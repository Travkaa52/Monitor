import os
import re
import asyncio
import json
import threading
import logging
import subprocess
import aiohttp
import uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s: %(message)s')
logger = logging.getLogger("NEPTUN_TACTICAL")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

MY_CHANNEL = 'monitorkh1654'
IS_PARSING_ENABLED = True

# Пам'ять для зв'язків: {message_id: target_id}
REPLY_MAP = {}

THREAT_TYPES = {
    "ballistics": {"keywords": ["баліст", "іскандер", "кинджал"], "icon": "img/ballistic.png", "label": "Балістика", "ttl": 15},
    "missile": {"keywords": ["ракета", "пуск", "х-59"], "icon": "img/missile.png", "label": "Ракета", "ttl": 15},
    "kab": {"keywords": ["каб", "авіабомб", "керована"], "icon": "img/kab.png", "label": "КАБ", "ttl": 25},
    "shahed": {"keywords": ["шахед", "шахєд", "герань", "мопед"], "icon": "img/drone.png", "label": "Шахед", "ttl": 45},
    "unknown": {"keywords": [], "icon": "img/unknown.png", "label": "Невідомо", "ttl": 20}
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= СИСТЕМНІ ФУНКЦІЇ =================

def db_sync(file, data=None):
    """Синхронізація з файлом та GitHub з примусовим оновленням"""
    with db_lock:
        if data is None:
            if not os.path.exists(file): return []
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    return json.loads(content) if content else []
            except Exception as e:
                logger.error(f"❌ Помилка читання JSON: {e}")
                return []
        else:
            try:
                # Атомарний запис
                temp_file = f"{file}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, file)
                
                # Запуск Git у фоні
                threading.Thread(target=git_push_force, daemon=True).start()
            except Exception as e:
                logger.error(f"❌ Помилка запису JSON: {e}")

def git_push_force():
    """Примусовий пуш для миттєвого оновлення фронтенду"""
    try:
        # Скидаємо можливі блокування Git
        if os.path.exists(".git/index.lock"): os.remove(".git/index.lock")
        
        subprocess.run(["git", "add", "targets.json"], check=False)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update"], check=False, capture_output=True)
        # Використовуємо push --force, щоб GitHub стовідсотково прийняв зміни
        subprocess.run(["git", "push", "--force"], check=False, capture_output=True)
        logger.info("🚀 Дані відправлено на GitHub")
    except Exception as e:
        logger.error(f"❌ Git Error: {e}")

# ================= ОБРОБКА ТЕКСТУ =================

def clean_location_name(text):
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Шахед|Ракета|Зафіксовано|Попередньо|!|\.)', ' ', text, flags=re.IGNORECASE).strip()
    match = re.search(r'(?:курсом|на|в|через|бік|напрямок|біля|у бік|район)\s+([А-ЯІЇЄ][а-яіїє\']+)', clean, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name.endswith('у'): name = name[:-1] + 'а'
        return name
    return None

async def get_coords_online(place_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place_name}, Харківська область, Україна", "format": "json", "limit": 1}
    headers = {"User-Agent": "TacticalParser_v4"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=5) as resp:
                data = await resp.json()
                if data: return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: return None

# ================= ГОЛОВНИЙ ОБРОБНИК =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    global REPLY_MAP
    if not IS_PARSING_ENABLED or not event.raw_text: return
    
    text_lc = event.raw_text.lower()
    msg_id = event.id
    reply_to_id = event.reply_to.reply_to_msg_id if event.reply_to else None

    # Очищення
    if any(k in text_lc for k in ["відбій", "чисто", "відміна"]):
        db_sync('targets.json', [])
        REPLY_MAP.clear()
        logger.info("🧹 CLEAR MAP")
        return

    # Завантажуємо поточні цілі
    targets = db_sync('targets.json')
    target_id = None
    updated = False

    # ПЕРЕВІРКА REPLY (Найважливіше!)
    if reply_to_id and reply_to_id in REPLY_MAP:
        target_id = REPLY_MAP[reply_to_id]
        logger.info(f"🔍 Спроба оновити ціль {target_id} (реплай на {reply_to_id})")
        
        for t in targets:
            if t['id'] == target_id:
                loc_name = clean_location_name(event.raw_text)
                coords = await get_coords_online(loc_name) if loc_name else None
                
                if coords:
                    t['lat'], t['lng'] = coords[0], coords[1]
                    t['label'] = f"{t['label'].split('|')[0].strip()} | {coords[2]}"
                
                t['time'] = datetime.now().strftime("%H:%M")
                t['expire_at'] = (datetime.now() + timedelta(minutes=20)).isoformat()
                
                if any(k in text_lc for k in ["зник", "мінус", "немає"]):
                    t['expire_at'] = (datetime.now() + timedelta(seconds=30)).isoformat()
                
                updated = True
                logger.info(f"✅ Ціль {target_id} ОНОВЛЕНО")
                break

    # СТВОРЕННЯ НОВОЇ (якщо не оновили стару)
    if not updated:
        loc_name = clean_location_name(event.raw_text)
        coords = await get_coords_online(loc_name) if loc_name else None
        
        if coords:
            target_id = str(uuid.uuid4())[:8]
            threat_id = next((tid for tid, info in THREAT_TYPES.items() if any(k in text_lc for k in info["keywords"])), "unknown")
            
            new_target = {
                "id": target_id,
                "type": threat_id,
                "lat": coords[0], "lng": coords[1],
                "label": f"{THREAT_TYPES[threat_id]['label']} | {coords[2]}",
                "icon": THREAT_TYPES[threat_id]["icon"],
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=THREAT_TYPES[threat_id]['ttl'])).isoformat()
            }
            targets.append(new_target)
            logger.info(f"✨ Створено НОВУ ціль {target_id}")

    # Фіксація у мапі та збереження
    if target_id:
        REPLY_MAP[msg_id] = target_id
        db_sync('targets.json', targets)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 PARSER V4 FULL FORCE ONLINE")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
