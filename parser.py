import asyncio
import json
import os
import re
import threading
import logging
import subprocess
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN")

# ================= КОНФІГУРАЦІЯ (Беремо з Secrets) =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# ВАЖЛИВО: SESSION_STRING треба отримати один раз локально
SESSION_STRING = os.getenv("SESSION_STRING", "") 
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHANNEL_ID = 'monitorkh1654'

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db_lock = threading.Lock()

SYMBOLS = {
    "air_defense": "💥 ППО", "drone": "🛵 Мопед", "missile": "🚀 Ракета",
    "kab": "☄️ КАБ", "mrls": "🔥 РСЗВ", "recon": "🛸 Розвідка",
    "aircraft": "✈️ Авіація", "unknown": "❓ Невідомо"
}

# ================= СИСТЕМА ГІТ-ДЕПЛОЮ =================
def commit_and_push():
    """Автоматично відправляє зміни targets.json на GitHub Pages"""
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "targets.json", "types.json"], check=True)
        # Перевірка чи є зміни
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        if status:
            subprocess.run(["git", "commit", "-m", "📡 Tactical Update [skip ci]"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("🚀 Дані успішно оновлено на GitHub Pages")
    except Exception as e:
        logger.error(f"❌ Помилка Git: {e}")

# ================= РОБОТА З БД =================
def db(file, data=None):
    with db_lock:
        try:
            if data is None:
                if not os.path.exists(file): return [] if file == 'targets.json' else {}
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            else:
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                # Якщо змінили БД — пушимо в Гіт
                if file == 'targets.json': commit_and_push()
        except Exception as e:
            logger.error(f"Помилка БД: {e}")
            return [] if file == 'targets.json' else {}

# --- (Функції extract_count, advanced_parse, monitor, callback_handler залишаються такими ж) ---
# Додай їх сюди зі свого попереднього коду

# ================= ОЧИЩЕННЯ ТА ЦИКЛ =================
def cleanup_worker():
    while True:
        now = datetime.now()
        t_list = db('targets.json')
        if t_list:
            filtered = [t for t in t_list if datetime.fromisoformat(t['expire_at']) > now]
            if len(filtered) != len(t_list):
                db('targets.json', filtered)
        threading.Event().wait(60)

async def main():
    # Запуск очищення в окремому потоці
    threading.Thread(target=cleanup_worker, daemon=True).start()
    
    # Стартуємо клієнт (Бот-токен не потрібен, якщо використовуємо StringSession юзера)
    # Або використовуємо start(bot_token=...)
    await client.start(bot_token=BOT_TOKEN)
    logger.info("💎 NEPTUN ONLINE ON GITHUB ACTIONS")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
