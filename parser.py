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

CITY_FALLBACK = {
    "Харків": [49.9935, 36.2304],
    "Чугуїв": [49.8356, 36.6863],
    "Богодухів": [50.1653, 35.5235],
    "Дергачі": [50.1136, 36.1205],
    "Люботин": [49.9486, 35.9281],
    "Куп'янськ": [49.7075, 37.6158]
}

THREAT_TYPES = {
    "ballistics": {"keywords": ["баліст", "іскандер", "кинджал", "кн-23"], "icon": "img/ballistic.png", "label": "Балістика", "ttl": 15},
    "cruise_missile": {"keywords": ["крилата ракета", "калібр", "х-101", "х-555"], "icon": "img/cruise.png", "label": "Крилата ракета", "ttl": 20},
    "missile": {"keywords": ["ракета", "пуск", "х-59", "х-31"], "icon": "img/missile.png", "label": "Ракета", "ttl": 15},
    "kab": {"keywords": ["каб", "авіабомб", "керована"], "icon": "img/kab.png", "label": "КАБ", "ttl": 25},
    "shahed": {"keywords": ["шахед", "шахєд", "герань", "мопед"], "icon": "img/drone.png", "label": "Шахед", "ttl": 45},
    "gerbera": {"keywords": ["gerbera", "гербера"], "icon": "img/drone.png", "label": "Гербера", "ttl": 40},
    "molniya": {"keywords": ["молнія", "молния"], "icon": "img/molniya.png", "label": "Молнія", "ttl": 30},
    "lancet": {"keywords": ["ланцет"], "icon": "img/lancet.png", "label": "Ланцет", "ttl": 25},
    "recon": {"keywords": ["розвід", "орлан", "зала", "суперкам"], "icon": "img/recon.png", "label": "Розвідник", "ttl": 30},
    "aviation": {"keywords": ["авіац", "міг-31", "ту-95", "су-34", "су-35"], "icon": "img/aircraft.png", "label": "Авіація", "ttl": 30},
    "mrls": {"keywords": ["рсзв", "град", "ураган", "смерч"], "icon": "img/mrls.png", "label": "РСЗВ", "ttl": 15},
    "air_defense": {"keywords": ["ппо", "працює", "вибух"], "icon": "img/images.png", "label": "ППО", "ttl": 10},
    "unknown": {"keywords": [], "icon": "img/unknown.png", "label": "Невідомо", "ttl": 20}
}

