# Monitor Kharkiv — обновлённый проект

## Что изменилось
- **parser.py** — теперь слушает несколько каналов через `SOURCE_CHANNELS` (env), никаких токенов в коде.
- **bot.py** (новый) — бот на aiogram: Menu Button + inline-кнопка открывают карту как Telegram Mini App.
- **index.html** — исправлен сломанный дублирующийся скрипт (там был реальный синтаксис-баг), добавлен Telegram WebApp SDK.
- **requirements.txt** — добавлен aiogram.
- **.gitignore** — теперь реально исключает `.env` и файлы сессий Telethon.
- Из архива удалены `parser.py.bak`, `deepseek_html_*.bak` и `bot_session.session*` — в них были твои реальные `API_HASH`, `BOT_TOKEN` и GitHub PAT в открытом виде, и живая Telegram-сессия. **Их нужно перевыпустить/отозвать, если этот проект хоть раз попадал в публичный репозиторий.**

## ⚠️ Обязательно сделать прямо сейчас
1. Перевыпусти `API_HASH` на my.telegram.org (или как минимум проверь, не утекал ли он).
2. Отзови старый `BOT_TOKEN` через @BotFather → `/revoke`, получи новый.
3. Удали/отзови GitHub Personal Access Token, который был в parser.py.bak (Settings → Developer settings → PAT).

## GitHub Secrets (Settings → Secrets and variables → Actions)
- `API_ID`, `API_HASH` — с my.telegram.org
- `SOURCE_CHANNELS` — например `monitorkh1654,channel2,channel3`
- `BOT_TOKEN` — токен бота (используется и парсером, и для Mini App)
- `ADMIN_IDS` — (опционально) твой user_id для алертов о падении парсера
- `GITHUB_TOKEN` — подставляется автоматически Actions, вручную не нужен

Встроенный `secrets.GITHUB_TOKEN` уже имеет право на запись в `targets.json`, т.к. в workflow добавлено `permissions: contents: write`.

## Локальный запуск бота (bot.py)
GitHub Actions не подходит для постоянно работающего бота (это cron, а не долгоживущий процесс).
Бота нужно держать где-то отдельно — на своём сервере / Railway / PythonAnywhere / VPS:

```bash
pip install -r requirements.txt
export BOT_TOKEN="..."
export WEBAPP_URL="https://<user>.github.io/<repo>/"
python bot.py
```

После этого у пользователей в чате с ботом появится:
- кнопка меню "Карта загроз" рядом с полем ввода,
- и кнопка "🗺 Открыть карту загроз" под `/start`.

Обе открывают `index.html` как Telegram Mini App (внутри Telegram, с автоматической темой оформления).

## Локальный запуск парсера (parser.py)
```bash
export API_ID="..."
export API_HASH="..."
export SOURCE_CHANNELS="monitorkh1654,channel2"
export BOT_TOKEN="..."
export GITHUB_TOKEN="..."           # только для локального запуска
export GITHUB_REPOSITORY="user/repo" # только для локального запуска
python parser.py
```

При первом запуске Telethon создаст `bot_session.session` — этот файл никогда не коммить (уже в `.gitignore`).
