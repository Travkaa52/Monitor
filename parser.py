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
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# --- НАЛАШТУВАННЯ ЛОГІВ ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s: %(message)s')
logger = logging.getLogger("NEPTUN_CORE")

# --- КОНФІГУРАЦІЯ ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

MY_CHANNEL = 'monitorkh1654'
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def clean_location_name(text):
    """Витягує назву міста, виправляючи відмінки та прибираючи сміття."""
    # Прибираємо спецсимволи та системні слова
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Шахед|Ракета|Зафіксовано|Попередньо|!|\.)', ' ', text, flags=re.IGNORECASE).strip()
    
    # Пріоритет: шукаємо місто після прийменників (на Лозову, в бік Чугуєва)
    match = re.search(r'(?:курсом|на|в|через|бік|напрямок|поблизу|біля|у бік)\s+([А-ЯІЇЄ][а-яіїє\']+)', clean, flags=re.IGNORECASE)
    
    if match:
        name = match.group(1).strip()
        # Виправлення закінчень для Nominatim (Лозову -> Лозова, Кутузівку -> Кутузівка)
        if name.endswith('у'): name = name[:-1] + 'а'
        elif name.endswith('і'): name = name[:-1] + 'а'
        return name

    # Якщо прийменників немає, шукаємо будь-яке слово з великої літери (крім першого)
    words = clean.split()
    for word in words[1:]:
        if word and word[0].isupper() and len(word) > 3:
            return word.strip(' ,.-')
    
    # Резерв: якщо в тексті просто назва міста
    if words and words[0][0].isupper() and len(words[0]) > 3:
        return words[0].strip(' ,.-')
        
    return None

async def get_coords_online(place_name):
    """Отримує координати через OpenStreetMap API."""
    if not place_name: return None
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": f"TacticalBot_{uuid.uuid4().hex[:6]}"}
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params={"q": query, "format": "json", "limit": 1}, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except Exception as e:
        logger.error(f"Помилка карти: {e}")
    return None

def db_sync(file, data=None):
    """Синхронізація JSON файлів та Git."""
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            threading.Thread(target=git_push, daemon=True).start()

def git_push():
    """Безпечне оновлення репозиторію."""
    try:
        if os.path.exists(".git/index.lock"): os.remove(".git/index.lock")
        subprocess.run(["git", "add", "targets.json", "types.json"], check=False, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"📡 Upd {datetime.now().strftime('%H:%M')}"], check=False, capture_output=True)
        subprocess.run(["git", "push"], check=False, capture_output=True)
    except: pass

# --- ОБРОБНИКИ ПОДІЙ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    """Пересилає важливе у твій канал."""
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    keywords = ["харків", "область", "чугуїв", "куп", "ізюм", "бпла", "каб", "ракета", "шахед"]
    
    if any(word in text_lc for word in keywords):
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"📡 Ретрансляція: {event.id}")
        except: pass

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def main_parser(event):
    """Аналізує повідомлення у твоєму каналі та додає на мапу."""
    raw_text = event.raw_text or event.message.message or ""
    if not raw_text or raw_text.startswith('/'): return
    
    logger.info(f"🔎 Аналіз: {raw_text[:40]}...")
    
    # Витягуємо назву локації
    location = clean_location_name(raw_text)
    if not location:
        logger.warning("📍 Локацію не розпізнано.")
        return

    # Шукаємо координати
    coords = await get_coords_online(location)
    if not coords:
        # Резервна перевірка для Харкова
        if "харків" in location.lower():
            coords = [49.9935, 36.2304, "Харків"]
        else:
            logger.error(f"❌ Місто [{location}] не знайдено на карті.")
            return

    # Визначаємо тип загрози
    types_db = db_sync('types.json')
    final_type = "unknown"
    text_lc = raw_text.lower()

    if any(w in text_lc for w in ["ппо", "працює"]): 
        final_type = "air_defense"
    else:
        for t_type, keys in types_db.items():
            if any(k in text_lc for k in keys):
                final_type = t_type
                break

    # Оновлюємо базу цілей
    targets = db_sync('targets.json')
    targets = [t for t in targets if t['id'] != event.id] # уникаємо дублів
    
    targets.append({
        "id": event.id,
        "type": final_type,
        "lat": coords[0], "lng": coords[1],
        "label": f"{SYMBOLS.get(final_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
    })
    
    db_sync('targets.json', targets)
    logger.info(f"✅ УСПІХ: {final_type} -> {coords[2]}")

# --- ЗАПУСК ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 СИСТЕМА ПРАЦЮЄ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
    
