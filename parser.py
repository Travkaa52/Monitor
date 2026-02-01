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

MY_CHANNEL = 'monitorkh1654' # Твій канал (куди ретранслюємо і де парсимо)
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov'] # Звідки беремо

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

DIRECTION_MAP = {
    "північ": 0, "північніше": 0, "пн": 0,
    "схід": 90, "сх": 90,
    "південь": 180, "пд": 180,
    "захід": 270, "зх": 270
}

pending_targets = {}
delete_queue = {}

# ================= ЛОГІКА РЕТРАНСЛЯЦІЇ =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    """Моніторить чужі канали та пересилає важливе у твій канал."""
    if not event.raw_text: return
    
    text_lc = event.raw_text.lower()
    # Розумний фільтр: тільки те, що стосується нашої області та загроз
    keywords = ["харків", "область", "чугуїв", "куп", "ізюм", "бпла", "каб", "ракета", "шахед"]
    
    if any(word in text_lc for word in keywords):
        try:
            # Пересилаємо повідомлення (можна через send_message або forward_messages)
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"📡 Ретрансляція з {event.chat.username if event.chat else 'джерела'}")
        except Exception as e:
            logger.error(f"Помилка ретрансляції: {e}")

# ================= ЛОГІКА ПАРСИНГУ =================

def parse_direction(text):
    text_lc = text.lower()
    for key, deg in DIRECTION_MAP.items():
        if key in text_lc: return deg
    return None

def clean_location_name(text):
    # Виправлено помилку в регулярці: Ракета замість Ратета
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Шахед|Ракета|Зафіксовано|Попередньо)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|у бік)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '')
    return name if len(name) > 2 else None

async def get_coords_online(place_name):
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": f"NeptunTactical_{uuid.uuid4().hex[:4]}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        res = data[0]
                        return [float(res["lat"]), float(res["lon"]), res["display_name"].split(',')[0]]
    except: pass
    return None

# ================= РОБОТА З БД ТА GIT =================

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Запускаємо пуш в окремому потоці, щоб не гальмувати бота
            threading.Thread(target=commit_and_push, daemon=True).start()

def commit_and_push():
    try:
        # Прибираємо блокування Git якщо воно є
        if os.path.exists(".git/index.lock"): os.remove(".git/index.lock")
        subprocess.run(["git", "add", "targets.json", "types.json"], check=False, capture_output=True)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update"], check=False, capture_output=True)
        subprocess.run(["git", "push"], check=False, capture_output=True)
    except: pass

# ================= ОБРОБКА ВЛАСНОГО КАНАЛУ =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    """Парсить повідомлення, які з'явилися у ВЛАСНОМУ каналі (від ретранслятора або вручну)."""
    raw_text = event.raw_text
    if not raw_text or raw_text.startswith('/'): return

    target_name = clean_location_name(raw_text)
    if not target_name: return
    
    found_point = await get_coords_online(target_name)
    if not found_point: return

    # Визначаємо тип
    types_db = db('types.json')
    text_lc = raw_text.lower()
    final_type = "unknown"
    
    if any(w in text_lc for w in ["робота ппо", "працює ппо"]): 
        final_type = "air_defense"
    else:
        for t_type, keywords in types_db.items():
            if any(word in text_lc for word in keywords):
                final_type = t_type
                break
    
    # Якщо тип невідомий — питаємо адміна
    if final_type == "unknown":
        pending_targets[event.id] = {"term": target_name.lower()}
        btns = [[Button.inline("🛵 Дрон", f"learn:drone:{event.id}"), Button.inline("🚀 Ракета", f"learn:missile:{event.id}")],
                [Button.inline("☄️ КАБ", f"learn:kab:{event.id}"), Button.inline("💥 ППО", f"learn:air_defense:{event.id}")]]
        for adm in ADMIN_IDS:
            try: await client.send_message(adm, f"❓ **Новий тип загрози!**\n`{raw_text}`", buttons=btns)
            except: pass

    new_target = {
        "id": event.id, "type": final_type, "count": 1,
        "status": "active", "reason": "", "lat": found_point[0], "lng": found_point[1],
        "direction": parse_direction(raw_text),
        "label": f"{SYMBOLS.get(final_type, '❓')} | {found_point[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
    }
    
    data = db('targets.json')
    data = [t for t in data if t['id'] != event.id]
    data.append(new_target)
    db('targets.json', data)
    logger.info(f"✅ Ціль додана на мапу: {found_point[2]}")

# ================= CALLBACKS ТА ЗАПУСК =================
# (Callbacks залишаються такими ж, як у твоєму коді)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 ТАКТИЧНИЙ БОТ ЗАПУЩЕНИЙ")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
