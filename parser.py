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
    "air_defense": "Робота:🛡️ППО", "drone": "БПЛА типу:Гербера/Шахед", "missile": "🚀 Ракета",
    "kab": "Загроза:☄️КАБ", "mrls": "🔥 РСЗВ", "recon": "БПЛА типу:🛸Розвідник",
    "aircraft": "✈️ Авіація", "artillery": "💥 Арта", "s300": "🚜 С-300",
    "molniya": "БПЛА типу:⚡Молнія", "unknown": "❓ Невизначений тип загрози"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# --- СИСТЕМНІ ФУНКЦІЇ ---

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            if 'targets' in file and isinstance(data, list):
                now = datetime.now()
                data = [t for t in data if datetime.fromisoformat(t.get('expire_at')) > now]

            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 {file} збережено. Записів: {len(data) if isinstance(data, list) else 'dict'}")

            try:
                subprocess.run(["git", "add", file], check=False, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"📡 {file} update"], check=False, capture_output=True)
                subprocess.Popen(["git", "push"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except: pass

async def get_coords(place):
    if not place or len(place.strip()) < 3: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place}, Харківська область", "format": "json", "limit": 1,
        "countrycodes": "ua", "accept-language": "uk",
        "viewbox": "34.5,50.5,38.5,48.5", "bounded": 1
    }
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": f"Neptun_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                data = await resp.json()
                if data: return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except Exception as e:
        logger.error(f"Geo Error: {e}")
    return None

def get_threat_type(text):
    mapping = {
        "drone": ["шахед", "мопед", "shahed", "гербера"],
        "missile": ["ракета", "крилата", "балістика"],
        "kab": ["каб", "авіабомб", "фаб"],
        "recon": ["розвідник", "розвідувальні", "supercam", "zala", "орлан", "бпла"],
        "mrls": ["рсзо", "рсзв", "град", "ураган"],
        "s300": ["с300", "с-300"],
        "artillery": ["арта", "артилерія", "вихід"],
        "aircraft": ["міг", "су-", "авіація"],
        "molniya": ["молния", "молнія"]
    }
    text_lc = text.lower()
    for t_type, keys in mapping.items():
        if any(k in text_lc for k in keys): return t_type
    return "unknown"

# --- ОБРОБНИКИ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    """Крок 1: Копіювання повідомлень з джерел у ваш канал"""
    if not event.raw_text: return
    keywords = ["харків", "область", "чугуїв", "куп", "бпла", "шахед", "каб", "ракета", "загроза"]
    if any(w in event.raw_text.lower() for w in keywords):
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info("📩 Ретрансляція успішна")
        except Exception as e:
            logger.error(f"Forward error: {e}")

@client.on(events.NewMessage(incoming=True))
async def admin_panel(event):
    """Адмін-панель у приватних повідомленнях бота"""
    if not event.is_private or event.sender_id not in ADMIN_IDS: return
    
    cmd = event.raw_text.lower().strip()
    if cmd == '/clear':
        db_sync('targets.json', [])
        await event.respond("🧹 **Карту очищено!**")
    elif cmd == '/info':
        t = db_sync('targets.json')
        a = db_sync('alerts.json')
        active = [k for k, v in a.items() if v.get('active')]
        await event.respond(f"📊 **Міток на карті:** {len(t)}\n🚨 **Активні тривоги:** {', '.join(active) if active else 'Немає'}")

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def main_parser(event):
    """Крок 2: Аналіз тексту у вашому каналі (включаючи переслані повідомлення)"""
    # Важливо: беремо текст повідомлення або підпис до медіа
    raw_text = event.raw_text or event.message.message or ""
    if not raw_text or raw_text.startswith('/'): return
    
    logger.info(f"🔎 Аналіз: {raw_text[:50].replace(os.linesep, ' ')}...")
    text_lc = raw_text.lower()

    # 1. СТАТУСИ ТРИВОГ
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db_sync('alerts.json')
        updated = False
        for ua, en in DISTRICTS_MAP.items():
            if ua.lower() in text_lc:
                alerts[en] = {"active": "🔴" in raw_text or "тривога" in text_lc}
                updated = True
        if updated: db_sync('alerts.json', alerts)
        return

    # 2. ПОШУК ЦІЛЕЙ
    global_threat = get_threat_type(text_lc)
    new_targets = []
    
    # Обробляємо кожен рядок окремо (для списків БПЛА)
    for line in raw_text.split('\n'):
        clean_line = line.strip()
        if len(clean_line) < 4: continue
        
        # Видаляємо сміття та цифри перед пошуком населеного пункту
        place = re.sub(r'(\d+|🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|БПЛА|Ракета|КАБ|Шахед|Мопед|молнія|гербера|н\.п\.|біля|нп)', '', clean_line, flags=re.IGNORECASE).strip()
        place = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|напрямок)', place, flags=re.IGNORECASE)[0].strip()
        place = re.sub(r'^(біля|в|у|район|селище|село|місто|смт|області|районі)\s+', '', place, flags=re.IGNORECASE).strip()

        coords = await get_coords(place)
        
        # Спроба для Харкова, якщо OSM не спрацював
        if not coords and "харків" in clean_line.lower():
            coords = [49.9935, 36.2304, "Харків"]

        if coords:
            threat = get_threat_type(clean_line)
            if threat == "unknown": threat = global_threat
            
            new_targets.append({
                "id": f"m{event.id}_{uuid.uuid4().hex[:4]}",
                "type": threat,
                "lat": coords[0], "lng": coords[1],
                "label": f"{SYMBOLS.get(threat, '❓')} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
            })
            logger.info(f"✅ Знайдено ціль: {threat} -> {coords[2]}")

    if new_targets:
        targets = db_sync('targets.json')
        # Оновлюємо базу, видаляючи старі мітки цього ж повідомлення
        targets = [t for t in targets if not str(t.get('id', '')).startswith(f"m{event.id}")]
        targets.extend(new_targets)
        db_sync('targets.json', targets)

# --- ЗАПУСК ---
async def main():
    await client.start()
    logger.info("🚀 БОТ ЗАПУЩЕНИЙ І МОНІТОРИТЬ КАНАЛ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
