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
git_lock = threading.Lock()

# --- СИСТЕМНІ ФУНКЦІЇ ---

def safe_git_push(file):
    """Виконує синхронізацію з Git в окремому потоці без блокування"""
    if git_lock.acquire(blocking=False):
        try:
            # Видаляємо index.lock якщо він залишився від попереднього збою
            lock_path = ".git/index.lock"
            if os.path.exists(lock_path):
                os.remove(lock_path)
            
            subprocess.run(["git", "add", file], check=False, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"📡 {file} update {datetime.now().strftime('%H:%M')}"], check=False, capture_output=True)
            subprocess.run(["git", "push"], check=False, capture_output=True)
        except Exception as e:
            logger.error(f"Git Sync Error: {e}")
        finally:
            git_lock.release()

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: 
                    content = json.load(f)
                    return content if isinstance(content, (list, dict)) else ([] if 'targets' in file else {})
            except: return [] if 'targets' in file else {}
        else:
            # Очищення старих міток (залишаємо ті, що в майбутньому)
            if 'targets' in file and isinstance(data, list):
                now = datetime.now()
                data = [t for t in data if datetime.fromisoformat(t.get('expire_at')) > (now - timedelta(seconds=30))]

            # Атомарний запис через тимчасовий файл
            try:
                temp_file = f"{file}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, file)
                logger.info(f"💾 {file} оновлено. Записів: {len(data) if isinstance(data, list) else 'dict'}")
                
                # Запуск Git в окремому потоці
                threading.Thread(target=safe_git_push, args=(file,), daemon=True).start()
            except Exception as e:
                logger.error(f"Save Error: {e}")

async def get_coords(place):
    if not place or len(place.strip()) < 3: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place}, Харківська область", "format": "json", "limit": 1,
        "countrycodes": "ua", "accept-language": "uk"
    }
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": f"NeptunBot_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                data = await resp.json()
                if data: return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

def get_threat_type(text):
    mapping = {
        "drone": ["шахед", "мопед", "shahed", "гербера"],
        "missile": ["ракета", "крилата", "балістика"],
        "kab": ["каб", "авіабомб", "фаб"],
        "recon": ["розвідник", "supercam", "zala", "орлан", "бпла"],
        "mrls": ["рсзо", "рсзв", "град"],
        "molniya": ["молния", "молнія"]
    }
    text_lc = text.lower()
    for t_type, keys in mapping.items():
        if any(k in text_lc for k in keys): return t_type
    return "unknown"

# --- ОБРОБНИКИ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    if not event.raw_text: return
    keywords = ["харків", "область", "чугуїв", "бпла", "шахед", "каб", "ракета"]
    if any(w in event.raw_text.lower() for w in keywords):
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info("📩 Ретрансляція успішна")
        except: pass

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def main_parser(event):
    raw_text = event.raw_text or event.message.message or ""
    if not raw_text or raw_text.startswith('/'): return
    
    logger.info(f"🔎 Аналіз: {raw_text[:50].replace(os.linesep, ' ')}...")
    text_lc = raw_text.lower()

    # 1. ТРИВОГИ
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
    targets = db_sync('targets.json')
    msg_id = f"m{event.id}"
    
    # Видаляємо старі мітки цього повідомлення
    targets = [t for t in targets if not str(t.get('id', '')).startswith(msg_id)]
    new_found = []
    
    for line in raw_text.split('\n'):
        if len(line.strip()) < 4: continue
        
        p = re.sub(r'(\d+|🚨|⚠️|Увага|БПЛА|Ракета|КАБ|Шахед|н\.п\.|біля|нп|—|-|:)', '', line, flags=re.IGNORECASE).strip()
        p = re.split(r'(на|в напрямку|через|бік|межах|в сторону)', p, flags=re.IGNORECASE)[0].strip()
        p = re.sub(r'^(в|у|селище|село|місто|смт)\s+', '', p, flags=re.IGNORECASE).strip()

        coords = await get_coords(p)
        if not coords and "харків" in line.lower(): coords = [49.9935, 36.2304, "Харків"]

        if coords:
            threat = get_threat_type(line)
            if threat == "unknown": threat = global_threat
            
            new_found.append({
                "id": f"{msg_id}_{uuid.uuid4().hex[:4]}",
                "type": threat,
                "lat": coords[0], "lng": coords[1],
                "label": f"{SYMBOLS.get(threat, '❓')} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
            })
            logger.info(f"✅ Знайдено: {threat} -> {coords[2]}")

    if new_found:
        targets.extend(new_found)
        db_sync('targets.json', targets)

@client.on(events.NewMessage(incoming=True))
async def admin_panel(event):
    if not event.is_private or event.sender_id not in ADMIN_IDS: return
    cmd = event.raw_text.lower().strip()
    if cmd == '/clear':
        db_sync('targets.json', [])
        await event.respond("🧹 Очищено")
    elif cmd == '/info':
        t = db_sync('targets.json')
        await event.respond(f"📍 Міток: {len(t)}")

# --- ЗАПУСК ---
async def main():
    await client.start()
    logger.info("🚀 СИСТЕМА ПРАЦЮЄ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
