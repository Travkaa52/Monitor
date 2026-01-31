import asyncio
import json
import os
import re
import threading
import logging
import subprocess
import aiohttp
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'monitorkh1654', 'radar_kharkov']

# Словник символів для карти
SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= ГЕО-ФУНКЦІЇ =================

def clean_location_name(text):
    """Витягує локацію, ігноруючи типи загроз та емодзі."""
    # Очищення від службових символів
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед)', '', text, flags=re.IGNORECASE).strip()
    # Пошук основного населеного пункту до напрямку руху
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|біля)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '')
    return name if len(name) > 2 else None

async def get_coords(place):
    """Отримує координати через OpenStreetMap (Nominatim)."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область, Україна", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"NeptunMapBot"}) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: return None

# ================= ЛОГІКА РЕТРАНСЛЯТОРА =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    """Фільтрує чужі канали та пересилає тільки Харківську область."""
    raw_text = event.raw_text
    loc_candidate = clean_location_name(raw_text)
    
    # Перевіряємо, чи є в тексті пряма згадка області або знайдена валідна локація
    is_kharkiv = any(word in raw_text.lower() for word in ["харків", "область", "хнс", "хнр"])
    
    if is_kharkiv or (loc_candidate and await get_coords(loc_candidate)):
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"♻️ Ретрансляція: {loc_candidate if loc_candidate else 'Харків'}")
        except Exception as e:
            logger.error(f"Помилка ретрансляції: {e}")

# ================= ЛОГІКА ПАРСЕРА =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_handler(event):
    """Парсить повідомлення у твоєму каналі та оновлює targets.json."""
    raw_text = event.raw_text
    loc_name = clean_location_name(raw_text)
    if not loc_name: return

    coords = await get_coords(loc_name)
    if not coords: return

    # Визначення типу загрози
    types_db = db('types.json')
    text_lc = raw_text.lower()
    found_type = "unknown"
    for t_type, keywords in types_db.items():
        if any(word in text_lc for word in keywords):
            found_type = t_type; break

    # Створення об'єкта для мапи
    new_target = {
        "id": event.id,
        "type": found_type,
        "count": 1,
        "status": "active",
        "lat": coords[0],
        "lng": coords[1],
        "label": f"{SYMBOLS.get(found_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=40)).isoformat()
    }

    # Збереження та пуш
    targets = db('targets.json')
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    db('targets.json', targets)
    logger.info(f"📍 Мапа оновлена: {coords[2]}")

# ================= СИСТЕМНІ ФУНКЦІЇ =================

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if file == 'targets.json' else {}
            with open(file, 'r', encoding='utf-8') as f: return json.load(f)
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", "📡 Tactical Sync", "--no-verify"], check=False)
                subprocess.run(["git", "push"], check=False)
            except: pass

async def main():
    await client.start()
    print("✅ СИСТЕМА NEPTUN ЗАПУЩЕНА")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())


