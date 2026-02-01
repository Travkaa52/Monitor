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

DISTRICTS_MAP = {
    "Богодухів": "Bohodukhivskyi", "Харків": "Kharkivskyi",
    "Чугуїв": "Chuhuivskyi", "Ізюм": "Iziumskyi",
    "Куп": "Kupianskyi", "Лозів": "Lozivskyi", "Красноград": "Krasnohradskyi"
}

SYMBOLS = {
    "air_defense": "Робота:🛡️ППО", "drone": "🛵Шахед/Гербера", "missile": "🚀 Ракета",
    "kab": "Загроза:☄️КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸Розвідник",
    "aircraft": "✈️ Авіація", "artillery": "💥 Арта", "s300": "🚜 С-300",
    "molniya": "⚡Молнія", "unknown": "❓ Ціль"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# --- СИСТЕМНІ ФУНКЦІЇ ---

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: 
                    res = json.load(f)
                    return res if isinstance(res, (list, dict)) else ([] if 'targets' in file else {})
            except: return [] if 'targets' in file else {}
        else:
            # ВИПРАВЛЕННЯ: Фільтрація часу
            if 'targets' in file and isinstance(data, list):
                now = datetime.now()
                # Ми залишаємо мітку, якщо вона закінчується в майбутньому 
                # Додаємо запас 1 хвилину на випадок розсинхронізації часу
                data = [t for t in data if datetime.fromisoformat(t.get('expire_at')) > (now - timedelta(minutes=1))]

            # Атомарний запис (спочатку в темп, потім заміна)
            try:
                with open(file + ".tmp", 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(file + ".tmp", file)
                logger.info(f"💾 {file} збережено. Записів: {len(data) if isinstance(data, list) else 'dict'}")
            except Exception as e:
                logger.error(f"❌ Помилка запису файлу: {e}")

            # Git Sync у фоні
            try:
                subprocess.Popen(["git", "add", file], stdout=subprocess.DEVNULL)
                subprocess.Popen(["git", "commit", "-m", "update"], stdout=subprocess.DEVNULL)
                subprocess.Popen(["git", "push"], stdout=subprocess.DEVNULL)
            except: pass

async def get_coords(place):
    if not place or len(place.strip()) < 3: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place}, Харківська область", "format": "json", "limit": 1,
        "countrycodes": "ua", "accept-language": "uk"
    }
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": f"Neptun_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                data = await resp.json()
                if data: return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

def get_threat_type(text):
    m = {
        "drone": ["шахед", "мопед", "shahed", "гербера"],
        "missile": ["ракета", "крилата", "балістика"],
        "kab": ["каб", "авіабомб", "фаб"],
        "recon": ["розвідник", "supercam", "zala", "орлан", "бпла"],
        "mrls": ["рсзо", "рсзв", "град"],
        "molniya": ["молния", "молнія"]
    }
    t_lc = text.lower()
    for t_type, keys in m.items():
        if any(k in t_lc for k in keys): return t_type
    return "unknown"

# --- ОБРОБНИКИ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    if not event.raw_text: return
    if any(w in event.raw_text.lower() for w in ["харків", "область", "бпла", "каб", "ракета"]):
        try: await client.send_message(MY_CHANNEL, event.message)
        except: pass

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def main_parser(event):
    raw_text = event.raw_text or event.message.message or ""
    if not raw_text or raw_text.startswith('/'): return
    
    logger.info(f"🔎 Аналіз поста: {raw_text[:40].strip()}...")
    text_lc = raw_text.lower()

    # 1. ТРИВОГИ
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db_sync('alerts.json')
        upd = False
        for ua, en in DISTRICTS_MAP.items():
            if ua.lower() in text_lc:
                alerts[en] = {"active": "🔴" in raw_text or "тривога" in text_lc}
                upd = True
        if upd: db_sync('alerts.json', alerts)
        return

    # 2. ЦІЛІ
    g_threat = get_threat_type(text_lc)
    new_entries = []
    
    for line in raw_text.split('\n'):
        if len(line.strip()) < 4: continue
        
        # Очищення назви (видаляємо н.п., біля, цифри)
        p = re.sub(r'(\d+|🚨|⚠️|Увага|БПЛА|Ракета|КАБ|Шахед|н\.п\.|біля|нп|—|-|:)', '', line, flags=re.IGNORECASE).strip()
        p = re.split(r'(на|в напрямку|через|бік|межах|в сторону)', p, flags=re.IGNORECASE)[0].strip()
        p = re.sub(r'^(в|у|селище|село|місто|смт)\s+', '', p, flags=re.IGNORECASE).strip()

        coords = await get_coords(p)
        if not coords and "харків" in line.lower(): coords = [49.9935, 36.2304, "Харків"]

        if coords:
            threat = get_threat_type(line)
            if threat == "unknown": threat = g_threat
            
            new_entries.append({
                "id": f"m{event.id}_{uuid.uuid4().hex[:4]}",
                "type": threat,
                "lat": coords[0], "lng": coords[1],
                "label": f"{SYMBOLS.get(threat, '❓')} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
            })
            logger.info(f"✅ Додано в список: {coords[2]}")

    if new_entries:
        targets = db_sync('targets.json')
        # Видаляємо старі записи саме цього повідомлення, щоб уникнути дублів при редагуванні
        targets = [t for t in targets if not str(t.get('id','')).startswith(f"m{event.id}")]
        targets.extend(new_entries)
        db_sync('targets.json', targets)

@client.on(events.NewMessage(incoming=True))
async def admin_panel(event):
    if not event.is_private or event.sender_id not in ADMIN_IDS: return
    if '/clear' in event.raw_text:
        db_sync('targets.json', [])
        await event.respond("🧹 Карта очищена")
    elif '/info' in event.raw_text:
        t = db_sync('targets.json')
        await event.respond(f"📍 Міток: {len(t)}")

# --- ЗАПУСК ---
async def main():
    await client.start()
    logger.info("🚀 БОТ ПРАЦЮЄ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
