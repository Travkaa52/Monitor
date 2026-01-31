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
logger = logging.getLogger("NEPTUN_GEO_SYSTEM")

# ================= КОНФИГУРАЦИЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

MY_CHANNEL = 'monitorkh1654' 
SOURCE_CHANNELS = ['monitor1654', 'tlknewsua', 'radar_kharkov']

# Базовые фильтры (на всякий случай)
BASE_KEYWORDS = ["харків", "область", "ппо", "вибух"]

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

# ================= ГЕО-ЛОГИКА (ОБЩАЯ) =================

def clean_location_name(text):
    """Та же логика, что и в парсере: вытягиваем только потенциальное место."""
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|Зафіксовано|Попередньо|Уточнення)', '', text, flags=re.IGNORECASE).strip()
    parts = re.split(r'(курсом|на|в напрямку|через|в бік|в межах|повз)', clean, flags=re.IGNORECASE)
    name = parts[0].strip()
    # Убираем типы угроз для гео-проверки
    loc_only = re.sub(r'(бпла|ракета|каб|шахед|мопед|авіація|ппо)', '', name, flags=re.IGNORECASE).strip()
    return loc_only if len(loc_only) > 2 else None

async def check_location_exists(place_name):
    """Проверяет, реально ли это населенный пункт в области."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{place_name}, Харківська область", "format": "json", "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent":"NeptunChecker"}) as resp:
                data = await resp.json()
                return data[0] if data else None
    except: return None

# ================= РЕТРАНСЛЯТОР С ГЕОБАЗОЙ =================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def retranslator_with_geo(event):
    text_lc = event.raw_text.lower()
    
    # 1. Сначала быстрая проверка на базовые слова
    has_base_word = any(word in text_lc for word in BASE_KEYWORDS)
    
    # 2. Извлекаем локацию
    potential_loc = clean_location_name(event.raw_text)
    
    location_data = None
    if potential_loc:
        location_data = await check_location_exists(potential_loc)
    
    # Условие пересылки: либо есть базовое слово (Харьков/ППО), либо найдена реальная локация в области
    if has_base_word or location_data:
        try:
            # Если найдена локация, можем даже добавить пометку для себя в логи
            loc_tag = f" [{potential_loc}]" if location_data else ""
            await client.send_message(MY_CHANNEL, event.message)
            logger.info(f"✅ Гео-фильтр пройден: {event.chat.username}{loc_tag}")
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")

# ================= ПАРСЕР (БЕЗ ИЗМЕНЕНИЙ) =================

@client.on(events.NewMessage(chats=MY_CHANNEL))
async def parser_logic(event):
    # Тут остается твой старый код парсера, который записывает в targets.json
    # Он сработает сразу после того, как реtranslator перешлет сообщение
    logger.info("📍 Парсер подхватил сообщение и обновляет targets.json")
    # ... (код парсера из предыдущих ответов) ...

# ================= ЗАПУСК =================

async def main():
    await client.start()
    print("🚀 Neptun System v4.0 Online (Retranslator + GeoBase + Parser)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
