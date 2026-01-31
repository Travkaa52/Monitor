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
# ВАЖНО: Используем SESSION_STRING вашего аккаунта. 
# Аккаунт должен быть админом в MY_CHANNEL и подписан на SOURCE_CHANNELS
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor_ukraine', 'povitryany_trivogi'] # Список каналов-источников

# Слова, при которых сообщение БУДЕТ переслано
FILTER_WORDS = ["харків", "область", "чугуїв", "куп", "вовчанськ", "дергачі", "люботин"]

# Инициализируем клиента ОДИН раз
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

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
                subprocess.run(["git", "commit", "-m", "📡 Tactical Sync", "--no-verify"], check=False)
                subprocess.run(["git", "push"], check=False)
            except: pass

def clean_location_name(text):
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз)', clean, flags=re.IGNORECASE)
    name = parts[0].strip()
    loc_only = re.sub(r'(бпла|ракета|каб|шахед|мопед|авіація|ппо)', '', name, flags=re.IGNORECASE).strip()
    return loc_only if len(loc_only) > 2 else None

async def get_coords(place):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область", "format": "json", "limit": 1}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers={"User-Agent":"Neptun"}) as resp:
            data = await resp.json()
            return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]] if data else None

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================

# 1. РЕТРАНСЛЯТОР: Из чужих каналов в твой
@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def forwarder(event):
    text = event.raw_text.lower()
    if any(word in text for word in FILTER_WORDS):
        # Отправляем копию сообщения в твой канал
        await client.send_message(MY_CHANNEL, event.message)
        logger.info(f"♻️ Сообщение переслано из {event.chat.username}")

# 2. ПАРСЕР: Читает твой канал (куда попали пересланные сообщения) и обновляет карту
@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser(event):
    raw_text = event.raw_text
    loc_name = clean_location_name(raw_text)
    if not loc_name: return

    coords = await get_coords(loc_name)
    if not coords: return

    # Типизация (используем твой types.json)
    types_db = db('types.json')
    text_lc = raw_text.lower()
    found_type = "unknown"
    for t_type, keywords in types_db.items():
        if any(word in text_lc for word in keywords):
            found_type = t_type; break

    new_target = {
        "id": event.id, "type": found_type, "count": 1, "status": "active",
        "lat": coords[0], "lng": coords[1], "direction": None,
        "label": f"{SYMBOLS.get(found_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
    }

    targets = db('targets.json')
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    db('targets.json', targets)
    logger.info(f"📍 Карта обновлена: {coords[2]}")

# ================= ЗАПУСК =================

async def main():
    # Мы НЕ используем BOT_TOKEN, так как StringSession (аккаунт) умеет всё
    await client.start() 
    print("✅ СИСТЕМА ЗАПУЩЕНА")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
