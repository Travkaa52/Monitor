import os
import json
import asyncio
from telethon import TelegramClient, events, types

# Налаштування (беруться з GitHub Secrets)
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',')]
DATA_FILE = 'targets.json'

def update_db(new_target):
    """Функція для безпечного оновлення JSON файлу"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                data = {"items": []}
    else:
        data = {"items": []}

    data['items'].append(new_target)
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def main():
    # Ініціалізація клієнта всередині асинхронної функції
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    
    print("Бот запущений. Очікування даних з Mini App або команд...")

    # Перевіряємо останні повідомлення (для роботи в GitHub Actions)
    async for message in client.iter_messages(BOT_TOKEN, limit=15):
        if message.sender_id not in ADMIN_IDS:
            continue

        # 1. ОБРОБКА ДАНИХ З MINI APP (через кнопку меню)
        if message.web_app_data:
            try:
                raw_json = message.web_app_data.data
                app_data = json.loads(raw_json)
                
                # Формуємо об'єкт цілі
                target = {
                    "id": str(os.urandom(3).hex()),
                    "type": app_data.get('type', 'shahed'),
                    "lat": float(app_data.get('lat')),
                    "lon": float(app_data.get('lon')),
                    "bearing": int(app_data.get('bearing', 0)),
                    "description": "Додано через Mini App"
                }
                
                update_db(target)
                await message.respond(f"✅ Mini App: {target['type']} додано (ID: {target['id']})")
            except Exception as e:
                print(f"Помилка Mini App: {e}")

        # 2. ОБРОБКА ТЕКСТОВИХ КОМАНД (якщо захочете вручну)
        elif message.text:
            text = message.text
            if text.startswith('/clear'):
                with open(DATA_FILE, 'w') as f:
                    json.dump({"items": []}, f)
                await message.respond("🧹 Карту очищено")
            
            elif text.startswith('/add'):
                # Ваша стара логіка /add
                try:
                    p = text.split(maxsplit=5)
                    target = {
                        "id": str(os.urandom(3).hex()),
                        "type": p[1],
                        "lat": float(p[2]),
                        "lon": float(p[3]),
                        "bearing": int(p[4]),
                        "description": p[5] if len(p)>5 else ""
                    }
                    update_db(target)
                    await message.respond(f"🎯 Текст: {p[1]} додано")
                except:
                    pass

    # Завершуємо сесію для GitHub Actions
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
