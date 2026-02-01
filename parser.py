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

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

# ================= КОНФІГУРАЦІЯ =================
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

# ================= СИСТЕМНІ ФУНКЦІЇ =================

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            # Видалення застарілих цілей перед записом (якщо це targets.json)
            if 'targets' in file:
                now = datetime.now().isoformat()
                data = [t for t in data if t.get('expire_at', now) > now]

            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            try:
                # Автоматичне налаштування Git Identity, щоб не було помилок commit
                subprocess.run(["git", "config", "user.email", "bot@neptun.system"], check=False)
                subprocess.run(["git", "config", "user.name", "Neptun Bot"], check=False)
                
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", f"📡 Sync {file}"], check=False)
                subprocess.run(["git", "push"], check=False)
            except Exception as e:
                logger.error(f"Git Error: {e}")

# ================= ГЕО ТА ПАРСИНГ =================

def clean_location_name(text):
    """Очищення тексту для пошуку координат"""
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед|розвідувальні|молнія|гербера|1|2|3|біля|в області)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|біля|район)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '').replace(':', '')
    return name if len(name) > 2 else None

async def get_coords(place):
    if not place: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область, Україна", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"NeptunMap/1.2"}) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
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
        if any(k in text_lc for k in keys):
            return t_type
    return "unknown"

# ================= ОБРОБНИКИ =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    is_kharkiv = any(word in text_lc for word in ["харків", "область", "хнс", "чугуїв", "куп", "люботин", "богодухів", "дергачі", "вовчанськ"])
    if is_kharkiv:
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info("♻️ Ретрансляція повідомлення")
        except: pass

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_handler(event):
    raw_text = event.raw_text
    text_lc = raw_text.lower()
    
    # 1. ОБРОБКА ТРИВОГ
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db('alerts.json')
        updated = False
        for ua_pattern, en_id in DISTRICTS_MAP.items():
            if ua_pattern.lower() in text_lc:
                is_active = "🔴" in raw_text or "тривога" in text_lc
                alerts[en_id] = {"active": is_active}
                updated = True
        if updated:
            db('alerts.json', alerts)
            return

    # 2. ОБРОБКА МІТОК
    lines = raw_text.split('\n')
    found_threat = get_threat_type(text_lc)
    targets_to_save = []
    
    for line in lines:
        if len(line.strip()) < 5: continue
        
        loc_name = clean_location_name(line)
        coords = await get_coords(loc_name)
        
        if not coords and "харків" in line.lower():
            coords = [49.9935, 36.2304, "Харків"]

        if coords:
            new_target = {
                "id": f"{event.id}_{uuid.uuid4().hex[:4]}",
                "type": found_threat,
                "lat": coords[0],
                "lng": coords[1],
                "label": f"{SYMBOLS.get(found_threat, '❓')} | {coords[2]}",
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": (datetime.now() + timedelta(minutes=40)).isoformat()
            }
            targets_to_save.append(new_target)

    if targets_to_save:
        targets = db('targets.json')
        if not isinstance(targets, list): targets = []
        
        # Видаляємо старі записи з цим ID повідомлення, щоб уникнути дублів при редагуванні
        targets = [t for t in targets if not str(t.get('id', '')).startswith(str(event.id))]
        targets.extend(targets_to_save)
        
        # Зберігаємо актуальні цілі
        db('targets.json', targets)
        logger.info(f"✅ Карту оновлено: {len(targets_to_save)} цілей")

async def main():
    await client.start()
    logger.info("✅ NEPTUN SYSTEM ONLINE")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
