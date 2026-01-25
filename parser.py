БПЛАкахt json
import os
import re
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

pending_targets = {}
delete_queue = {}

# ================= ЛОГІКА ПАРСИНГУ =================

def parse_direction(text):
    """Визначає кут напрямку на основі ключових слів."""
    text_lc = text.lower()
    for key, deg in DIRECTION_MAP.items():
        if key in text_lc:
            return deg
    return None

def clean_location_name(text):
    """Витягує чисту назву населеного пункту."""
    clean = re.sub(r'(🚨|⚠️|Увага|Рух|Вектор|Напрямок|БПЛА|Тип|пахед|РатетаЗафіксовано|Попередньо)', '', text, flags=re.IGNORECASE).strip()
    # Розбиваємо текст по роздільниках напрямку
    parts = re.split(r'(курсом|на|в напрямку|через|в бік)', clean, flags=re.IGNORECASE)
    name = parts[0].strip().replace('"', '').replace('«', '').replace('»', '')
    return name if len(name) > 2 else None

def extract_count(text):
    match = re.search(r'(\d+)', text)
    return int(match.group(1)) if match else 1

# ================= ГЕО ТА БД =================

async def get_coords_online(place_name):
    query = f"{place_name}, Харківська область, Україна"
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": "NeptunTacticalBot/1.0"}
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

def db(file, data=None):
    with db_lock:
        try:
            if data is None:
                if not os.path.exists(file): return [] if file == 'targets.json' else {}
                with open(file, 'r', encoding='utf-8') as f: return json.load(f)
            else:
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                commit_and_push()
        except Exception as e:
            logger.error(f"БД error: {e}")
            return [] if file == 'targets.json' else {}

def commit_and_push():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=False)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=False)
        subprocess.run(["git", "add", "targets.json", "types.json"], check=False)
        subprocess.run(["git", "commit", "-m", "📡 Tactical Update [skip ci]"], check=False)
        subprocess.run(["git", "push"], check=False)
    except: pass

# ================= ОБРОБКА КАНАЛУ =================

@client.on(events.NewMessage)
async def handle_channel(event):
    if event.chat and getattr(event.chat, 'username', '') == CHANNEL_ID:
        raw_text = event.raw_text
        
        # 1. Визначаємо локацію та координати
        target_name = clean_location_name(raw_text)
        if not target_name: return
        
        found_point = await get_coords_online(target_name)
        if not found_point: return

        # 2. Визначаємо тип
        types_db = db('types.json')
        text_lc = raw_text.lower()
        final_type = None
        
        if any(w in text_lc for w in ["робота ппо", "працює ппо"]): final_type = "air_defense"
        
        if not final_type:
            for t_type, keywords in types_db.items():
                if any(word in text_lc for word in keywords):
                    final_type = t_type; break
        
        # 3. Напрямок
        direction = parse_direction(raw_text)

        if not final_type:
            final_type = "unknown"
            pending_targets[event.id] = {"term": target_name.lower()}
            btns = [[Button.inline("🛵 Дрон", f"learn:drone:{event.id}"), Button.inline("🚀 Ракета", f"learn:missile:{event.id}")],
                    [Button.inline("☄️ КАБ", f"learn:kab:{event.id}"), Button.inline("💥 ППО", f"learn:air_defense:{event.id}")]]
            for adm in ADMIN_IDS:
                try: await client.send_message(adm, f"❓ **Новий тип!**\n`{raw_text}`", buttons=btns)
                except: pass

        # 4. Формуємо об'єкт
        new_target = {
            "id": event.id, "type": final_type, "count": extract_count(raw_text),
            "status": "active", "reason": "", "lat": found_point[0], "lng": found_point[1],
            "direction": direction,
            "label": f"{SYMBOLS.get(final_type, '❓')} | {found_point[2]}",
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
        }
        
        data = db('targets.json')
        # Оновлюємо, якщо повідомлення редаговане
        data = [t for t in data if t['id'] != event.id]
        data.append(new_target)
        db('targets.json', data)

# ================= АДМІН ПАНЕЛЬ ТА CALLBACKS =================

@client.on(events.NewMessage(from_users=ADMIN_IDS))
async def admin_cmd(event):
    text = event.raw_text.lower()
    if text in ['1', '/list']:
        targets = db('targets.json')
        active = [t for t in targets if t.get('status') == 'active']
        if not active: return await event.reply("📭 Активних цілей немає.")
        for t in active:
            btns = [
                [Button.inline("➕", f"edit_cnt:plus:{t['id']}"), Button.inline("➖", f"edit_cnt:minus:{t['id']}")],
                [Button.inline("🧭 Курс", f"set_dir_menu:{t['id']}")],
                [Button.inline("🗑 Видалити", f"ask_del:{t['id']}")]
            ]
            await event.reply(f"📡 **Ціль:** {t['label']}\n🔢 Кількість: **{t['count']}**\n🧭 Курс: {t.get('direction', 'Немає')}°", buttons=btns)

@client.on(events.CallbackQuery)
async def cb_handler(event):
    if event.sender_id not in ADMIN_IDS: return
    data = event.data.decode(); tid = data.split(":")[-1]; targets = db('targets.json')
    
    if data.startswith("learn:"):
        _, cat, _ = data.split(":")
        info = pending_targets.pop(int(tid), None)
        if info:
            t_db = db('types.json')
            if cat not in t_db: t_db[cat] = []
            if info['term'] not in t_db[cat]: t_db[cat].append(info['term']); db('types.json', t_db)
            await event.edit(f"✅ Тип {cat} вивчено.")

    elif data.startswith("set_dir_menu:"):
        dir_btns = [
            [Button.inline("⬆️ Пн", f"save_dir:0:{tid}"), Button.inline("↗️ Пн-Сх", f"save_dir:45:{tid}")],
            [Button.inline("➡️ Сх", f"save_dir:90:{tid}"), Button.inline("⬇️ Пд", f"save_dir:180:{tid}")],
            [Button.inline("⬅️ Зх", f"save_dir:270:{tid}"), Button.inline("🚫 Скинути", f"save_dir:none:{tid}")]
        ]
        await event.edit("🧭 Оберіть напрямок:", buttons=dir_btns)

    elif data.startswith("save_dir:"):
        _, deg, _ = data.split(":")
        for t in targets:
            if t['id'] == int(tid): t['direction'] = int(deg) if deg != "none" else None
        db('targets.json', targets); await event.edit("✅ Напрямок оновлено.")

    elif data.startswith("ask_del:"):
        delete_queue[event.sender_id] = int(tid)
        await event.edit("⚠️ Причина:", buttons=[[Button.inline("✅ Знищено", "kill:Знищено"), Button.inline("📉 Впало", "kill:Впало")]])

    elif data.startswith("kill:"):
        reason = data.split(":")[1]; target_id = delete_queue.pop(event.sender_id, None)
        for t in targets:
            if t['id'] == target_id: t['status'], t['reason'] = 'archived', reason
        db('targets.json', targets); await event.edit(f"📥 Архів: {reason}")

async def main():
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

