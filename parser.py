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
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "monitorkh1654,air_alert_ua,CXID").split(",")]

THREAT_CONFIG = {
    "lightning": {"keywords": ["блискавка", "lightning", "швидка ціль"], "ttl": 10},
    "kab": {"keywords": ["каб", "авіабомб", "керована", "уаб", "фаб"], "ttl": 40},
    "ballistic": {"keywords": ["баліст", "іскандер", "кинджал", "кн-23", "с-300", "с-400"], "ttl": 12},
    "missile": {"keywords": ["ракета", "пуск", "х-101", "х-59", "калібр"], "ttl": 25},
    "shahed": {"keywords": ["шахед", "шахєд", "герань", "мопед", "бпла"], "ttl": 75},
    "aircraft": {"keywords": ["міг-31", "су-34", "су-35", "ту-95", "літак"], "ttl": 30},
    "artillery": {"keywords": ["обстріл", "арт", "рсзв", "град"], "ttl": 15},
    "unknown": {"keywords": [], "ttl": 20}
}

DIRECTION_MAP = {
    "північ": (0.08, 0.0), "південь": (-0.08, 0.0), "схід": (0.0, 0.08), "захід": (0.0, -0.08),
    "пн-сх": (0.06, 0.06), "пн-зх": (0.06, -0.06), "пд-сх": (-0.06, 0.06), "пд-зх": (-0.06, -0.06),
    "курс на": (0.04, 0.04), "в напрямку": (0.03, 0.03), "над": (0.01, 0.01), "по": (0.02, 0.02)
}

# ================= LOGGING SETUP =================
os.makedirs("logs", exist_ok=True)
action_logger = logging.getLogger("TACTICAL_LOG")
action_logger.setLevel(logging.INFO)
log_formatter = logging.Formatter('%(asctime)s %(message)s', datefmt='[%Y-%m-%d %H:%M:%S]')

console_h = logging.StreamHandler()
console_h.setFormatter(log_formatter)
action_logger.addHandler(console_h)

