import os
import re
import asyncio
import json
import logging
import subprocess
import aiohttp
import uuid
import hashlib
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

# ================= CONFIGURATION =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "monitorkh1654,air_alert_ua,ukraine_air_alarm").split(",")]

THREAT_CONFIG = {
    "ballistic": {"keywords": ["баліст", "іскандер", "кинджал", "кн-23", "с-300", "с-400", "циркон", "точк"], "ttl": 12},
    "missile": {"keywords": ["ракета", "пуск", "х-101", "х-555", "х-59", "х-31", "х-22", "калібр", "онікс"], "ttl": 25},
    "kab": {"keywords": ["каб", "авіабомб", "керована", "уаб", "фаб", "бомб"], "ttl": 40},
    "shahed": {"keywords": ["шахед", "шахєд", "герань", "мопед", "бпла", "ланцет"], "ttl": 75},
    "recon": {"keywords": ["орлан", "зала", "розвід", "суперкам", "куб"], "ttl": 45},
    "aircraft": {"keywords": ["міг-31", "су-34", "су-35", "ту-95", "ту-22", "літак", "су-57"], "ttl": 30},
    "artillery": {"keywords": ["обстріл", "арт", "рсзв", "град", "ураган", "смерч"], "ttl": 15},
    "unknown": {"keywords": [], "ttl": 20}
}

DIRECTION_MAP = {
    "північ": (0.08, 0.0), "південь": (-0.08, 0.0), "схід": (0.0, 0.08), "захід": (0.0, -0.08),
    "пн-сх": (0.06, 0.06), "пн-зх": (0.06, -0.06), "пд-сх": (-0.06, 0.06), "пд-зх": (-0.06, -0.06),
    "курс на": (0.03, 0.03), "в напрямку": (0.02, 0.02)
}

# ================= LOGGING SETUP =================
os.makedirs("logs", exist_ok=True)
action_logger = logging.getLogger("ACTION_LOG")
action_logger.setLevel(logging.INFO)

# Формат лога согласно ТЗ
log_formatter = logging.Formatter('%(asctime)s %(message)s', datefmt='[%Y-%m-%d %H:%M:%S]')

# Вывод в консоль
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
action_logger.addHandler(console_handler)

