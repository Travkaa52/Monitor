import asyncio
import json
import os
import base64
import threading
import requests
from datetime import datetime, timedelta
from telethon import TelegramClient, events

# =============================================
# --- НАЛАШТУВАННЯ TELEGRAM (з env / GitHub Secrets) ---
# =============================================
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']

# Кілька каналів через кому: "monitorkh1654,another_channel,third_channel"
SOURCE_CHANNELS = [c.strip() for c in os.environ.get('SOURCE_CHANNELS', '').split(',') if c.strip()]
if not SOURCE_CHANNELS:
    raise RuntimeError("Не задано жодного каналу у SOURCE_CHANNELS (env)")

# Опційно: кому слати сповіщення про збої парсера (через кому: "123456,789012")
ADMIN_IDS = [a.strip() for a in os.environ.get('ADMIN_IDS', '').split(',') if a.strip()]
BOT_TOKEN = os.environ.get('BOT_TOKEN')  # той самий бот, що і для Mini App

# =============================================
# --- НАЛАШТУВАННЯ GITHUB ---
# =============================================
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
# GITHUB_REPOSITORY приходить від Actions як "owner/repo"
_repo_full = os.environ['GITHUB_REPOSITORY']
GITHUB_OWNER, GITHUB_REPO = _repo_full.split('/', 1)
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
GITHUB_FILE = os.environ.get('GITHUB_FILE', 'targets.json')

# =============================================
# --- РОЗШИРЕНИЙ СЛОВНИК СЛЕНГУ ТА ТИПІВ ---
# =============================================
TARGET_TYPES = {
    "recon":    ["зала", "zala", "розвід", "орлан", "суперкам", "supercam", "безпілотник"],
    "kab":      ["каб", "пуск", "авіабомба", "фаб", "керована"],
    "aircraft": ["петухи", "су-34", "су-35", "борт", "літак", "сушка"],
    "mrls":     ["рсзв", "град", "смерч", "ураган", "вихід", "обстріл"],
    "drone":    ["шахед", "бпла", "мопед", "герань", "шахід"],
    "missile":  ["ракета", "іскандер", "х-101", "кинджал", "балістика"]
}

# =============================================
# --- ГЕОДАНІ ХАРКІВСЬКОЇ ОБЛАСТІ ---
# =============================================
GEO_DATA = {
    "харків":           [49.99, 36.23, "Обласний центр"],
    "харьков":          [49.99, 36.23, "Обласний центр"],
    "пісочин":          [49.95, 36.10, "Харківський р-н"],
    "солоницівка":      [50.01, 36.05, "Харківський р-н"],
    "люботин":          [49.94, 35.92, "Харківський р-н"],
    "мерефа":           [49.82, 36.05, "Харківський р-н"],
    "циркуни":          [50.07, 36.38, "Харківський р-н"],
    "липці":            [50.20, 36.42, "Харківський р-н"],
    "руська лозова":    [50.13, 36.29, "Харківський р-н"],
    "кутузівка":        [50.02, 36.46, "Харківський р-н"],
    "козача лопань":    [50.33, 36.19, "Харківський р-н"],
    "дергачі":          [50.11, 36.12, "Харківський р-н"],
    "чугуїв":           [49.83, 36.68, "Чугуївський р-н"],
    "вовчанськ":        [50.28, 36.93, "Чугуївський р-н"],
    "старий салтів":    [50.08, 36.79, "Чугуївський р-н"],
    "малинівка":        [49.79, 36.72, "Чугуївський р-н"],
    "печеніги":         [49.86, 36.93, "Чугуївський р-н"],
    "білий колодязь":   [50.20, 37.14, "Чугуївський р-н"],
    "вовчанські хутори":[50.28, 37.03, "Чугуївський р-н"],
    "куп'янськ":        [49.70, 37.61, "Куп'янський р-н"],
    "вузлова":          [49.67, 37.64, "Куп'янськ-Вузловий"],
    "ківшарівка":       [49.62, 37.68, "Куп'янський р-н"],
    "шевченкове":       [49.70, 37.17, "Куп'янський р-н"],
    "дворічна":         [49.85, 37.67, "Куп'янський р-н"],
    "боросте":          [49.33, 37.62, "Борівська громада"],
    "ізюм":             [49.19, 37.27, "Ізюмський р-н"],
    "балаклія":         [49.45, 36.85, "Ізюмський р-н"],
    "донець":           [49.46, 36.50, "Ізюмський р-н"],
    "савинці":          [49.40, 36.99, "Ізюмський р-н"],
    "богодухів":        [50.16, 35.52, "Богодухівський р-н"],
    "золочів":          [50.28, 35.97, "Богодухівський р-н"],
    "валки":            [49.83, 35.61, "Богодухівський р-н"],
    "відродженівське":  [50.31, 35.84, "Золочівська громада"],
    "лозова":           [48.88, 36.31, "Лозівський р-н"],
    "первомайський":    [49.38, 36.21, "Лозівський р-н"],
    "красноград":       [49.37, 35.45, "Красноградський р-н"]
}

