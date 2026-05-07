import asyncio
import json
import os
import base64
import threading
import requests
from datetime import datetime, timedelta
from telethon import TelegramClient, events

# =============================================
# --- НАЛАШТУВАННЯ TELEGRAM ---
# =============================================
API_ID = '25635427'
API_HASH = 'e2f99fb35400e6628c88ffd388308598'
BOT_TOKEN = '8377487187:AAFEd-mRZjJaJ_xC0931IkFlLyr09Lwnnwo'
CHANNEL_ID = 'monitorkh1654'

# =============================================
# --- НАЛАШТУВАННЯ GITHUB ---
# =============================================
# 1. Створіть Personal Access Token на: https://github.com/settings/tokens
#    Права: repo → contents (read & write)
# 2. Замініть значення нижче на ваші

GITHUB_TOKEN = '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'          # GitHub Personal Access Token
GITHUB_OWNER = 'Travkaa52'                  # Ваш GitHub username або org
GITHUB_REPO  = 'Monitor'             # Назва вашого репо (публічне!)
GITHUB_BRANCH = 'main'                         # Гілка (main або master)
GITHUB_FILE  = 'targets.json'                  # Шлях до файлу в репо

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
    # ХАРКІВ ТА ПЕРЕДМІСТЯ
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
    # ЧУГУЇВСЬКИЙ НАПРЯМОК
    "чугуїв":           [49.83, 36.68, "Чугуївський р-н"],
    "вовчанськ":        [50.28, 36.93, "Чугуївський р-н"],
    "старий салтів":    [50.08, 36.79, "Чугуївський р-н"],
    "малинівка":        [49.79, 36.72, "Чугуївський р-н"],
    "печеніги":         [49.86, 36.93, "Чугуївський р-н"],
    "білий колодязь":   [50.20, 37.14, "Чугуївський р-н"],
    "вовчанські хутори":[50.28, 37.03, "Чугуївський р-н"],
    # КУП'ЯНСЬКИЙ НАПРЯМОК
    "куп'янськ":        [49.70, 37.61, "Куп'янський р-н"],
    "вузлова":          [49.67, 37.64, "Куп'янськ-Вузловий"],
    "ківшарівка":       [49.62, 37.68, "Куп'янський р-н"],
    "шевченкове":       [49.70, 37.17, "Куп'янський р-н"],
    "дворічна":         [49.85, 37.67, "Куп'янський р-н"],
    "боросте":          [49.33, 37.62, "Борівська громада"],
    # ІЗЮМСЬКИЙ НАПРЯМОК
    "ізюм":             [49.19, 37.27, "Ізюмський р-н"],
    "балаклія":         [49.45, 36.85, "Ізюмський р-н"],
    "донець":           [49.46, 36.50, "Ізюмський р-н"],
    "савинці":          [49.40, 36.99, "Ізюмський р-н"],
    # БОГОДУХІВСЬКИЙ НАПРЯМОК
    "богодухів":        [50.16, 35.52, "Богодухівський р-н"],
    "золочів":          [50.28, 35.97, "Богодухівський р-н"],
    "валки":            [49.83, 35.61, "Богодухівський р-н"],
    "відродженівське":  [50.31, 35.84, "Золочівська громада"],
    # ПІВДЕНЬ ОБЛАСТІ
    "лозова":           [48.88, 36.31, "Лозівський р-н"],
    "первомайський":    [49.38, 36.21, "Лозівський р-н"],
    "красноград":       [49.37, 35.45, "Красноградський р-н"]
}

# =============================================
# --- ГЛОБАЛЬНИЙ СТАН ---
# =============================================
active_targets = []
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_github_sha_cache = None   # кешуємо SHA файлу щоб зайвий раз не робити GET


# =============================================
# --- GITHUB: PUSH targets.json ---
# =============================================
def _get_github_sha():
    """Отримати поточний SHA файлу з GitHub (потрібен для оновлення)."""
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
            _github_sha_cache = None  # файл ще не існує — буде створений
    except Exception as e:
        print(f"⚠️  GitHub GET error: {e}")
    return _github_sha_cache


def push_to_github():
    """Закодувати targets.json у base64 і запушити на GitHub через API."""
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

    # При першому пуші отримуємо SHA
    if _github_sha_cache is None:
        _get_github_sha()

    payload = {
        "message": f"update targets {datetime.now().strftime('%H:%M:%S')}",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if _github_sha_cache:
        payload["sha"] = _github_sha_cache   # потрібен для оновлення існуючого файлу

    try:
        r = requests.put(url, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            # Оновлюємо SHA з відповіді (щоб наступний пуш одразу мав правильний SHA)
            _github_sha_cache = r.json().get("content", {}).get("sha")
            print(f"✅ GitHub: targets.json оновлено ({len(active_targets)} цілей)")
        else:
            print(f"⚠️  GitHub push error {r.status_code}: {r.text[:200]}")
            # Якщо SHA застарів — скидаємо кеш і спробуємо наступного разу
            if r.status_code == 409:
                _github_sha_cache = None
    except Exception as e:
        print(f"⚠️  GitHub push exception: {e}")


def push_to_github_async():
    """Запускаємо push у окремому потоці щоб не блокувати event loop."""
    threading.Thread(target=push_to_github, daemon=True).start()


# =============================================
# --- ЗБЕРЕЖЕННЯ ЛОКАЛЬНО + PUSH ---
# =============================================
def save_targets():
    """Зберегти targets.json локально, потім запушити на GitHub."""
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
# --- TELEGRAM КЛІЄНТ ---
# =============================================
client = TelegramClient('bot_session', API_ID, API_HASH)


@client.on(events.NewMessage(chats=CHANNEL_ID))
async def handler(event):
    text = event.raw_text.lower()
    now = datetime.now()

    # Визначаємо ТИП загрози
    detected_type = "missile"
    for t_name, keywords in TARGET_TYPES.items():
        if any(word in text for word in keywords):
            detected_type = t_name
            break

    # Визначаємо МІСТО
    for city, data in GEO_DATA.items():
        if city in text:
            is_duplicate = any(
                t['label'].startswith(city.capitalize()) and t['type'] == detected_type
                for t in active_targets
            )
            if not is_duplicate:
                target = {
                    "id":        event.id,
                    "type":      detected_type,
                    "lat":       data[0],
                    "lng":       data[1],
                    "lon":       data[1],   # index.html використовує і lat/lng і lat/lon
                    "label":     f"{city.capitalize()} ({data[2]})",
                    "time":      now.strftime("%H:%M"),
                    "expire_at": (now + timedelta(minutes=40)).isoformat()
                }
                active_targets.append(target)
                save_targets()
                print(f"🎯 {detected_type.upper()} → {city.capitalize()} | GitHub ↑")
            break


# =============================================
# --- ЗАПУСК ---
# =============================================
async def main():
    # Ініціалізуємо SHA при старті
    print("🔗 Підключення до GitHub...")
    _get_github_sha()

    print("🤖 Система моніторингу Харківщини активована!")
    print(f"📡 Слухаємо канал: {CHANNEL_ID}")
    print(f"🐙 GitHub: https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE}")

    asyncio.create_task(cleaner())
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