# Вывод в файл с ротацией (10MB на файл, храним 5 последних)
file_handler = RotatingFileHandler("logs/actions.log", maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(log_formatter)
action_logger.addHandler(file_handler)

# Глобальная сессия
http_session: Optional[aiohttp.ClientSession] = None

# ================= STATE MANAGER =================

class TacticalState:
    def __init__(self):
        self.targets: List[Dict] = []
        self.reply_map: Dict[int, str] = {}
        self.processed_hashes: Dict[str, datetime] = {}
        self.lock = asyncio.Lock()
        self.dirty = False
        self.file = "data/state.json"
        os.makedirs("data", exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.file):
            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    self.targets = json.load(f)
                    for t in self.targets:
                        if "last_msg_id" in t:
                            self.reply_map[t["last_msg_id"]] = t["target_id"]
            except Exception as e:
                action_logger.error(f"[ERROR] State load: {e}")

    async def save_to_disk(self):
        async with self.lock:
            try:
                with open(self.file, "w", encoding="utf-8") as f:
                    json.dump(self.targets, f, ensure_ascii=False, indent=2)
                self.dirty = False
            except Exception as e:
                action_logger.error(f"[ERROR] Disk save: {e}")

    async def sync_loop(self):
        while True:
            await asyncio.sleep(30)
            if self.dirty:
                await self.save_to_disk()
                try:
                    # Асинхронный вызов гита без блокировки
                    proc = await asyncio.create_subprocess_shell(
                        "git add data/state.json && git commit -m 'Auto-Update' && git pull --rebase origin main && git push origin main",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    await proc.wait()
                except Exception as e:
                    action_logger.error(f"[ERROR] Git sync: {e}")

    async def hash_cleaner_loop(self):
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            async with self.lock:
                expired = [h for h, t in self.processed_hashes.items() if (now - t).total_seconds() > 600]
                for h in expired:
                    del self.processed_hashes[h]

state = TacticalState()

# ================= LOGIC ENGINE =================

class IntelligentAnalyzer:
    @staticmethod
    def get_threat_type(text: str) -> str:
        text_l = text.lower()
        for t_type, cfg in THREAT_CONFIG.items():
            if any(kw in text_l for kw in cfg["keywords"]):
                return t_type
        return "unknown"

    @staticmethod
    def extract_location(text: str) -> Optional[str]:
        patterns = [
            r"(?:на|у|в|біля|повз|район|через)\s+([А-ЯІЇЄ][а-яіїє']+)",
            r"([А-ЯІЇЄ][а-яіїє']+)\s+(?:загроза|вибух|курс|напрямок)"
        ]
        for p in patterns:
            m = re.search(p, text)
            if m and len(m.group(1)) > 3: return m.group(1)
        return None

    @staticmethod
    def parse_direction_shift(text: str) -> Tuple[float, float, str]:
        text_l = text.lower()
        for key, (slat, slng) in DIRECTION_MAP.items():
            if key in text_l:
                return slat, slng, key
        return 0.0, 0.0, ""

    @staticmethod
    async def geocode(name: str) -> Optional[Tuple[float, float, str]]:
        if not name or not http_session: return None
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": f"{name}, Україна", "format": "json", "limit": 1}
        try:
            async with http_session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data = await r.json()
                    if data:
                        return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(",")[0]
        except: pass
        return None

    @staticmethod
    def find_best_target(t_type: str, loc_name: Optional[str], coords: Optional[Tuple[float, float]]) -> Tuple[Optional[Dict], int]:
        now = datetime.now()
        best_t = None
        max_score = 0
        for t in state.targets:
            if datetime.fromisoformat(t["expire_at"]) < now: continue
            score = 0
            if t["type"] == t_type: score += 40
            if loc_name and t.get("current_location") == loc_name: score += 40
            if coords and t.get("lat"):
                dist = abs(t["lat"] - coords[0]) + abs(t["lng"] - coords[1])
                if dist < 0.4: score += 35
            if score > max_score:
                max_score = score
                best_t = t
        return best_t, max_score

# ================= TELEGRAM HANDLER (AUTO INGEST) =================

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNELS))
async def auto_handler(event):
    if not event.raw_text or len(event.raw_text) < 3: return
    
    text = event.raw_text
    msg_hash = hashlib.md5(re.sub(r'\s+', '', text).lower().encode()).hexdigest()
    
    source = "Unknown"
    try:
        chat = await event.get_chat()
        source = f"@{chat.username}" if getattr(chat, 'username', None) else str(event.chat_id)
    except: pass

    # 1. Проверка на дубликат (SKIP)
    async with state.lock:
        if msg_hash in state.processed_hashes:
            action_logger.info(f"[SKIP] reason=duplicate src={source}")
            return
        state.processed_hashes[msg_hash] = datetime.now()

    t_type = IntelligentAnalyzer.get_threat_type(text)
    
    # 2. Проверка на шум (SKIP)
    if t_type == "unknown" and len(text) < 15:
        action_logger.info(f"[SKIP] reason=noise src={source}")
        return

    loc_name = IntelligentAnalyzer.extract_location(text)
    geo = await IntelligentAnalyzer.geocode(loc_name)
    d_lat, d_lng, d_name = IntelligentAnalyzer.parse_direction_shift(text)
    
    target_id = state.reply_map.get(event.reply_to.reply_to_msg_id) if event.reply_to else None
    
    async with state.lock:
        target = None
        confidence = 100
        
        if target_id:
            target = next((t for t in state.targets if t["target_id"] == target_id), None)
        
        if not target:
            target, confidence = IntelligentAnalyzer.find_best_target(t_type, loc_name, (geo[0], geo[1]) if geo else None)

        now_dt = datetime.now()
        
        # 3. Обновление цели (UPDATE)
        if target and confidence >= 35:
            update_details = []
            if geo:
                target["lat"], target["lng"] = geo[0], geo[1]
                target["current_location"] = loc_name
                update_details.append(f"loc={loc_name}")
            elif d_name:
                target["lat"] += d_lat
                target["lng"] += d_lng
                update_details.append(f"dir={d_name}")

            # Регулировка TTL
            is_clear = any(x in text.lower() for x in ["збито", "мінус", "знищено", "чисто", "відбій"])
            ttl_min = 2 if is_clear else THREAT_CONFIG.get(target["type"], {"ttl": 20})["ttl"]
            target["expire_at"] = (now_dt + timedelta(minutes=ttl_min)).isoformat()
            update_details.append(f"ttl={ttl_min}m")

            target["history"].append({
                "time": now_dt.strftime("%H:%M:%S"),
                "text": text[:100],
                "conf": confidence,
                "src": source
            })
            state.reply_map[event.id] = target["target_id"]
            action_logger.info(f"[UPDATE] target={target['target_id']} {' '.join(update_details)} src={source} conf={confidence}")
        
        # 4. Создание новой цели (ADD)
        else:
            new_id = str(uuid.uuid4())[:8]
            ttl_min = THREAT_CONFIG.get(t_type, {"ttl": 20})["ttl"]
            new_target = {
                "target_id": new_id,
                "type": t_type,
                "current_location": loc_name or "Уточнюється",
                "lat": geo[0] if geo else 49.0,
                "lng": geo[1] if geo else 31.0,
                "history": [{"time": now_dt.strftime("%H:%M:%S"), "text": text[:100], "conf": 100, "src": source}],
                "detected_at": now_dt.isoformat(),
                "expire_at": (now_dt + timedelta(minutes=ttl_min)).isoformat(),
                "last_msg_id": event.id
            }
            state.targets.append(new_target)
            state.reply_map[event.id] = new_id
            action_logger.info(f"[ADD] target={new_id} type={t_type} loc={new_target['current_location']} src={source} conf=100")
        
        state.dirty = True

# ================= SERVICE LOOPS =================

async def janitor():
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        async with state.lock:
            initial_count = len(state.targets)
            state.targets = [t for t in state.targets if datetime.fromisoformat(t["expire_at"]) > now]
            if len(state.targets) != initial_count:
                state.dirty = True
                action_logger.info(f"[SYSTEM] Cleanup: removed {initial_count - len(state.targets)} expired targets")

async def connection_manager():
    while True:
        try:
            if not client.is_connected():
                await client.start(bot_token=BOT_TOKEN)
            action_logger.info("[SYSTEM] Ingest online. Monitoring channels...")
            await client.run_until_disconnected()
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception as e:
            action_logger.error(f"[SYSTEM] Connection error: {e}. Reconnecting...")
            await asyncio.sleep(10)

async def main():
    global http_session
    http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    try:
        await asyncio.gather(
            connection_manager(),
            state.sync_loop(),
            state.hash_cleaner_loop(),
            janitor()
        )
    finally:
        if http_session:
            await http_session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        action_logger.info("[SYSTEM] Shutdown initiated by operator")
