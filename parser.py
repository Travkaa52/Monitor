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
    "air_defense": "💥Робота ППО", "drone": "🛵 БПЛА Шахед/Гербера", "missile": "🚀 Ракета",
    "kab": "☄️Загроза КАБ", "mrls": "🔥 Загроза РСЗВ", "recon": "🛸 БПЛА Розвідник",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо", "lancet": "🎯 БПЛА Ланцет",
    "molnia": "⚡ БПЛА Молнія"
}

# ================= ЛОГІКА ПАРСИНГУ (PRO-EXTENDED) =================

def clean_location_name(text):
    """
    Розширена версія: знаходить декілька локацій.
    Підтримує: 'на Прудянку', 'Слатине', 'Безруки', 'Кочеток/Чугуїв'
    """
    # 1. Попереднє очищення від сміття
    text = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|Зафіксовано|Попередньо|!|\.)', ' ', text, flags=re.IGNORECASE)
    
    # 2. Пошук локацій (Слова з великої літери після прийменників або роздільників)
    # Шукаємо: на X, в X, курсом на X, або X/Y
    pattern = r'(?:курсом|на|в|через|бік|біля|район)\s+([А-ЯІЇЄ][а-яіїє\']+)|([А-ЯІЇЄ][а-яіїє\']+)(?=/)'
    matches = re.findall(pattern, text)
    
    found = []
    for m in matches:
        # Регулярка повертає кортеж груп, беремо ту, що не пуста
        loc = m[0] if m[0] else m[1]
        if loc:
            # Нормалізація закінчень (мінімальна)
            if loc.endswith('у'): loc = loc[:-1] + 'а'
            elif loc.endswith('єва'): loc = loc[:-3] + 'їв'
            found.append(loc.strip())

    # 3. Якщо через регулярку нічого не знайшли, шукаємо просто слова з великої літери (fallback)
    if not found:
        words = text.split()
        for word in words:
            if word and word[0].isupper() and len(word) > 3:
                found.append(word.strip(' ,.-'))

    return list(set(found)) if found else None

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

# ================= РОБОТА З БД ТА GIT (ORIGINAL) =================

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
            # Виклик Git синхронізації
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

# ================= АВТО-ОЧИЩЕННЯ (ORIGINAL) =================

async def cleaner_task():
    while True:
        await asyncio.sleep(60)
        targets = db_sync('targets.json')
        now = datetime.now().isoformat()
        active_targets = [t for t in targets if t.get('expire_at', '') > now]
        if len(active_targets) != len(targets):
            db_sync('targets.json', active_targets)

# ================= ОБРОБНИКИ (ENHANCED) =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    keywords = ["харків", "область", "чугуїв", "бпла", "шахед", "каб на", "ракета", "молнія", "ланцет"]
    if any(w in text_lc for w in keywords):
        await client.send_message(MY_CHANNEL, event.message)

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    raw_text = event.raw_text or ""
    if not raw_text or raw_text.startswith('/'): return
    text_lc = raw_text.lower()

    # 1. Логіка завершення цілі / Відбій
    targets = db_sync('targets.json')
    if any(x in text_lc for x in ["відбій", "більше не відстежується", "зник", "чисто"]):
        if "відбій" in text_lc:
            db_sync('targets.json', [])
            logger.info("🛑 ВІДБІЙ: Очищено всі цілі")
        else:
            locs_to_remove = clean_location_name(raw_text)
            if locs_to_remove:
                targets = [t for t in targets if not any(l in t['label'] for l in locs_to_remove)]
                db_sync('targets.json', targets)
        return

    # 2. Парсинг локацій (може бути декілька)
    locations = clean_location_name(raw_text)
    if not locations: return

    # 3. Визначення типу загрози
    threat = "unknown"
    if "молнія" in text_lc: threat = "molnia"
    elif "ланцет" in text_lc: threat = "lancet"
    elif "шахед" in text_lc or "гербера" in text_lc: threat = "drone"
    elif "ракета" in text_lc: threat = "missile"
    elif "каб" in text_lc: threat = "kab"
    else:
        types_db = db_sync('types.json')
        for t_type, keys in types_db.items():
            if any(k in text_lc for k in keys):
                threat = t_type; break

    # 4. Кількість
    count = 1
    num_match = re.search(r'(\d+)\s*(?:бпла|шах|ракет)', text_lc)
    if num_match: count = int(num_match.group(1))
    elif "декілька" in text_lc or "група" in text_lc: count = "група"

    # 5. Цикл створення точок
    for loc in locations:
        coords = await get_coords_online(loc)
        if not coords and "харків" in loc.lower():
            coords = [49.9935, 36.2304, "Харків"]

        if coords:
            # Оновлення існуючої точки в цій локації, якщо вона вже є (щоб не плодити дублі)
            label = f"{SYMBOLS.get(threat, '❓')} | {coords[2]}"
            targets = [t for t in targets if t.get('label') != label]
            
            # Розрахунок часу життя
            ttl = 15
            if threat in ["drone", "molnia"]: ttl = 40
            if threat == "kab": ttl = 25

            expire_time = datetime.now() + timedelta(minutes=ttl)
            
            targets.append({
                "id": f"{event.id}_{uuid.uuid4().hex[:4]}",
                "type": threat,
                "lat": coords[0],
                "lng": coords[1],
                "label": label,
                "count": count,
                "time": datetime.now().strftime("%H:%M"),
                "expire_at": expire_time.isoformat()
            })
            logger.info(f"🎯 Ціль: {loc} ({threat})")

    db_sync('targets.json', targets)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 TACTICAL MONITOR СТАРТУВАВ")
    asyncio.create_task(cleaner_task())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
