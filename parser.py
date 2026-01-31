import asyncio
import json
import os
import re
import threading
import logging
import subprocess
import aiohttp
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_SYSTEM")

# ================= КОНФИГУРАЦИЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

# Каналы
MY_CHANNEL = 'monitorkh1654' # Твой канал
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'radar_kharkov'] # Откуда берем инфо

# Ключевые слова для ретранслятора (чтобы не спамить лишним)
FILTER_WORDS = ["харків", "область", "чугуїв", "куп'янськ", "вовчанськ", "дергачі", "люботин"]

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# Символы для карты
SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

# ================= ЛОГИКА РЕТРАНСЛЯТОРА =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def forwarder_handler(event):
    """Слушает чужие каналы и пересылает важное в твой канал"""
    text = event.raw_text.lower()
    
    # Проверяем, касается ли новость твоего региона
    if any(word in text for word in FILTER_WORDS):
        try:
            # Пересылаем сообщение в твой канал (от имени юзера)
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"♻️ Переслано из {event.chat.username}")
        except Exception as e:
            logger.error(f"Ошибка ретрансляции: {e}")

# ================= ЛОГИКА ПАРСЕРА =================

def parse_direction(text):
    direction_map = {
        "північ": 0, "північніше": 0, "пн": 0, "схід": 90, "сх": 90,
        "південь": 180, "пд": 180, "захід": 270, "зх": 270
    }
    text_lc = text.lower()
    for key, deg in direction_map.items():
        if key in text_lc: return deg
    return None

def clean_location_name(text):
    # Очистка для геокодирования
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз)', clean, flags=re.IGNORECASE)
    name = parts[0].strip()
    # Убираем типы угроз только для поиска координат
    loc_only = re.sub(r'(бпла|ракета|каб|шахед|мопед|авіація|ппо)', '', name, flags=re.IGNORECASE).strip()
    return loc_only if len(loc_only) > 2 else None

async def get_coords(place):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"Neptun"}) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: return None

# ================= ОБРАБОТКА ТВОЕГО КАНАЛА =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def handle_my_channel(event):
    """Парсит сообщения, которые попали в твой канал (ручные или пересланные)"""
    raw_text = event.raw_text
    loc_name = clean_location_name(raw_text)
    if not loc_name: return

    coords = await get_coords(loc_name)
    if not coords: return

    # Типизация
    types_db = db('types.json')
    text_lc = raw_text.lower()
    found_type = "unknown"
    for t_type, keywords in types_db.items():
        if any(word in text_lc for word in keywords):
            found_type = t_type; break

    new_target = {
        "id": event.id, "type": found_type, "count": 1,
        "status": "active", "lat": coords[0], "lng": coords[1],
        "direction": parse_direction(raw_text),
        "label": f"{SYMBOLS.get(found_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
    }

    # Обновляем БД
    targets = db('targets.json')
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    db('targets.json', targets)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def db(file, data=None):
    with db_lock:
        if data is None:
            if not os.path.exists(file): return [] if file == 'targets.json' else {}
            with open(file, 'r', encoding='utf-8') as f: return json.load(f)
        else:
            with open(file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", "📡 Auto Update", "--no-verify"], check=False)
                subprocess.run(["git", "push"], check=False)
            except: pass

async def main():
    # Запуск бота и клиента одновременно
    await client.start(bot_token=BOT_TOKEN)
    logger.info("📡 Система Neptun запущена: Ретранслятор + Парсер активны.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

