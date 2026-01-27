import os
import re
import json
import asyncio
import logging
import subprocess
import aiohttp
import threading
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# ================= НАЛАШТУВАННЯ =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TACTICAL_PARSER")

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
CHANNEL_ID = 'monitorkh1654'
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

# ================= ДОПОМІЖНІ ФУНКЦІЇ =================

def git_sync():
    """Синхронізація з репозиторієм."""
    try:
        subprocess.run(["git", "config", "user.name", "TacticalBot"], check=True)
        subprocess.run(["git", "config", "user.email", "bot@tactical.internal"], check=True)
        subprocess.run(["git", "add", "targets.json", "types.json"], check=True)
        # [skip ci] запобігає повторному запуску GitHub Actions
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update [skip ci]"], check=False)
        subprocess.run(["git", "push"], check=True)
        logger.info("✅ Дані синхронізовано з GitHub")
    except Exception as e:
        logger.error(f"❌ Помилка Git: {e}")

def load_db(file):
    if not os.path.exists(file): return [] if file == 'targets.json' else {}
    with open(file, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except: return [] if file == 'targets.json' else {}

def save_db(file, data):
    with db_lock:
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        git_sync()

# ================= ЛОГІКА ОЧИЩЕННЯ (5 ХВИЛИН) =================

async def auto_cleanup_task():
    """Видаляє цілі, термін дії яких вичерпано."""
    while True:
        try:
            targets = load_db('targets.json')
            if targets:
                now = datetime.now()
                # Фільтруємо лише активні цілі, час expire_at яких ще не настав
                filtered = [t for t in targets if datetime.fromisoformat(t['expire_at']) > now]
                
                if len(filtered) != len(targets):
                    logger.info(f"🧹 Очистка: видалено {len(targets) - len(filtered)} об'єктів")
                    save_db('targets.json', filtered)
        except Exception as e:
            logger.error(f"Помилка в таску очищення: {e}")
        
        await asyncio.sleep(30) # Перевірка кожні 30 секунд

# ================= ПАРСИНГ ТА ГЕО =================

async def get_coords(city):
    url = f"https://nominatim.openstreetmap.org/search?q={city},Харківська область&format=json&limit=1"
    headers = {"User-Agent": "TacticalMonitor/1.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]['lat']), float(data[0]['lon']), data[0]['display_name'].split(',')[0]]
    except: return None
    return None

# ================= ОБРОБНИК ПОВІДОМЛЕНЬ =================

@client.on(events.NewMessage(chats=CHANNEL_ID))
async def channel_listener(event):
    text = event.raw_text.lower()
    
    # 1. Пошук міста
    city_match = re.search(r'(?:у|в|біля|через|на)\s+([а-яА-Яіїєґ]{3,})', text)
    if not city_match: return
    city_name = city_match.group(1)
    
    geo = await get_coords(city_name)
    if not geo: return

    # 2. Визначення типу
    final_type = "unknown"
    types_db = load_db('types.json')
    
    if any(x in text for x in ["ппо", "працює"]): final_type = "air_defense"
    else:
        for t_type, keywords in types_db.items():
            if any(k in text for k in keywords):
                final_type = t_type
                break

    # 3. Напрямок (курс)
    direction = None
    direction_map = {
        "пн": 0, "північ": 0, "пн-сх": 45, "сх": 90, "схід": 90,
        "пд-сх": 135, "пд": 180, "південь": 180, "пд-зх": 225,
        "зх": 270, "захід": 270, "пн-зх": 315
    }
    for k, v in direction_map.items():
        if k in text:
            direction = v; break

    # 4. Створення об'єкта (TTL 5 хвилин)
    now = datetime.now()
    new_target = {
        "id": event.id,
        "type": final_type,
        "lat": geo[0],
        "lng": geo[1],
        "direction": direction,
        "label": f"{SYMBOLS.get(final_type, '❓')} | {geo[2].upper()}",
        "time": now.strftime("%H:%M"),
        "expire_at": (now + timedelta(minutes=5)).isoformat() # ВИДАЛЕННЯ ЧЕРЕЗ 5 ХВ
    }

    # 5. Оновлення бази
    targets = load_db('targets.json')
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    save_db('targets.json', targets)
    
    logger.info(f"🎯 Нова ціль: {city_name} ({final_type})")

# ================= ЗАПУСК =================

async def main():
    logger.info("📡 Запуск тактичного парсера...")
    await client.start(bot_token=BOT_TOKEN)
    
    # Запуск фонового завдання очищення
    asyncio.create_task(auto_cleanup_task())
    
    logger.info("🚀 Бот активний. Очікування повідомлень...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
