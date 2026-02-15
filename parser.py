import os
import json
import asyncio
from telethon import TelegramClient, events

# Налаштування
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',')]
DATA_FILE = 'targets.json'

async def main():
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    
    # 1. Читаємо старі цілі
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    else:
        data = {"items": []}

    print("Бот активний. Перевірка команд...")

    # 2. Обробка команд (Add/Clear/Status)
    # Формат: /add тип lat lon bearing опис
    async for message in client.iter_messages(BOT_TOKEN, limit=10):
        if message.sender_id in ADMIN_IDS and message.text:
            text = message.text
            
            if text.startswith('/add'):
                try:
                    p = text.split(maxsplit=5)
                    new_id = str(os.urandom(3).hex())
                    new_target = {
                        "id": new_id,
                        "type": p[1],
                        "lat": float(p[2]),
                        "lon": float(p[3]),
                        "bearing": int(p[4]),
                        "description": p[5] if len(p)>5 else ""
                    }
                    data['items'].append(new_target)
                    await message.respond(f"🎯 Додано: {p[1]} (ID: {new_id})")
                except:
                    await message.respond("❌ Помилка. Формат: `/add тип lat lon bearing опис`")

            elif text.startswith('/clear'):
                data = {"items": []}
                await message.respond("🧹 Карту очищено")

    # 3. Зберігаємо оновлений файл
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
