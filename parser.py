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

if not SESSION_STRING:
    raise RuntimeError("SESSION_STRING is empty")

MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

ADMIN_IDS = [5423792783] 

DISTRICTS_MAP = {
    "Богодухів": "Bohodukhivskyi", "Харків": "Kharkivskyi",
    "Чугуїв": "Chuhuivskyi", "Ізюм": "Iziumskyi",
    "Куп": "Kupianskyi", "Лозів": "Lozivskyi", "Красноград": "Krasnohradskyi"
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
            if not os.path.exists(file):
                return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return [] if 'targets' in file else {}
        else:
            if 'targets' in file:
                now = datetime.now()
                data = [
                    t for t in data
                    if datetime.fromisoformat(t.get('expire_at', now.isoformat())) > now
                ]

            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            try:
                subprocess.run(["git", "config", "user.email", "bot@neptun.system"], check=False)
                subprocess.run(["git", "config", "user.name", "Neptun Bot"], check=False)
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", f"📡 Update: {datetime.now().strftime('%H:%M:%S')}"], check=False)
                subprocess.run(["git", "push"], check=False)
            except Exception as e:
                logger.error(f"Git Sync Error: {e}")

# --- ГЕО-ПОИСК (OSM) ---

def clean_location_name(text):
    clean = re.sub(
        r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед|молнія|гербера)',
        '',
        text,
        flags=re.IGNORECASE
    ).strip()

    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|напрямок)', clean, flags=re.IGNORECASE)
    candidate = parts[0].strip().replace('"', '').replace('«', '').replace('»', '').replace(':', '')

    candidate = re.sub(
        r'^(біля|в|у|район|селище|село|місто|смт|області|районі)\s+',
        '',
        candidate,
        flags=re.IGNORECASE
    ).strip()

    return candidate if len(candidate) > 2 else None

async def get_coords(place):
    if not place:
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place}, Харківська область",
        "format": "json",
        "limit": 1,
        "countrycodes": "ua",
        "accept-language": "uk",
        "viewbox": "34.5,50.5,38.5,48.5",
        "bounded": 1
    }

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": f"NeptunBot_{uuid.uuid4().hex[:4]}"}
            async with session.get(url, params=params, headers=headers) as resp:
                data = await resp.json()
                if data:
                    return [
                        float(data[0]["lat"]),
                        float(data[0]["lon"]),
                        data[0]["display_name"].split(',')[0]
                    ]
    except Exception:
        pass

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

# --- ОБРАБОТЧИКИ ---

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    if not event.raw_text:
        return

    text_lc = event.raw_text.lower()
    keywords = [
        "харків", "область", "чугуїв", "куп'янськ", "богодухів",
        "дергачі", "бпла", "балістика", "є загроза для",
        "купянск", "шахед", "развед.бпла", "каб на",
        "швидкісна на", "активність тактичної авіації",
        "люботин", "вовчанськ"
    ]

    if any(word in text_lc for word in keywords):
        try:
            if event.message:
                await client.send_message(MY_CHANNEL, event.message)
            logger.info("📩 Ретрансляция выполнена")
        except Exception as e:
            logger.error(f"Retranslate error: {e}")

@client.on(events.NewMessage(incoming=True))
async def admin_private_handler(event):
    if not event.is_private or event.sender_id not in ADMIN_IDS:
        return

    text_lc = (event.raw_text or "").lower()

    if text_lc == '/clear':
        db('targets.json', [])
        await event.respond("🧹 **Карта очищена.** Все метки удалены.")
        logger.info(f"🚫 Админ {event.sender_id} очистил карту")

    elif text_lc == '/info':
        targets = db('targets.json') or []
        alerts = db('alerts.json') or {}

        active_districts = [
            k for k, v in alerts.items()
            if isinstance(v, dict) and v.get('active')
        ]

        msg = (
            f"📊 **Статус системы:**\n"
            f"📍 Меток на карте: `{len(targets)}`\n"
            f"🚨 Тревога в: `{', '.join(active_districts) if active_districts else 'Нет активных'}`
        )

        await event.respond(msg)

@client.on(events.NewMessage(chats=MY_CHANNEL, incoming=True))
async def parser_handler(event):
    raw_text = event.raw_text or ""
    if not raw_text or raw_text.startswith('/'):
        return

    text_lc = raw_text.lower()
    logger.info(f"🔎 Анализ поста: {raw_text[:30]}...")

    # 1. СТАТУСЫ ТРЕВОГ
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db('alerts.json') or {}
        updated = False

        for ua_pattern, en_id in DISTRICTS_MAP.items():
            if ua_pattern.lower() in text_lc:
                alerts[en_id] = {
                    "active": ("🔴" in raw_text or "тривога" in text_lc)
                }
                updated = True

        if updated:
            db('alerts.json', alerts)
            return

    # 2. ПОИСК ЦЕЛЕЙ
    lines = raw_text.split('\n')
    targets_to_save = []

    for line in lines:
        if len(line.strip()) < 5:
            continue

        found_threat = get_threat_type(line.lower())
        loc_name = clean_location_name(line)
        coords = await get_coords(loc_name)

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
                "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
            })

    if targets_to_save:
        targets = db('targets.json') or []
        targets = [
            t for t in targets
            if not str(t.get('id', '')).startswith(str(event.id))
        ]
        targets.extend(targets_to_save)
        db('targets.json', targets)
        logger.info("📍 Метки обновлены из канала")

# --- ЗАПУСК ---

async def main():
    await client.start()
    logger.info("🚀 БОТ ЗАПУЩЕН")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
