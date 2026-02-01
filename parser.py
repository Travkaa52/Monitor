import asyncio
import json
import os
import re
import threading
import logging
import subprocess
import aiohttp
import uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- НАЛАШТУВАННЯ ЛОГІВ ---
logging.basicConfig(format='[%(levelname)s] %(asctime)s: %(message)s', level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

# --- КОНФІГУРАЦІЯ ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 

MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']
ADMIN_IDS = [5423792783] 

SYMBOLS = {
    "air_defense": "🛡️ППО", "drone": "🛵Шахед", "missile": "🚀Ракета",
    "kab": "☄️КАБ", "mrls": "🔥РСЗВ", "recon": "🛸Розвідник",
    "aircraft": "✈️Авіація", "artillery": "💥Арта", "s300": "🚜С-300",
    "molniya": "⚡Молнія", "unknown": "❓Ціль"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()
git_lock = threading.Lock()

# --- СИСТЕМНІ ФУНКЦІЇ ---

def safe_git_push(file):
    if git_lock.acquire(blocking=False):
        try:
            lock_path = ".git/index.lock"
            if os.path.exists(lock_path): os.remove(lock_path)
            subprocess.run(["git", "add", file], check=False, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"update {datetime.now().strftime('%H:%M')}"], check=False, capture_output=True)
            subprocess.run(["git", "push"], check=False, capture_output=True)
        finally:
            git_lock.release()

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return []
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return []
        else:
            if 'targets' in file:
                now = datetime.now()
                data = [t for t in data if datetime.fromisoformat(t.get('expire_at')) > (now - timedelta(seconds=10))]
            
            with open(file + ".tmp", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(file + ".tmp", file)
            logger.info(f"💾 {file} збережено ({len(data)} зап.)")
            threading.Thread(target=safe_git_push, args=(file,), daemon=True).start()

async def get_coords(place):
    if not place or len(place.strip()) < 3: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": f"Neptun_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                data = await resp.json()
                if data: return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

def get_threat_type(text):
    text = text.lower()
    mapping = {
        "drone": ["шахед", "мопед", "гербера"],
        "missile": ["ракета", "х-", "іскандер"],
        "kab": ["каб", "фаб", "авіабомб"],
        "recon": ["розвід", "орлан", "zala", "суперкам", "бпла"],
        "mrls": ["рсзв", "град", "смерч"],
        "s300": ["с300", "с-300"]
    }
    for t_type, keys in mapping.items():
        if any(k in text for k in keys): return t_type
    return "unknown"

# --- ОБРОБНИКИ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    """ Копіює з чужих каналів у твій """
    if not event.raw_text: return
    # Якщо текст містить ключові слова - пересилаємо
    if any(w in event.raw_text.lower() for w in ["харків", "бпла", "каб", "ракета", "увага"]):
        await client.send_message(MY_CHANNEL, event.message)
        logger.info(f"📩 Переслано повідомлення {event.id}")

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def main_parser(event):
    """ Аналізує все, що з'явилося у ТВОЄМУ каналі (в т.ч. переслане ботом) """
    raw_text = event.raw_text or ""
    if not raw_text or raw_text.startswith('/'): return
    
    logger.info(f"🔎 Аналіз поста у {MY_CHANNEL}...")
    
    targets = db_sync('targets.json')
    # Очищуємо старі мітки цього повідомлення (якщо воно редагується)
    targets = [t for t in targets if not str(t.get('id','')).startswith(f"m{event.id}")]
    
    global_type = get_threat_type(raw_text)
    new_found = False

    for line in raw_text.split('\n'):
        if len(line.strip()) < 3: continue
        
        # 1. Шукаємо населений пункт (чистимо рядок)
        p = re.sub(r'(\d+|🚨|⚠️|БПЛА|Ракета|КАБ|Шахед|н\.п\.|біля|нп|в напрямку|курсом|—|-|:)', '', line, flags=re.IGNORECASE).strip()
        p = re.split(r'(на|в|через|бік|межах)', p, flags=re.IGNORECASE)[0].strip()
        p = re.sub(r'^(у|в|селище|село|місто|смт)\s+', '', p, flags=re.IGNORECASE).strip()

        coords = await get_coords(p)
        # Підстраховка для Харкова
        if not coords and "харків" in line.lower():
            coords = [49.9935, 36.2304, "Харків"]

        if coords:
            threat = get_threat_type(line)
            if threat == "unknown": threat = global_type
            
            targets.append({
                "id": f"m{event.id}_{uuid.uuid4().hex[:4]}",
                "type": threat,
                "lat": coords[0], "lng": coords[1],
                "label": f"{SYMBOLS[threat]} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
            })
            new_found = True
            logger.info(f"📍 Знайдено ціль: {threat} у {coords[2]}")

    if new_found:
        db_sync('targets.json', targets)

# --- ЗАПУСК ---
async def main():
    await client.start()
    logger.info("🚀 БОТ ПРАЦЮЄ")
    await client.run_until_disconnected()

asyncio.run(main())
