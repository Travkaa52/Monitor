import asyncio
import os
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "") 

admin_raw = os.getenv("ADMIN_IDS", "0")
ADMIN_IDS = [int(i.strip()) for i in admin_raw.split(",") if i.strip().isdigit()]

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# ================= ОБРОБКА БУДЬ-ЯКИХ ПОВІДОМЛЕНЬ =================
@client.on(events.NewMessage(incoming=True))
async def debug_handler(event):
    # Бот логує все, що бачить
    sender_id = event.sender_id
    text = event.raw_text
    logger.info(f"🔔 ПОМІЧЕНО ПОВІДОМЛЕННЯ: від {sender_id}, текст: {text}")
    
    # Якщо це один з адмінів
    if sender_id in ADMIN_IDS:
        await event.reply(f"✅ Я тебе бачу! Твій ID: `{sender_id}`. Команда: {text}")
    else:
        # Якщо пише хтось інший (або твій ID не в списку)
        await event.reply(f"❌ Доступ обмежено. Твій ID `{sender_id}` не знайдено в ADMIN_IDS.")

# ================= ГОЛОВНИЙ ЦИКЛ =================
async def main():
    try:
        await client.start(bot_token=BOT_TOKEN)
        logger.info(f"💎 БОТ ЗАПУЩЕНИЙ. Очікую повідомлень...")
        logger.info(f"Дозволені ID: {ADMIN_IDS}")
        
        # Працюємо 15 хвилин
        await asyncio.wait_for(client.run_until_disconnected(), timeout=900)
    except Exception as e:
        logger.error(f"💥 Помилка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