SOURCE_ZONES = {
    "КРИМ": {"keywords": ["крим", "криму", "джанкой"], "coords": [45.1, 34.1]},
    "МОРЕ": {"keywords": ["моря", "морі", "акваторії"], "coords": [44.5, 33.0]},
    "БЄЛГОРОД": {"keywords": ["бєлгород", "белгород", "бнр"], "coords": [50.6, 36.6]},
    "КУРСЬК": {"keywords": ["курськ", "курск"], "coords": [51.7, 36.2]},
    "ЛУГАНСЬК": {"keywords": ["луганськ", "луганск"], "coords": [48.5, 39.3]},
    "ДОНЕЦЬК": {"keywords": ["донецьк", "донецк"], "coords": [48.0, 37.8]}
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= ДОПОМІЖНІ ФУНКЦІЇ =================

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return []
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return []
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            threading.Thread(target=commit_and_push, daemon=True).start()

def commit_and_push():
    try:
        if os.path.exists(".git/index.lock"): os.remove(".git/index.lock")
        subprocess.run(["git", "add", "targets.json"], check=False, capture_output=True)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update"], check=False, capture_output=True)
        subprocess.run(["git", "push"], check=False, capture_output=True)
    except: pass

def clean_location_name(text):
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Шахед|Ракета|Зафіксовано|Попередньо|!|\.)', ' ', text, flags=re.IGNORECASE).strip()
    match = re.search(r'(?:курсом|на|в|через|бік|напрямок|біля|у бік|район)\s+([А-ЯІЇЄ][а-яіїє\']+)', clean, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name.endswith('у'): name = name[:-1] + 'а'
        elif name.endswith('єва'): name = name[:-3] + 'їв'
        return name
    return None

async def get_coords_online(place_name):
    if place_name in CITY_FALLBACK:
        return [CITY_FALLBACK[place_name][0], CITY_FALLBACK[place_name][1], place_name]
    
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": f"TacticalMonitor_{uuid.uuid4().hex[:6]}"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params={"q": query, "format": "json", "limit": 1}, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        res = data[0]
                        return [float(res["lat"]), float(res["lon"]), res["display_name"].split(',')[0]]
    except: pass
    return None

# ================= ОБРОБНИКИ =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    global REPLY_MAP
    if not IS_PARSING_ENABLED or not event.raw_text: return
    
    raw_text = event.raw_text
    text_lc = raw_text.lower()
    msg_id = event.id
    reply_to = event.reply_to_msg_id

    # 1. Очищення при відбої
    if any(k in text_lc for k in ["відбій", "чисто", "відміна"]):
        db_sync('targets.json', [])
        REPLY_MAP.clear()
        logger.info("🧹 Карта очищена")
        return

    # 2. Логіка Reply та пошук цілі
    targets = db_sync('targets.json')
    target_id = None
    is_update = False

    if reply_to in REPLY_MAP:
        target_id = REPLY_MAP[reply_to]
        is_update = True

    # 3. Визначення типу та локації
    loc_name = clean_location_name(raw_text)
    coords = await get_coords_online(loc_name) if loc_name else None
    
    # 4. Джерело (Зони)
    source_zone = next((z for z, i in SOURCE_ZONES.items() if any(k in text_lc for k in i["keywords"])), None)
    if source_zone and not coords:
        coords = [SOURCE_ZONES[source_zone]["coords"][0], SOURCE_ZONES[source_zone]["coords"][1], source_zone]

    if is_update:
        # ОНОВЛЕННЯ ІСНУЮЧОЇ ЦІЛІ
        for t in targets:
            if t['id'] == target_id:
                if coords:
                    t['lat'], t['lng'] = coords[0], coords[1]
                    t['label'] = f"{t['label'].split('|')[0]} | {coords[2]}"
                t['time'] = datetime.now().strftime("%H:%M")
                
                # Якщо об'єкт зник
                if any(k in text_lc for k in ["зник", "не фіксується", "мінус"]):
                    t['expire_at'] = (datetime.now() + timedelta(minutes=5)).isoformat()
                break
    elif coords:
        # СТВОРЕННЯ НОВОЇ ЦІЛІ
        target_id = str(uuid.uuid4())[:8]
        threat_id = "unknown"
        for tid, info in THREAT_TYPES.items():
            if any(k in text_lc for k in info["keywords"]):
                threat_id = tid
                break
        
        new_target = {
            "id": target_id,
            "type": threat_id,
            "lat": coords[0],
            "lng": coords[1],
            "label": f"{THREAT_TYPES[threat_id]['label']} | {coords[2]}",
            "icon": THREAT_TYPES[threat_id]["icon"],
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": (datetime.now() + timedelta(minutes=THREAT_TYPES[threat_id]['ttl'])).isoformat()
        }
        targets.append(new_target)

    # Збереження
    if target_id:
        REPLY_MAP[msg_id] = target_id
        db_sync('targets.json', targets)
        logger.info(f"✅ {'Оновлено' if is_update else 'Додано'} ціль {target_id}")

# ================= СИСТЕМНІ ТАСКИ =================

@client.on(events.NewMessage(chats=ADMIN_IDS, pattern='/admin'))
async def admin_panel(event):
    buttons = [
        [Button.inline(f"{'🔴 STOP' if IS_PARSING_ENABLED else '🟢 START'} PARSING", b"toggle")],
        [Button.inline("❌ CLEAR ALL", b"clear")]
    ]
    await event.respond("🛡 **ADMIN PANEL**", buttons=buttons)

@client.on(events.CallbackQuery())
async def callback_handler(event):
    global IS_PARSING_ENABLED
    if event.data == b"toggle":
        IS_PARSING_ENABLED = not IS_PARSING_ENABLED
        await event.edit(f"Parsing: {'🟢 ON' if IS_PARSING_ENABLED else '🔴 OFF'}")
    elif event.data == b"clear":
        db_sync('targets.json', [])
        await event.answer("Targets cleared!")

async def cleaner_task():
    while True:
        await asyncio.sleep(60)
        targets = db_sync('targets.json')
        now = datetime.now().isoformat()
        active = [t for t in targets if t.get('expire_at', '') > now]
        if len(active) != len(targets):
            db_sync('targets.json', active)
            logger.info("🧹 Прибрано старі об'єкти")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    asyncio.create_task(cleaner_task())
    logger.info("🚀 Парсер запущено")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
