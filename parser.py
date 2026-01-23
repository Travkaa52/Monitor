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

pending_data = {}
delete_queue = {}

# ================= СИСТЕМА ГІТ-ДЕПЛОЮ =================
def commit_and_push():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", "targets.json", "types.json"], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        if status:
            subprocess.run(["git", "commit", "-m", "📡 Tactical Update [skip ci]"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("🚀 Дані оновлено на GitHub")
    except Exception as e:
        logger.error(f"❌ Git error: {e}")

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
                commit_and_push()
        except Exception as e:
            logger.error(f"БД error: {e}")
            return [] if file == 'targets.json' else {}

# ================= ДОПОМІЖНІ ФУНКЦІЇ =================
def extract_count(text):
    match = re.search(r'(\d+)', text)
    return int(match.group(1)) if match else 1

def advanced_parse(text):
    clean = re.sub(r'(🚨|⚠️|Увага|На даний час|зафіксовано|рух|вектор|напрямок|бпла|тип)', '', text, flags=re.IGNORECASE).strip()
    return re.sub(r'["\'«»]', '', clean.split('курсом')[0].split('на')[0].strip())

# ================= ОСНОВНИЙ ОБРОБНИК =================
@client.on(events.NewMessage)
async def handle_messages(event):
    # 1. АДМІН-КОМАНДИ
    if event.sender_id == ADMIN_ID:
        if event.raw_text in ['/1', '1']:
            targets = db('targets.json')
            active = [t for t in targets if t.get('status') == 'active']
            if not active: return await event.reply("📭 Активних цілей немає.")
            for t in active:
                btns = [[Button.inline("➕", f"edit_cnt:plus:{t['id']}"), Button.inline("➖", f"edit_cnt:minus:{t['id']}")],
                        [Button.inline("🗑 Видалити", f"ask_del:{t['id']}")]]
                await event.reply(f"📡 **Ціль:** {t['label']}\n🔢 Кількість: **{t['count']}**", buttons=btns)
            return

    # 2. МОНІТОРИНГ КАНАЛУ
    if event.chat and getattr(event.chat, 'username', '') == CHANNEL_ID:
        raw_text = event.raw_text
        text = raw_text.lower()
        geo_db = db('geo.json')
        types_db = db('types.json')
        
        found_points = []
        final_type = None

        # Спеціальні типи (ППО/Авіація)
        if any(word in text for word in ["робота ппо", "працює ппо"]):
            final_type = "air_defense"
            if any(bnr in text for bnr in ["бнр", "белгород", "бєлгород"]):
                found_points = [geo_db.get("бнр", [50.59, 36.58, "БНР"])]
        
        if not final_type and "активність" in text and "авіації" in text:
            final_type = "aircraft"
            if "бнр" in text: found_points = [geo_db.get("бнр", [50.59, 36.58, "БНР"])]

        # Пошук точок
        if not found_points:
            for k in sorted(geo_db.keys(), key=len, reverse=True):
                if k in text: found_points.append(geo_db[k])
        
        if not found_points: return

        # Визначення типу
        if not final_type:
            for t_type, keywords in types_db.items():
                if any(word in text for word in keywords):
                    final_type = t_type
                    break
        
        # Навчання новому типу
        if not final_type:
            threat_name = advanced_parse(raw_text)
            pending_data[ADMIN_ID] = {"term": threat_name.lower(), "lat": found_points[-1][0], "lng": found_points[-1][1], "place": found_points[-1][2]}
            btns = [[Button.inline("🛵 Дрон", "add:drone"), Button.inline("🚀 Ракета", "add:missile")],
                    [Button.inline("☄️ КАБ", "add:kab"), Button.inline("💥 ППО", "add:air_defense")],
                    [Button.inline("❌ Ігнор", "cancel")]]
            await client.send_message(ADMIN_ID, f"❓ **Новий тип!**\nТекст: `{raw_text}`", buttons=btns)
            return

        # Збереження
        minutes = 20 if final_type == "air_defense" else (60 if final_type == "aircraft" else 45)
        new_target = {
            "id": event.id, "type": final_type, "count": extract_count(raw_text),
            "status": "active", "reason": "", "lat": found_points[-1][0], "lng": found_points[-1][1],
            "label": f"{SYMBOLS[final_type]} | {' ➜ '.join([p[2] for p in found_points])}",
            "time": datetime.now().strftime("%H:%M"),
            "expire_at": (datetime.now() + timedelta(minutes=minutes)).isoformat()
        }
        
        targets = db('targets.json')
        targets.append(new_target)
        db('targets.json', targets)

# ================= CALLBACKS (Кнопки) =================
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode()
    uid = event.sender_id
    targets = db('targets.json')

    if data.startswith("edit_cnt:"):
        _, act, tid = data.split(":")
        for t in targets:
            if t['id'] == int(tid):
                t['count'] = t['count'] + 1 if act == "plus" else max(1, t['count'] - 1)
                await event.edit(f"📡 **Ціль:** {t['label']}\n🔢 Кількість: **{t['count']}**", 
                                 buttons=[[Button.inline("➕", f"edit_cnt:plus:{tid}"), Button.inline("➖", f"edit_cnt:minus:{tid}")],
                                          [Button.inline("🗑 Видалити", f"ask_del:{tid}")]])
                db('targets.json', targets)
                break

    elif data.startswith("ask_del:"):
        tid = int(data.split(":")[1])
        delete_queue[uid] = tid
        await event.edit("⚠️ **Причина видалення:**", 
                         buttons=[[Button.inline("✅ Знищено", "kill:Знищено"), Button.inline("📉 Впало", "kill:Впало")]])

    elif data.startswith("kill:"):
        reason = data.split(":")[1]
        tid = delete_queue.pop(uid, None)
        for t in targets:
            if t['id'] == tid:
                t['status'], t['reason'] = 'archived', reason
                t['expire_at'] = (datetime.now() + timedelta(minutes=5)).isoformat()
        db('targets.json', targets)
        await event.edit(f"📥 Архів: {reason}")

    elif data.startswith("add:"):
        cat = data.split(":")[1]
        info = pending_data.pop(uid, None)
        if info:
            t_db = db('types.json')
            if cat not in t_db: t_db[cat] = []
            t_db[cat].append(info['term'])
            db('types.json', t_db)
            await event.edit(f"✅ Тип `{info['term']}` додано до {SYMBOLS[cat]}")

# ================= ЗАПУСК =================
def cleanup_worker():
    while True:
        now = datetime.now()
        t_list = db('targets.json')
        filtered = [t for t in t_list if datetime.fromisoformat(t['expire_at']) > now]
        if len(filtered) != len(t_list): db('targets.json', filtered)
        threading.Event().wait(60)

async def main():
    threading.Thread(target=cleanup_worker, daemon=True).start()
    await client.start(bot_token=BOT_TOKEN)
    logger.info("💎 NEPTUN FULL OPERATIONAL")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
