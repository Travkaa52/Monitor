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

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEPTUN")

# ================= КОНФІГУРАЦІЯ =================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
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

ADMIN_HELP_TEXT = """
🚀 **NEPTUN TACTICAL TERMINAL**
Команди керування:

🔢 `1` або `/list` — Керування активними цілями.
📊 `/stats` — Статистика об'єктів та баз.
🔍 `/geo [назва]` — Тестовий пошук координат.
➕ `/add [тип] [місто]` — Ручне додавання мітки.
🧹 `/clear` — Очистити карту (скидання targets.json).
❓ `/help` — Виклик цього меню.

*Типи для додавання:* `drone`, `missile`, `kab`, `air_defense`
"""

pending_targets = {}
delete_queue = {}

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

def extract_count(text):
    match = re.search(r'(\d+)', text)
    return int(match.group(1)) if match else 1

def advanced_parse(text):
    clean = re.sub(r'(🚨|⚠️|Увага|На даний час|зафіксовано|рух|вектор|напрямок|бпла|тип|каб|ракета|шахед|мопед)', '', text, flags=re.IGNORECASE).strip()
    return re.sub(r'["\'«»]', '', clean.split('курсом')[0].split('на')[0].strip())

# ================= АДМІН ПАНЕЛЬ =================
@client.on(events.NewMessage(incoming=True, from_users=ADMIN_ID))
async def admin_panel(event):
    text = event.raw_text.lower()
    
    if text in ['/help', '/start', 'допомога']:
        await event.reply(ADMIN_HELP_TEXT)

    elif text in ['1', '/1', '/list']:
        targets = db('targets.json')
        active = [t for t in targets if t.get('status') == 'active']
        if not active: return await event.reply("📭 Активних цілей немає.")
        for t in active:
            btns = [[Button.inline("➕", f"edit_cnt:plus:{t['id']}"), Button.inline("➖", f"edit_cnt:minus:{t['id']}")],
                    [Button.inline("🗑 Видалити", f"ask_del:{t['id']}")]]
            await event.reply(f"📡 **Ціль:** {t['label']}\n🔢 Кількість: **{t['count']}**", buttons=btns)

    elif text == '/stats':
        targets = db('targets.json')
        types = db('types.json')
        active = len([t for t in targets if t.get('status') == 'active'])
        await event.reply(f"📊 **СТАТИСТИКА:**\nАктивно цілей: `{active}`\nБаза типів: `{len(types)}` кат.")

    elif text == '/clear':
        db('targets.json', [])
        await event.reply("🧹 Карта очищена.")

    elif text.startswith('/geo'):
        place = text.replace('/geo', '').strip()
        res = await get_coords_online(place)
        if res: await event.reply(f"📍 **{res[2]}**\n`{res[0]}, {res[1]}`")
        else: await event.reply("❌ Не знайдено.")

    elif text.startswith('/add'):
        try:
            p = text.split(' ')
            t_type, place = p[1], " ".join(p[2:])
            res = await get_coords_online(place)
            if res:
                new_t = {
                    "id": int(datetime.now().timestamp()), "type": t_type, "count": 1, "status": "active",
                    "reason": "", "lat": res[0], "lng": res[1],
                    "label": f"{SYMBOLS.get(t_type, '❓')} | {res[2]} (MANUAL)",
                    "time": datetime.now().strftime("%H:%M"),
                    "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
                }
                data = db('targets.json'); data.append(new_t); db('targets.json', data)
                await event.reply(f"✅ Додано: {res[2]}")
        except: await event.reply("Формат: `/add drone місто`")

# ================= МОНІТОРИНГ КАНАЛУ =================
@client.on(events.NewMessage)
async def handle_channel(event):
    if event.chat and getattr(event.chat, 'username', '') == CHANNEL_ID:
        raw_text = event.raw_text
        target_name = advanced_parse(raw_text)
        if not target_name or len(target_name) < 3: return

        found_point = await get_coords_online(target_name)
        if not found_point: return

        types_db = db('types.json')
        text = raw_text.lower()
        final_type = None
        if any(w in text for w in ["робота ппо", "працює ппо"]): final_type = "air_defense"
        
        if not final_type:
            for t_type, keywords in types_db.items():
                if any(word in text for word in keywords):
                    final_type = t_type; break
        
        if not final_type:
            final_type = "unknown"
            pending_targets[event.id] = {"term": target_name.lower()}
            btns = [[Button.inline("🛵 Дрон", f"learn:drone:{event.id}"), Button.inline("🚀 Ракета", f"learn:missile:{event.id}")],
                    [Button.inline("☄️ КАБ", f"learn:kab:{event.id}"), Button.inline("💥 ППО", f"learn:air_defense:{event.id}")]]
            await client.send_message(ADMIN_ID, f"❓ **Новий тип!**\n`{raw_text}`", buttons=btns)

        new_target = {
            "id": event.id, "type": final_type, "count": extract_count(raw_text),
            "status": "active", "reason": "", "lat": found_point[0], "lng": found_point[1],
            "label": f"{SYMBOLS.get(final_type, '❓')} | {found_point[2]}",
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": (datetime.now() + timedelta(minutes=45)).isoformat()
        }
        data = db('targets.json'); data.append(new_target); db('targets.json', data)

# ================= CALLBACKS =================
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode(); uid = event.sender_id; targets = db('targets.json')
    if data.startswith("learn:"):
        _, cat, tid = data.split(":")
        info = pending_targets.pop(int(tid), None)
        if info:
            t_db = db('types.json')
            if cat not in t_db: t_db[cat] = []
            if info['term'] not in t_db[cat]: t_db[cat].append(info['term']); db('types.json', t_db)
            for t in targets:
                if t['id'] == int(tid): t['type'] = cat; t['label'] = t['label'].replace(SYMBOLS["unknown"], SYMBOLS[cat])
            db('targets.json', targets); await event.edit(f"✅ Вивчено -> {SYMBOLS[cat]}")
    elif data.startswith("edit_cnt:"):
        _, act, tid = data.split(":")
        for t in targets:
            if t['id'] == int(tid):
                t['count'] = t['count'] + 1 if act == "plus" else max(1, t['count'] - 1)
                db('targets.json', targets)
                await event.edit(f"📡 **Ціль:** {t['label']}\n🔢 Кількість: **{t['count']}**", 
                                 buttons=[[Button.inline("➕", f"edit_cnt:plus:{tid}"), Button.inline("➖", f"edit_cnt:minus:{tid}")],
                                          [Button.inline("🗑 Видалити", f"ask_del:{tid}")]])
    elif data.startswith("ask_del:"):
        delete_queue[uid] = int(data.split(":")[1])
        await event.edit("⚠️ Причина:", buttons=[[Button.inline("✅ Знищено", "kill:Знищено"), Button.inline("📉 Впало", "kill:Впало")]])
    elif data.startswith("kill:"):
        reason = data.split(":")[1]; tid = delete_queue.pop(uid, None)
        for t in targets:
            if t['id'] == tid: t['status'], t['reason'] = 'archived', reason
        db('targets.json', targets); await event.edit(f"📥 Архів: {reason}")

# ================= ЗАПУСК =================
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("💎 NEPTUN ONLINE")
    try: await client.send_message(ADMIN_ID, "✅ **СИСТЕМА ГОТОВА**\n" + ADMIN_HELP_TEXT)
    except: pass
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
