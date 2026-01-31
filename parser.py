import asyncio
import json
import os
import re
import threading
import logging
import subprocess
import aiohttp
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if file == 'targets.json' else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return []
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                subprocess.run(["git", "config", "user.name", "NeptunBot"], check=False)
                subprocess.run(["git", "config", "user.email", "bot@neptun.com"], check=False)
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", "📍 Map Update", "--no-verify"], check=False)
                subprocess.run(["git", "push"], check=False)
                logger.info(f"🚀 Git Push успішний: {file}")
            except Exception as e:
                logger.error(f"❌ Git Error: {e}")

async def get_coords(place):
    if not place: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область, Україна", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"NeptunMapBot/1.0"}) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

def clean_location_name(text):
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|біля)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '')
    return name if len(name) > 2 else None

# ================= ПАРСЕР ТА РЕТРАНСЛЯТОР =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    
    # Фільтр Харкова
    if any(word in text_lc for word in ["харків", "область", "хнс", "чугуїв", "куп", "люботин"]):
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"♻️ Ретрансляція успішна")
        except Exception as e:
            logger.error(f"Помилка ретрансляції: {e}")

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_handler(event):
    raw_text = event.raw_text
    logger.info(f"📡 Аналіз повідомлення: {raw_text[:30]}...")

    loc_name = clean_location_name(raw_text)
    coords = await get_coords(loc_name)
    
    # FALLBACK: Якщо локацію не розпізнано, ставимо Харків
    if not coords:
        coords = [49.9935, 36.2304, "Харків (Моніторинг)"]
        logger.info("⚠️ Локацію не знайдено, використано дефолтні координати")

    # Визначення типу
    found_type = "unknown"
    types_db = db('types.json')
    for t_type, keywords in types_db.items():
        if any(word in raw_text.lower() for word in keywords):
            found_type = t_type; break

    new_target = {
        "id": event.id,
        "type": found_type,
        "lat": coords[0],
        "lng": coords[1],
        "label": f"{SYMBOLS.get(found_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=40)).isoformat()
    }

    targets = db('targets.json')
    if not isinstance(targets, list): targets = []
    
    # Оновлення списку (залишаємо останні 10 цілей)
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    targets = targets[-10:] 
    
    db('targets.json', targets)
    logger.info(f"✅ JSON ОНОВЛЕНО: {coords[2]}")

async def main():
    await client.start()
    logger.info("✅ СИСТЕМА ЗАПУЩЕНА")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