# =============================================
# --- ГЛОБАЛЬНИЙ СТАН ---
# =============================================
active_targets = []
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_github_sha_cache = None


# =============================================
# --- АДМІН-СПОВІЩЕННЯ ПРО ЗБОЇ ---
# =============================================
def notify_admins(text: str):
    if not BOT_TOKEN or not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": f"⚠️ Monitor parser: {text}"},
                timeout=10
            )
        except Exception as e:
            print(f"⚠️  Не вдалося сповістити адміна {admin_id}: {e}")


# =============================================
# --- GITHUB: PUSH targets.json ---
# =============================================
def _get_github_sha():
    global _github_sha_cache
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        r = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        if r.status_code == 200:
            _github_sha_cache = r.json().get("sha")
        elif r.status_code == 404:
            _github_sha_cache = None
    except Exception as e:
        print(f"⚠️  GitHub GET error: {e}")
    return _github_sha_cache


def push_to_github():
    global _github_sha_cache

    local_path = os.path.join(BASE_DIR, 'targets.json')
    if not os.path.exists(local_path):
        return

    with open(local_path, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }

    if _github_sha_cache is None:
        _get_github_sha()

    payload = {
        "message": f"update targets {datetime.now().strftime('%H:%M:%S')}",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if _github_sha_cache:
        payload["sha"] = _github_sha_cache

    try:
        r = requests.put(url, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            _github_sha_cache = r.json().get("content", {}).get("sha")
            print(f"✅ GitHub: targets.json оновлено ({len(active_targets)} цілей)")
        else:
            print(f"⚠️  GitHub push error {r.status_code}: {r.text[:200]}")
            if r.status_code == 409:
                _github_sha_cache = None
    except Exception as e:
        print(f"⚠️  GitHub push exception: {e}")
        notify_admins(f"помилка push у GitHub: {e}")


def push_to_github_async():
    threading.Thread(target=push_to_github, daemon=True).start()


# =============================================
# --- ЗБЕРЕЖЕННЯ ЛОКАЛЬНО + PUSH ---
# =============================================
def save_targets():
    path = os.path.join(BASE_DIR, 'targets.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(active_targets, f, ensure_ascii=False, indent=4)
    push_to_github_async()


# =============================================
# --- ОЧИЩЕННЯ ЗАСТАРІЛИХ ЦІЛЕЙ ---
# =============================================
async def cleaner():
    global active_targets
    while True:
        now = datetime.now()
        before = len(active_targets)
        active_targets = [
            t for t in active_targets
            if datetime.fromisoformat(t['expire_at']) > now
        ]
        if len(active_targets) != before:
            save_targets()
            print(f"🧹 Видалено {before - len(active_targets)} застарілих цілей")
        await asyncio.sleep(60)


# =============================================
# --- TELEGRAM КЛІЄНТ (кілька джерел) ---
# =============================================
client = TelegramClient('bot_session', API_ID, API_HASH)


@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = event.raw_text.lower()
    now = datetime.now()
    source_chat = getattr(event.chat, 'username', None) or str(event.chat_id)

    detected_type = "missile"
    for t_name, keywords in TARGET_TYPES.items():
        if any(word in text for word in keywords):
            detected_type = t_name
            break

    for city, data in GEO_DATA.items():
        if city in text:
            is_duplicate = any(
                t['label'].startswith(city.capitalize()) and t['type'] == detected_type
                for t in active_targets
            )
            if not is_duplicate:
                target = {
                    "id":        f"{source_chat}_{event.id}",
                    "type":      detected_type,
                    "lat":       data[0],
                    "lng":       data[1],
                    "lon":       data[1],
                    "label":     f"{city.capitalize()} ({data[2]})",
                    "source":    source_chat,
                    "time":      now.strftime("%H:%M"),
                    "expire_at": (now + timedelta(minutes=40)).isoformat()
                }
                active_targets.append(target)
                save_targets()
                print(f"🎯 [{source_chat}] {detected_type.upper()} → {city.capitalize()} | GitHub ↑")
            break


# =============================================
# --- ЗАПУСК ---
# =============================================
async def main():
    print("🔗 Підключення до GitHub...")
    _get_github_sha()

    print("🤖 Система моніторингу Харківщини активована!")
    print(f"📡 Слухаємо канали: {', '.join(SOURCE_CHANNELS)}")
    print(f"🐙 GitHub: https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE}")

    asyncio.create_task(cleaner())
    await client.start(bot_token=os.environ.get('PARSER_BOT_TOKEN') or BOT_TOKEN)
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        notify_admins(f"парсер впав: {e}")
        raise
