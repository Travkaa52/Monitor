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
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥Робота ППО", "drone": "🛵 БПЛА типу Шахед/Гербера", "missile": "🚀 Ракета",
    "kab": "☄️Загроза КАБ", "mrls": "🔥 Загроза РСЗВ", "recon": "🛸 БПЛА типу Розвідник",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо", "lancet": "🎯 БПЛА типу Ланцет"
}

# ================= ЛОГІКА ПАРСИНГУ =================

def clean_location_name(text):
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Шахед|Ракета|Зафіксовано|Попередньо|!|\.)', ' ', text, flags=re.IGNORECASE).strip()
    match = re.search(r'(?:курсом|на|в|через|бік|напрямок|біля|у бік)\s+([А-ЯІЇЄ][а-яіїє\']+)', clean, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name.endswith('у'): name = name[:-1] + 'а'
        elif name.endswith('єва'): name = name[:-3] + 'їв'
        return name
    words = clean.split()
    for word in words:
        if word and word[0].isupper() and len(word) > 3:
            return word.strip(' ,.-')
    return None

async def get_coords_online(place_name):
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

# ================= РОБОТА З БД ТА GIT =================

def db_sync(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if 'targets' in file else {}
            try:
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            except: return [] if 'targets' in file else {}
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            threading.Thread(target=commit_and_push, daemon=True).start()

def commit_and_push():
    try:
        if os.path.exists(".git/index.lock"): os.remove(".git/index.lock")
        subprocess.run(["git", "config", "user.name", "TacticalBot"], check=False)
        subprocess.run(["git", "config", "user.email", "bot@tactical.net"], check=False)
        subprocess.run(["git", "add", "targets.json", "types.json"], check=False)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update"], check=False)
        subprocess.run(["git", "push"], check=False)
    except: pass

# ================= АВТО-ОЧИЩЕННЯ =================

async def cleaner_task():
    """Фонове завдання для видалення старих цілей."""
    while True:
        await asyncio.sleep(60) # Перевірка щохвилини
        targets = db_sync('targets.json')
        now = datetime.now().isoformat()
        
        # Залишаємо тільки ті цілі, термін яких ще не минув
        active_targets = [t for t in targets if t.get('expire_at', '') > now]
        
        if len(active_targets) != len(targets):
            logger.info(f"🧹 Очищення: видалено {len(targets) - len(active_targets)} застарілих цілей")
            db_sync('targets.json', active_targets)

# ================= ОБРОБНИКИ ПОДІЙ =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    keywords = ["харків", "область", "чугуїв", "куп'янськ", "богодухів", "дергачі", "бпла", "балістика", "шахед", "каб на", "люботин", "вовчанськ"]
    if any(w in text_lc for w in keywords):
        await client.send_message(MY_CHANNEL, event.message)

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    raw_text = event.raw_text or ""
    if not raw_text or raw_text.startswith('/'): return

    location = clean_location_name(raw_text)
    if not location: return
    
    coords = await get_coords_online(location)
    if not coords and "харків" in location.lower():
        coords = [49.9935, 36.2304, "Харків"]

    if coords:
        types_db = db_sync('types.json')
        text_lc = raw_text.lower()
        threat = "unknown"
        for t_type, keys in types_db.items():
            if any(k in text_lc for k in keys):
                threat = t_type; break

        targets = db_sync('targets.json')
        targets = [t for t in targets if t['id'] != event.id]
        
        # Час життя цілі: 45 хвилин (можна змінити)
        expire_time = datetime.now() + timedelta(minutes=15)
        
        targets.append({
            "id": event.id, "type": threat, "lat": coords[0], "lng": coords[1],
            "label": f"{SYMBOLS.get(threat, '❓')} | {coords[2]}",
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": expire_time.isoformat()
        })
        db_sync('targets.json', targets)
        logger.info(f"✅ Додано: {coords[2]} ({threat}). Зникне о {expire_time.strftime('%H:%M')}")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 СИСТЕМА ПРАЦЮЄ ТА ОЧИЩУЄТЬСЯ")
    # Запускаємо очищувач як фонове завдання
    asyncio.create_task(cleaner_task())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

