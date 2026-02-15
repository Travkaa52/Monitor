import os
import json
import asyncio
from telethon import TelegramClient, events

# Конфигурация
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',')]
DATA_FILE = 'targets.json'

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

def update_json(new_target):
    with open(DATA_FILE, 'r+') as f:
        data = json.load(f)
        data['items'].append(new_target)
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()

@client.on(events.NewMessage(pattern='/add'))
async def add(event):
    if event.sender_id not in ADMIN_IDS: return
    try:
        # Формат: /add тип лат лон курс (напр. /add shahed 49.9 36.2 220)
        _, t, lat, lon, bear = event.text.split()
        target = {
            "id": str(os.urandom(4).hex()),
            "type": t, "lat": float(lat), "lon": float(lon), "bearing": int(bear)
        }
        update_json(target)
        await event.respond(f"✅ Добавлено!")
        await client.disconnect() # Важно для завершения Action
    except:
        await event.respond("Ошибка! Формат: /add тип лат лон курс")

async def main():
    # Бот ждет команду 45 секунд, если команд нет - закрывается (экономит ресурсы)
    try:
        await asyncio.wait_for(client.run_until_disconnected(), timeout=45)
    except asyncio.TimeoutError:
        pass

if __name__ == '__main__':
    asyncio.run(main())
