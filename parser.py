import os
import re
import asyncio
import json
import logging
import subprocess
import aiohttp
import uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("NEPTUN_FINAL")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov', 'kharkiv_life']

# Параметри типів загроз
THREAT_PROFILES = {
    "шахед": {"type": "drone", "ttl": 60, "icon": "🛵"},
    "гербера": {"type": "drone", "ttl": 45, "icon": "🛵"},
    "молнія": {"type": "drone", "ttl": 30, "icon": "⚡"},
    "ланцет": {"type": "drone", "ttl": 20, "icon": "🎯"},
    "ракета": {"type": "missile", "ttl": 15, "icon": "🚀"},
    "балістика": {"type": "ballistics", "ttl": 10, "icon": "☄️"},
    "каб": {"type": "kab", "ttl": 30, "icon": "☄️"},
    "відбій": {"type": "clear", "ttl": 0, "icon": "✅"}
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# ================= СИСТЕМА ОБРОБКИ ДАНИХ =================

class DataController:
    _lock = asyncio.Lock()
    file_path = 'targets.json'

    @classmethod
    async def read(cls):
        async with cls._lock:
            if not os.path.exists(cls.file_path): return []
            try:
                with open(cls.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Read Error: {e}")
                return []

    @classmethod
    async def write(cls, data):
        async with cls._lock:
            try:
                with open(cls.file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 JSON Updated: {len(data)} objects")
                # Запуск Git синхронізації у фоні
                asyncio.create_task(cls.git_push())
            except Exception as e:
                logger.error(f"Write Error: {e}")

    @classmethod
    async def git_push(cls):
        try:
            subprocess.run(["git", "add", cls.file_path], check=False, capture_output=True)
            subprocess.run(["git", "commit", "-m", "📡 Tactical Update"], check=False, capture_output=True)
            proc = subprocess.run(["git", "push"], check=False, capture_output=True)
            if proc.returncode == 0: logger.info("🚀 Git Push Success")
        except: pass

# ================= ІНТЕЛЕКТУАЛЬНИЙ ПАРСЕР =================



def parse_message(text):
    text = text.lower()
    result = {
        "threat": "невідомо",
        "locations": [],
        "count": 1,
        "is_terminal": False,
        "is_status": False
    }

    # 1. Визначення термінальних станів
    if any(x in text for x in ["відбій", "чисто", "не відстежується", "зник"]):
        result["is_terminal"] = True
        return result

    # 2. Визначення типу загрози
    for key, profile in THREAT_PROFILES.items():
        if key in text:
            result["threat"] = key
            break

    # 3. Визначення кількості
    if "декілька" in text or "група" in text: result["count"] = "група"
    num_match = re.search(r'(\d+)\s*(бпла|шах|ракет|молн)', text)
    if num_match: result["count"] = int(num_match.group(1))

    # 4. Вилучення локацій (Складна логіка)
    # Шукаємо слова з великої літери після прийменників рухів
    loc_matches = re.findall(r'(?:на|через|в\s+район|бік|курсом\s+на)\s+([А-ЯІЇЄ][а-яіїє\']+)', text, re.IGNORECASE)
    
    # Обробка слешів (Кочеток/Чугуїв)
    slash_matches = re.findall(r'([А-ЯІЇЄ][а-яіїє\']+)(?=/| та)', text)
    
    raw_locations = list(set(loc_matches + slash_matches))
    result["locations"] = [l.strip() for l in raw_locations if len(l) > 3]

    if "на даний час" in text or "в області" in text and not result["locations"]:
        result["is_status"] = True

    return result

async def get_coords(loc):
    # Пріоритетний список (Харківщина) для миттєвої відповіді
    manual_db = {
        "Харків": [49.9935, 36.2304],
        "Чугуїв": [49.8356, 36.6863],
        "Богодухів": [50.1653, 35.5235],
        "Слатине": [50.2114, 36.1558],
        "Прудянка": [50.2383, 36.1264],
        "Безруки": [50.1683, 36.1186],
        "Кочеток": [49.8683, 36.7275],
        "Дергачі": [50.1136, 36.1205],
        "Люботин": [49.9486, 35.9281]
    }
    
    if loc in manual_db: return manual_db[loc] + [loc]
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{loc}, Харківська область, Україна", "format": "json", "limit": 1}
    headers = {"User-Agent": "TacticalParser_v6"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as r:
                if r.status == 200:
                    data = await r.json()
                    if data: return [float(data[0]["lat"]), float(data[0]["lon"]), loc]
    except: pass
    return None

# ================= ОБРОБНИКИ ТА ЛОГІКА ЦІЛЕЙ =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def master_handler(event):
    if not event.raw_text: return
    raw = event.raw_text
    parsed = parse_message(raw)
    
    targets = await DataController.read()
    updated = False

    # Логіка Відбою
    if parsed["is_terminal"]:
        if "відбій" in raw.lower(): targets = []
        else: # "не відстежується" - мітимо конкретні або всі завершеними
            for t in targets: t["status"] = "finished"
        await DataController.write(targets)
        return

    if parsed["is_status"]: return # Пропускаємо загальні зведення

    for loc in parsed["locations"]:
        coords = await get_coords(loc)
        if not coords: continue

        # Шукаємо дублікат для оновлення (якщо ціль вже є в цій локації)
        existing = next((t for t in targets if t["label"] == loc and t["status"] == "active"), None)
        
        if existing:
            existing["timestamp"] = int(datetime.now().timestamp())
            existing["expire_at"] = (datetime.now() + timedelta(minutes=THREAT_PROFILES.get(parsed["threat"], {"ttl": 20})["ttl"])).isoformat()
            existing["raw_text"] = raw
            existing["count"] = parsed["count"]
            logger.info(f"🔄 Updated target in {loc}")
        else:
            profile = THREAT_PROFILES.get(parsed["threat"], {"type": "unknown", "ttl": 20, "icon": "❓"})
            new_obj = {
                "uuid": str(uuid.uuid4()),
                "type": profile["type"],
                "icon": profile["icon"],
                "count": parsed["count"],
                "lat": coords[0],
                "lng": coords[1],
                "label": loc,
                "status": "active",
                "raw_text": raw,
                "timestamp": int(datetime.now().timestamp()),
                "expire_at": (datetime.now() + timedelta(minutes=profile["ttl"])).isoformat()
            }
            targets.append(new_obj)
            logger.info(f"📍 New target: {parsed['threat']} -> {loc}")
        updated = True

    if updated:
        await DataController.write(targets)

async def auto_cleaner():
    while True:
        await asyncio.sleep(30)
        targets = await DataController.read()
        now = datetime.now().isoformat()
        cleaned = [t for t in targets if t["expire_at"] > now and t["status"] == "active"]
        if len(cleaned) != len(targets):
            await DataController.write(cleaned)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🔥 NEPTUN V6.5 PRO ACTIVE")
    asyncio.create_task(auto_cleaner())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
