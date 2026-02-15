import os
import json
import asyncio
from telethon import TelegramClient, events

# Конфігурація з GitHub Secrets
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',')]
DATA_FILE = 'targets.json'

def update_json(new_target):
    # Створюємо файл, якщо його не існує
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({"items": []}, f)
            
    with open(DATA_FILE, 'r+') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {"items": []}
        
        data['items'].append(new_target)
        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()

async def main():
    # Ініціалізуємо клієнт всередині main, щоб уникнути конфлікту циклів подій
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    
    print("Бот запущений, очікування команд...")

    @client.on(events.NewMessage(pattern='/add'))
    async def add(event):
        if event.sender_id not in ADMIN_IDS:
            return
        try:
            # Формат: /add тип лат лон курс
            parts = event.text.split()
            if len(parts) < 5:
                await event.respond("❌ Формат: `/add тип lat lon bearing`")
                return

            t_type, lat, lon, bear = parts[1], float(parts[2]), float(parts[3]), int(parts[4])
            
            target = {
                "id": str(os.urandom(3).hex()),
                "type": t_type,
                "lat": lat,
                "lon": lon,
                "bearing": bear,
                "description": "Ціль додана через Telegram"
            }
            
            update_json(target)
            await event.respond(f"✅ Додано: {t_type} (ID: {target['id']})")
            
            # Зупиняємо бота після отримання команди, щоб завершити GitHub Action
            await client.disconnect()
        except Exception as e:
            await event.respond(f"❌ Помилка: {str(e)}")

    @client.on(events.NewMessage(pattern='/clear'))
    async def clear(event):
        if event.sender_id not in ADMIN_IDS: return
        with open(DATA_FILE, 'w') as f:
            json.dump({"items": []}, f)
        await event.respond("🧹 Карту очищено")
        await client.disconnect()

    # Бот чекає 45 секунд. Якщо за цей час ви надішлете команду — Action виконається і збереже дані.
    # Якщо команд не буде — він просто вимкнеться (щоб не витрачати хвилини GitHub Actions).
    try:
        await asyncio.wait_for(client.run_until_disconnected(), timeout=45)
    except asyncio.TimeoutError:
        print("Час очікування вийшов, нових команд немає.")
    finally:
        if client.is_connected():
            await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
