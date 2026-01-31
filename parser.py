import asyncio
import json
import os
import re
import threading
import logging
import subprocess
import aiohttp
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN_CORE")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'cxidua', 'tlknewsua', 'radar_kharkov']

# Райони для зафарбовування
DISTRICTS_MAP = {
    "Богодухів": "Bohodukhivskyi",
    "Харків": "Kharkivskyi",
    "Чугуїв": "Chuhuivskyi",
    "Ізюм": "Iziumskyi",
    "Куп": "Kupianskyi",
    "Лозів": "Lozivskyi",
    "Красноград": "Krasnohradskyi"
}

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= СИСТЕМНІ ФУНКЦІЇ (БАЗА ТА ГІТ) =================

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
            try:
                subprocess.run(["git", "config", "user.name", "NeptunBot"], check=False)
                subprocess.run(["git", "config", "user.email", "bot@neptun.com"], check=False)
                subprocess.run(["git", "add", file], check=False)
                subprocess.run(["git", "commit", "-m", f"📡 Sync {file}", "--no-verify"], check=False)
                subprocess.run(["git", "push"], check=False)
            except: pass

# ================= ГЕО-ФУНКЦІЇ (СТАРІ) =================

def clean_location_name(text):
    """Твоя стара логіка очищення тексту"""
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення|БПЛА|Ракета|КАБ|Шахед|Мопед)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз|біля)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '')
    return name if len(name) > 2 else None

async def get_coords(place):
    """Твоя стара логіка запитів до OSM"""
    if not place: return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place}, Харківська область, Україна", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"NeptunMap/1.2"}) as resp:
                data = await resp.json()
                if data:
                    return [float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(',')[0]]
    except: pass
    return None

# ================= ЛОГІКА РЕТРАНСЛЯТОРА (СТАРА) =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_handler(event):
    if not event.raw_text: return
    text_lc = event.raw_text.lower()
    
    # Фільтрація повідомлень про Харківщину
    is_kharkiv = any(word in text_lc for word in ["харків", "область", "хнс", "чугуїв", "куп", "люботин", "богодухів"])
    
    if is_kharkiv:
        try:
            await client.send_message(MY_CHANNEL, event.message)
            logger.info("♻️ Ретрансляція успішна")
        except Exception as e:
            logger.error(f"Помилка пересилки: {e}")

# ================= ЛОГІКА ПАРСЕРА (ТОЧКИ + РАЙОНИ) =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_handler(event):
    raw_text = event.raw_text
    text_lc = raw_text.lower()
    
    # 1. ОБРОБКА ТРИВОГ (НОВА ЛОГІКА ЗАФАРБОВУВАННЯ)
    if any(x in raw_text for x in ["🔴", "🟢", "тривога", "відбій"]):
        alerts = db('alerts.json')
        updated = False
        for ua_pattern, en_id in DISTRICTS_MAP.items():
            if ua_pattern.lower() in text_lc:
                # 🔴 - тривога, 🟢 - відбій
                is_active = "🔴" in raw_text or "тривога" in text_lc
                alerts[en_id] = {"active": is_active}
                updated = True
        if updated:
            db('alerts.json', alerts)
            logger.info("🚨 СТАТУС РАЙОНІВ ОНОВЛЕНО")
            return

    # 2. ОБРОБКА МІТОК (СТАРА ЛОГІКА З ФОЛБЕКОМ)
    loc_name = clean_location_name(raw_text)
    coords = await get_coords(loc_name)
    
    if not coords:
        # Якщо локацію не розпізнано, ставимо Харків, щоб повідомлення було на карті
        coords = [49.9935, 36.2304, "Харків (Моніторинг)"]

    # Тип загрози
    found_type = "unknown"
    for t_type, keywords in [("drone", ["шахед", "мопед"]), ("missile", ["ракет"]), ("kab", ["каб", "авіабомб"])]:
        if any(word in text_lc for word in keywords):
            found_type = t_type; break

    new_target = {
        "id": event.id,
        "type": found_type,
        "lat": coords[0],
        "lng": coords[1],
        "label": f"{SYMBOLS.get(found_type, '❓')} | {coords[2]}",
        "time": datetime.now().strftime("%H:%M"),
        "expire_at": (datetime.now() + timedelta(minutes=40)).isoformat()
    }

    targets = db('targets.json')
    if not isinstance(targets, list): targets = []
    
    targets = [t for t in targets if t['id'] != event.id]
    targets.append(new_target)
    db('targets.json', targets[-15:]) # Зберігаємо останні 15 міток
    logger.info(f"✅ Метка додана: {coords[2]}")

async def main():
    await client.start()
    logger.info("✅ NEPTUN SYSTEM ONLINE")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
