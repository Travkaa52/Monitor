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
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s: %(message)s')
logger = logging.getLogger("NEPTUN_TACTICAL_PRO")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

# Словник символів та профілів загрози
THREAT_MAP = {
    "шахед": {"sym": "🛵", "type": "drone", "ttl": 45},
    "гербера": {"sym": "🛵", "type": "drone", "ttl": 40},
    "молнія": {"sym": "⚡", "type": "drone", "ttl": 30},
    "ланцет": {"sym": "🎯", "type": "drone", "ttl": 20},
    "ракета": {"sym": "🚀", "type": "missile", "ttl": 15},
    "балістика": {"sym": "☄️", "type": "ballistics", "ttl": 10},
    "каб": {"sym": "☄️", "type": "kab", "ttl": 25},
    "крилата": {"sym": "🚀", "type": "missile", "ttl": 20},
    "невідомо": {"sym": "❓", "type": "unknown", "ttl": 30}
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= ЯДРО ПАРСИНГУ (ADVANCED) =================

def extract_count(text):
    """Визначає кількість об'єктів у тексті."""
    if re.search(r'(декілька|група|зграя)', text, re.I): return "група"
    match = re.search(r'(\d+)\s*(бпла|шах|ракет)', text, re.I)
    return int(match.group(1)) if match else 1

def clean_location_name(text):
    """Покращений парсер локацій для складних повідомлень."""
    # Видаляємо шумові фрази та рекламу
    text = re.sub(r'(підписуйтесь|посилання|канал|інфо|моніторинг|⚠️|🚨)', '', text, flags=re.I)
    
    # Шукаємо локації через роздільники та прийменники
    # Наприклад: "Кочеток/Чугуїв" або "Богодухів та найближчі н.п."
    locations = []
    
    # Шаблон для пошуку назв міст з великої літери
    pattern = r'(?:на|в|через|бік|біля|курсом\s+на|рух\s+на)\s+([А-ЯІЇЄ][а-яіїє\']+)'
    matches = re.findall(pattern, text)
    
    if not matches:
        # Спроба знайти через слеш: Кочеток/Чугуїв
        slash_match = re.findall(r'([А-ЯІЇЄ][а-яіїє\']+)(?=/| та)', text)
        if slash_match: matches.extend(slash_match)

    for m in matches:
        m = m.strip()
        if len(m) > 3: locations.append(m)
        
    return list(set(locations))

async def get_coords_online(place_name):
    """Геокодування через Nominatim з обробкою помилок."""
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": f"TacticalMonitor_V6_{uuid.uuid4().hex[:6]}"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params={"q": query, "format": "json", "limit": 1}, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

# ================= ЛОГІКА БД ТА ПАМ'ЯТІ =================

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
            # Запуск Git синхронізації у фоні
            threading.Thread(target=commit_and_push, daemon=True).start()

def commit_and_push():
    try:
        subprocess.run(["git", "add", "targets.json"], check=False, capture_output=True)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Sync"], check=False, capture_output=True)
        subprocess.run(["git", "push"], check=False, capture_output=True)
    except: pass

# ================= ОБРОБНИК ПОДІЙ =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator(event):
    """Фільтрація та ретрансляція повідомлень з джерел."""
    if not event.raw_text: return
    text = event.raw_text.lower()
    # Ігноруємо відбої в ретрансляторі (обробляємо їх тільки в цілях)
    if "відбій" in text: return 
    
    triggers = ["харків", "область", "чугуїв", "бпла", "ракета", "каб", "шахед", "ланцет", "молнія"]
    if any(t in text for t in triggers):
        await client.send_message(MY_CHANNEL, event.message)

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    raw_text = event.raw_text or ""
    text_lc = raw_text.lower()
    
    # 1. Обробка термінальних станів (Відбій / Зник / Не відстежується)
    targets = db_sync('targets.json')
    if any(x in text_lc for x in ["відбій", "більше не відстежується", "зник", "чисто"]):
        logger.info("🛑 Сигнал завершення цілі / відбій")
        # Якщо відбій - чистимо все, якщо "не відстежується" - можна мітити статус
        if "відбій" in text_lc: targets = [] 
        else:
            for t in targets: t['status'] = 'finished'
        db_sync('targets.json', targets)
        return

    # 2. Визначення типу загрози та кількості
    threat_key = "невідомо"
    for k in THREAT_MAP.keys():
        if k in text_lc:
            threat_key = k
            break
            
    count = extract_count(text_lc)
    locations = clean_location_name(raw_text)
    
    if not locations:
        if "в області" in text_lc: # Зведений статус
            logger.info("ℹ️ Повідомлення про загальний статус в області")
            return
        return

    # 3. Створення / Оновлення цілей
    new_targets_count = 0
    for loc in locations:
        coords = await get_coords_online(loc)
        if not coords: continue
        
        # Перевіряємо, чи це оновлення існуючої цілі (продовження руху)
        is_update = False
        for t in targets:
            if t['label'] == loc and t['status'] == 'active':
                t['timestamp'] = int(datetime.now().timestamp())
                t['expire_at'] = (datetime.now() + timedelta(minutes=THREAT_MAP[threat_key]['ttl'])).isoformat()
                t['raw_text'] = raw_text
                is_update = True
                break
        
        if not is_update:
            target_id = str(uuid.uuid4())
            profile = THREAT_MAP[threat_key]
            
            new_obj = {
                "uuid": target_id,
                "msg_id": event.id,
                "type": profile['type'],
                "count": count,
                "lat": coords[0],
                "lng": coords[1],
                "label": loc,
                "direction": "на " + loc,
                "status": "active",
                "raw_text": raw_text,
                "timestamp": int(datetime.now().timestamp()),
                "expire_at": (datetime.now() + timedelta(minutes=profile['ttl'])).isoformat()
            }
            targets.append(new_obj)
            new_targets_count += 1

    if new_targets_count > 0 or is_update:
        db_sync('targets.json', targets)
        logger.info(f"✅ Оброблено: {threat_key} x{count}. Локацій: {len(locations)}")

# ================= АВТО-ОЧИЩЕННЯ =================

async def cleaner_task():
    while True:
        await asyncio.sleep(60)
        targets = db_sync('targets.json')
        now = datetime.now().isoformat()
        active = [t for t in targets if t.get('expire_at', '') > now and t.get('status') != 'finished']
        if len(active) != len(targets):
            db_sync('targets.json', active)
            logger.info(f"🧹 Очищено {len(targets) - len(active)} застарілих цілей")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("🚀 TACTICAL MONITOR CORE v6.0 READY")
    asyncio.create_task(cleaner_task())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
