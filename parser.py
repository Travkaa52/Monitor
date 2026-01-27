import os
import re
import json
import asyncio
import threading
import logging
import subprocess
import aiohttp
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]
CHANNEL_ID = 'monitorkh1654'

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

DIRECTION_MAP = {
    "північ": 0, "північніше": 0, "пн": 0,
    "північний схід": 45, "пн-сх": 45,
    "схід": 90, "східніше": 90, "сх": 90,
    "південний схід": 135, "пд-сх": 135,
    "південь": 180, "південніше": 180, "пд": 180,
    "південний захід": 225, "пд-зх": 225,
    "захід": 270, "західніше": 270, "зх": 270,
    "північний захід": 315, "пн-зх": 315
}

# ================= ЛОГІКА БД ТА ГІТ =================

def db(file, data=None):
    with db_lock:
        try:
            if data is None:
                if not os.path.exists(file): return []
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            else:
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                commit_and_push()
        except Exception as e:
            logger.error(f"БД error: {e}")
            return []

def commit_and_push():
    try:
        subprocess.run(["git", "add", "targets.json", "types.json"], check=False)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update [skip ci]"], check=False)
        subprocess.run(["git", "push"], check=False)
    except: pass

async def auto_cleanup():
    """Видаляє цілі, час яких вичерпано"""
    while True:
        data = db('targets.json')
        now = datetime.now()
        new_data = [t for t in data if datetime.fromisoformat(t['expire_at']) > now and t['status'] == 'active']
        if len(new_data) != len(data):
            db('targets.json', new_data)
        await asyncio.sleep(60)

# ================= ПАРСИНГ ТА ОБРОБКА =================

async def get_coords_online(place_name):
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": "NeptunBot/1.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        res = data[0]
                        return [float(res["lat"]), float(res["lon"]), res["display_name"].split(',')[0]]
    except: pass
    return None

@client.on(events.NewMessage)
async def handle_channel(event):
    if event.chat and getattr(event.chat, 'username', '') == CHANNEL_ID:
        raw_text = event.raw_text
        # Визначаємо локацію
        clean = re.sub(r'(🚨|⚠️|Увага|БПЛА|Тип)', '', raw_text).strip()
        target_name = clean.split('\n')[0].split(' ')[0] # Спрощено для прикладу
        
        found_point = await get_coords_online(target_name)
        if not found_point: return

        # Визначаємо тип
        final_type = "unknown"
        if "ппо" in raw_text.lower(): final_type = "air_defense"
        elif "шахед" in raw_text.lower() or "мопед" in raw_text.lower(): final_type = "drone"
        elif "ракета" in raw_text.lower(): final_type = "missile"

        # Визначаємо напрямок
        direction = None
        for key, deg in DIRECTION_MAP.items():
            if key in raw_text.lower():
                direction = deg
                break

        new_target = {
            "id": event.id, "type": final_type, "count": 1,
            "status": "active", "lat": found_point[0], "lng": found_point[1],
            "direction": direction,
            "label": f"{found_point[2]}",
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
        }
        
        data = db('targets.json')
        data = [t for t in data if t['id'] != event.id]
        data.append(new_target)
        db('targets.json', data)

async def main():
    await client.start(bot_token=BOT_TOKEN)
    asyncio.create_task(auto_cleanup())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
