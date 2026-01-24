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

# Черга для навчання: зберігає дані повідомлення, поки адмін не вибере тип
pending_targets = {}
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
    # 1. АДМІН-КОМАНДИ (Керування списком)
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
        
        if not final_type and "активність" in text and "авіації" in text:
            final_type = "aircraft"

        # Пошук точок
        for k in sorted(geo_db.keys(), key=len, reverse=True):
            if k in text: found_points.append(geo_db[k])
        
        if not found_points: return

        # Визначення типу з бази
        if not final_type:
            for t_type, keywords in types_db.items():
                if any(word in text for word in keywords):
                    final_type = t_type
                    break
        
        # ЛОГІКА НАВЧАННЯ: Якщо тип невідомий - ставимо unknown і питаємо адміна
        is_learning = False
        if not final_type:
            final_type = "unknown"
            is_learning = True
            threat_name = advanced_parse(raw_text)
            pending_targets[event.id] = {"term": threat_name.lower()}
            
            btns = [[Button.inline("🛵 Дрон", f"learn:drone:{event.id}"), Button.inline("🚀 Ракета", f"learn:missile:{event.id}")],
                    [Button.inline("☄️ КАБ", f"learn:kab:{event.id}"), Button.inline("💥 ППО", f"learn:air_defense:{event.id}")]]
            await client.send_message(ADMIN_ID, f"❓ **Новий тип!**\nТекст: `{raw_text}`\nЯ вивів це як 'Невідомо'. Виберіть тип:", buttons=btns)

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

    # Навчання (learn:тип:id_повідомлення)
    if data.startswith("learn:"):
        _, cat, tid = data.split(":")
        tid = int(tid)
        info = pending_targets.pop(tid, None)
        if info:
            # Оновлюємо базу знань
            t_db = db('types.json')
            if cat not in t_db: t_db[cat] = []
            if info['term'] not in t_db[cat]:
                t_db[cat].append(info['term'])
                db('types.json', t_db)
            
            # Оновлюємо вже існуючу мітку в targets.json
            for t in targets:
                if t['id'] == tid:
                    t['type'] = cat
                    t['label'] = t['label'].replace(SYMBOLS["unknown"], SYMBOLS[cat])
                    break
            db('targets.json', targets)
            await event.edit(f"✅ Вивчено: `{info['term']}` -> {SYMBOLS[cat]}")

    elif data.startswith("edit_cnt:"):
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

# ================= ЗАПУСК =================
def cleanup_worker():
    while True:
        try:
            now = datetime.now()
            t_list = db('targets.json')
            filtered = [t for t in t_list if datetime.fromisoformat(t['expire_at']) > now]
            if len(filtered) != len(t_list): db('targets.json', filtered)
        except: pass
        threading.Event().wait(60)

async def main():
    threading.Thread(target=cleanup_worker, daemon=True).start()
    await client.start(bot_token=BOT_TOKEN)
    logger.info("💎 NEPTUN FULL OPERATIONAL")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