file_h = RotatingFileHandler("logs/actions.log", maxBytes=15*1024*1024, backupCount=7, encoding='utf-8')
file_h.setFormatter(log_formatter)
action_logger.addHandler(file_h)

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
                        if "last_msg_id" in t: self.reply_map[t["last_msg_id"]] = t["target_id"]
            except Exception as e:
                action_logger.error(f"[SYSTEM_ERR] Load state: {e}")

    async def save_to_disk(self):
        async with self.lock:
            try:
                with open(self.file, "w", encoding="utf-8") as f:
                    json.dump(self.targets, f, ensure_ascii=False, indent=2)
                self.dirty = False
            except Exception as e:
                action_logger.error(f"[SYSTEM_ERR] Save disk: {e}")

    async def sync_loop(self):
        while True:
            await asyncio.sleep(30)
            if self.dirty:
                await self.save_to_disk()
                try:
                    proc = await asyncio.create_subprocess_shell(
                        "git add data/state.json && git commit -m 'Auto-Sync' && git push origin main",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    await proc.wait()
                except: pass

    async def cleaner_loop(self):
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            async with self.lock:
                expired_hashes = [h for h, t in self.processed_hashes.items() if (now - t).total_seconds() > 600]
                for h in expired_hashes: del self.processed_hashes[h]
                
                initial_count = len(self.targets)
                self.targets = [t for t in self.targets if datetime.fromisoformat(t["expire_at"]) > now]
                if len(self.targets) != initial_count:
                    self.dirty = True
                    action_logger.info(f"[JANITOR] Cleaned {initial_count - len(self.targets)} targets")

state = TacticalState()

# ================= ANALYSIS ENGINE =================

class CXIDAnalyzer:
    @staticmethod
    def get_type(text: str) -> str:
        text_l = text.lower()
        for t, cfg in THREAT_CONFIG.items():
            if any(kw in text_l for kw in cfg["keywords"]): return t
        return "unknown"

    @staticmethod
    def extract_loc_and_dir(text: str) -> Tuple[Optional[str], float, float, str]:
        text_l = text.lower()
        loc = None
        d_lat, d_lng, d_name = 0.0, 0.0, ""
        loc_match = re.search(r"(?:курс на|над|по|в районі|біля)\s+([А-ЯІЇЄ][а-яіїє']+)", text)
        if loc_match: loc = loc_match.group(1)
        for key, (slat, slng) in DIRECTION_MAP.items():
            if key in text_l:
                d_lat, d_lng, d_name = slat, slng, key
                break
        return loc, d_lat, d_lng, d_name

    @staticmethod
    async def geocode(name: str) -> Optional[Tuple[float, float]]:
        if not name or not http_session: return None
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": f"{name}, Україна", "format": "json", "limit": 1}
            async with http_session.get(url, params=params, timeout=5) as r:
                data = await r.json()
                if data: return float(data[0]["lat"]), float(data[0]["lon"])
        except: pass
        return None

    @staticmethod
    def calc_confidence(t_type: str, loc: Optional[str], d_name: str) -> int:
        score = 40
        if t_type != "unknown": score += 20
        if loc: score += 20
        if d_name: score += 20
        return min(score, 100)

# ================= AUTOMATED HANDLER =================

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNELS))
async def ingest_handler(event):
    if not event.raw_text: return
    text = event.raw_text
    
    if any(x in text.lower() for x in ["графік", "світло", "черг", "реклама", "підписка", "підпишись", "донат", "ads"]):
        return

    msg_hash = hashlib.md5(text.strip().lower().encode()).hexdigest()
    source = "Unknown"
    try:
        chat = await event.get_chat()
        source = f"@{chat.username}" if getattr(chat, 'username', None) else str(event.chat_id)
    except: pass

    async with state.lock:
        if msg_hash in state.processed_hashes:
            action_logger.info(f"[SKIP] reason=duplicate src={source}")
            return
        state.processed_hashes[msg_hash] = datetime.now()

    t_type = CXIDAnalyzer.get_type(text)
    loc, d_lat, d_lng, d_name = CXIDAnalyzer.extract_loc_and_dir(text)
    geo = await CXIDAnalyzer.geocode(loc)
    conf = CXIDAnalyzer.calc_confidence(t_type, loc, d_name)
    
    if conf < 50 and t_type == "unknown":
        action_logger.info(f"[SKIP] reason=low_confidence src={source}")
        return

    async with state.lock:
        target = None
        if event.reply_to:
            t_id = state.reply_map.get(event.reply_to.reply_to_msg_id)
            target = next((t for t in state.targets if t["target_id"] == t_id), None)
        
        if not target and geo:
            for t in state.targets:
                dist = abs(t["lat"] - geo[0]) + abs(t["lng"] - geo[1])
                if dist < 0.5 and t["type"] == t_type:
                    target = t; break

        now = datetime.now()
        
        if target:
            status = "moving"
            if "вибух" in text.lower(): status = "destroyed"
            elif "не фіксується" in text.lower(): status = "lost"
            
            if geo: 
                target["lat"], target["lng"] = geo[0], geo[1]
                target["current_location"] = loc
            elif d_name and target.get("lat") != 49.0: 
                target["lat"] += d_lat
                target["lng"] += d_lng
            
            target["status"] = status
            ttl_ext = 5 if status in ["destroyed", "lost"] else THREAT_CONFIG.get(target["type"], {"ttl":20})["ttl"]
            target["expire_at"] = (now + timedelta(minutes=ttl_ext)).isoformat()
            target["history"].append({"t": now.strftime("%H:%M"), "txt": text[:100], "dir": d_name, "conf": conf})
            target["history"] = target["history"][-20:]
            state.reply_map[event.id] = target["target_id"]
            action_logger.info(f"[UPDATE] target={target['target_id']} status={status} loc={loc or 'same'} src={source} conf={conf}")
        else:
            new_id = str(uuid.uuid4())[:8]
            ttl = THREAT_CONFIG.get(t_type, {"ttl":20})["ttl"]
            new_target = {
                "target_id": new_id, 
                "type": t_type, 
                "status": "detected",
                "current_location": loc or "unknown",
                "lat": geo[0] if geo else 49.0, 
                "lng": geo[1] if geo else 31.0,
                "history": [{"t": now.strftime("%H:%M"), "txt": text[:100], "dir": d_name, "conf": conf}],
                "expire_at": (now + timedelta(minutes=ttl)).isoformat(), 
                "last_msg_id": event.id
            }
            state.targets.append(new_target)
            state.reply_map[event.id] = new_id
            action_logger.info(f"[ADD] target={new_id} type={t_type} loc={loc or 'unknown'} src={source} conf={conf}")
        
        state.dirty = True

# ================= RUNNER =================

async def main():
    global http_session
    # 1. Инициализация сессии до старта обработчиков
    http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    
    try:
        # 2. Инициализация клиента
        await client.start(bot_token=BOT_TOKEN)
        action_logger.info("[SYSTEM] Engine started. Automated monitoring ON.")
        
        # 3. Запуск всех конкурентных задач, включая прослушивание
        await asyncio.gather(
            client.run_until_disconnected(),
            state.sync_loop(),
            state.cleaner_loop()
        )
    except Exception as e:
        action_logger.critical(f"[FATAL] System crash: {e}")
    finally:
        if http_session:
            await http_session.close()

if __name__ == "__main__":
    try: 
        asyncio.run(main())
    except KeyboardInterrupt: 
        action_logger.info("[SYSTEM] Shutdown by operator.")
