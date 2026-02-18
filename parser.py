import os
import json
import asyncio
from telethon import TelegramClient, events, types

# Налаштування
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
# Беремо перший ID зі списку адмінів для перевірки повідомлень
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',')]
DATA_FILE = 'targets.json'

def update_db(new_target):
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
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    
    print("Бот запущений. Очікування даних...")

    # ВИПРАВЛЕННЯ: Бот перевіряє повідомлення у діалогах з адмінами
    for admin_id in ADMIN_IDS:
        try:
            # Отримуємо об'єкт чату адміна
            entity = await client.get_input_entity(admin_id)
            
            async for message in client.iter_messages(entity, limit=10):
                # 1. Дані з Mini App
                if message.web_app_data:
                    try:
                        app_data = json.loads(message.web_app_data.data)
                        target = {
                            "id": str(os.urandom(3).hex()),
                            "type": app_data.get('type', 'shahed'),
                            "lat": float(app_data.get('lat')),
                            "lon": float(app_data.get('lon')),
                            "bearing": int(app_data.get('bearing', 0)),
                            "description": "З Mini App"
                        }
                        update_db(target)
                        await message.respond(f"✅ Додано: {target['type']}")
                    except Exception as e:
                        print(f"Помилка даних: {e}")

                # 2. Текстові команди
                elif message.text:
                    if message.text.startswith('/clear'):
                        with open(DATA_FILE, 'w') as f:
                            json.dump({"items": []}, f)
                        await message.respond("🧹 Карту очищено")
        except Exception as e:
            print(f"Не вдалося отримати повідомлення для {admin_id}: {e}")

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
