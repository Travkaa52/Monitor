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

# --- НАСТРОЙКА ЛОГОВ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

# --- КОНФИГУРАЦИЯ ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

DISTRICTS_MAP = {
    "Богодухів": "Bohodukhivskyi",
    "Харків": "Kharkivskyi",
    "Чугуїв": "Chuhuivskyi",
    "Ізюм": "Iziumskyi",
    "Куп": "Kupianskyi",
    "Лозів": "Lozivskyi",
    "Красноград": "Krasnohradskyi"
}

SYMBOLS = {
    "air_defense": "🛡️ ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "artillery": "💥 Арта", "s300": "🚜 С-300",
    "molniya": "⚡ Молнія", "unknown": "❓ Невідомо"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# --- СИСТЕМНЫЕ ФУНКЦИИ ---

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            if 'targets' in file:
                now_iso = datetime.now().isoformat()
                data = [t for t in data if t.get('expire_at', now_iso) > now_iso]

            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            try:
                subprocess.run(["git", "config", "user.email", "bot@neptun.system"], check=False)
                subprocess.run(["git", "config", "user.name", "Neptun Bot"], check=False)
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", f"📡 Sync {file}"], check=False)
                subprocess.run(["git", "push"], check=False)
            except Exception as e:
                logger.error(f"Git Sync Error: {e}")

# --- ГЕО И ПАРСИНГ ---

def clean_location_name(text):
    """Максимальная очистка для OpenStreetMap"""
    # 1. Убираем спецсимволы и технические слова
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед|молнія|гербера|1|2|3|біля|в області|районі)', '', text, flags=re.IGNORECASE).strip()
    
    # 2. Отсекаем направление (все что после "на", "в бік" и т.д.)
    # Нам нужно только место, ГДЕ сейчас объект
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|напрямок)', clean, flags=re.IGNORECASE)
    candidate = parts[0].strip().replace('"', '').replace('«', '').replace('»', '').replace(':', '')
    
    # 3. Убираем слова-связки в начале
    candidate = re.sub(r'^(біля|в|у|район|селище|село|місто|смт)\s+', '', candidate, flags=re.IGNORECASE).strip()
    
    return candidate if len(candidate) > 2 else None

async def get_coords(place):
    """Автоматический поиск через OpenStreetMap без базы данных"""
    if not place: return None
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place}, Харківська область", # Уточняем область для точности
        "format": "json",
        "limit": 1,
        "countrycodes": "ua",
        "accept-language": "uk",
        # Ограничиваем поиск квадратом Харьковской области (viewbox)
        "viewbox": "34.5,50.5,38.5,48.5", 
        "bounded": 1 # Искать строго внутри этого квадрата
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Уникальный User-Agent важен, чтобы API не блокировало запросы
            headers = {"User-Agent": f"NeptunBot_OSM_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        display_name = data[0]["display_name"].split(',')[0]
                        return [float(data[0]["lat"]), float(data[0]["lon"]), display_name]
    except Exception as e:
        logger.error(f"OSM Search Error ({place}): {e}")
    return None

def get_threat_type(text_lc):
    mapping = {
        "drone": ["шахед", "мопед", "shahed", "гербера"],
        "missile": ["ракета", "крилата", "балістика"],
        "kab": ["каб", "авіабомб", "фаб"],
        "recon": ["розвідник", "розвідувальні", "развед", "supercam", "zala", "орлан"],
        "mrls": ["рсзо", "рсзв", "град", "ураган", "смерч"],
        "s300": ["с300", "с-300"],
        "artillery": ["арта", "артилерія", "вихід", "обстріл"],
        "aircraft": ["міг", "су-", "авіація", "борт"],
        "molniya": ["молния", "молнія"]
    }
    for t_type, keys in mapping.items():
        if any(k in text_lc for k in keys): return t_type
    return "unknown"

# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    relevant_words = ["харків", "область", "хнс", "чугуїв", "куп", "люботин", "богодухів", "дергачі", "вовчанськ"]
    if any(word in text_lc for word in relevant_words):
        try:
            await client.send_message(MY_CHANNEL, event.message)
        except: pass

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_handler(event):
    raw_text = event.raw_text
    text_lc = raw_text.lower()
    
    # 1. ТРЕВОГИ
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db('alerts.json')
        updated = False
        for ua_pattern, en_id in DISTRICTS_MAP.items():
            if ua_pattern.lower() in text_lc:
                alerts[en_id] = {"active": "🔴" in raw_text or "тривога" in text_lc}
                updated = True
        if updated:
            db('alerts.json', alerts)
            return

    # 2. ПОИСК ЦЕЛЕЙ ЧЕРЕЗ API
    lines = raw_text.split('\n')
    found_threat = get_threat_type(text_lc)
    targets_to_save = []
    
    for line in lines:
        if len(line.strip()) < 5: continue
        
        loc_name = clean_location_name(line)
        coords = await get_coords(loc_name)
        
        # Если API не нашло ничего специфичного, проверяем общее упоминание города
        if not coords and "харків" in line.lower():
            coords = [49.9935, 36.2304, "Харків"]

        if coords:
            targets_to_save.append({
                "id": f"{event.id}_{uuid.uuid4().hex[:4]}",
                "type": found_threat,
                "lat": coords[0],
                "lng": coords[1],
                "label": f"{SYMBOLS.get(found_threat, '❓')} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=40)).isoformat()
            })

    if targets_to_save:
        targets = db('targets.json')
        if not isinstance(targets, list): targets = []
        targets = [t for t in targets if not str(t.get('id', '')).startswith(str(event.id))]
        targets.extend(targets_to_save)
        db('targets.json', targets)
        logger.info(f"✅ OSM нашел и обновил {len(targets_to_save)} целей")

async def main():
    await client.start()
    logger.info("🚀 NEPTUN SYSTEM ONLINE (OSM AUTOPILOT)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
