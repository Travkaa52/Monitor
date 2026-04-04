#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser Bot - автоматический парсинг целей из каналов
Читает сообщения из указанных каналов, извлекает координаты и типы целей
"""

import os
import re
import json
import asyncio
import uuid
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from telethon import TelegramClient, events
from telethon.tl.types import Message

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# ID администраторов (для команд)
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',') if i.strip()]

# КАНАЛЫ ДЛЯ ПАРСИНГА (можно указать username или ID)
# Пример: SOURCE_CHANNELS = "@skykh_info", "-1001234567890", "https://t.me/channel"
SOURCE_CHANNELS = os.environ.get('SOURCE_CHANNELS', '').split(',')

# Файлы
DATA_FILE = 'targets.json'
LOG_FILE = 'bot.log'
STATE_FILE = 'last_message_state.json'  # Для сохранения последнего обработанного сообщения

# GitHub настройки
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '')

# ==================== НАСТРОЙКИ ПАРСИНГА ====================

# Типы целей и их ключевые слова (для автоопределения)
TARGET_KEYWORDS = {
    'shahed': ['шахед', 'shahed', 'shahid', 'мопед', 'geran'],
    'gerbera': ['гербера', 'gerbera'],
    'orlan': ['орлан', 'orlan', 'развед', 'разведчик'],
    'molniya': ['молния', 'molniya', 'молнія'],
    'lancet': ['ланцет', 'lancet'],
    'kab': ['каб', 'kab', 'авиабомба', 'умпк'],
    'rocket': ['ракета', 'rocket', 'крылатая', 'калибр', 'искандер'],
    'rszo': ['рсзо', 'rszo', 'град', 'смерч', 'ураган', 'торнадо'],
    'balistika': ['баллистика', 'balistika', 'баллистическая'],
    'explosion': ['взрыв', 'explosion', 'прилет', 'удар', 'попадание']
}

# Регулярные выражения для поиска координат
# Форматы: 49.9935,36.2304 или 49.9935 36.2304 или 49°59'36.6"N 36°13'49.4"E
COORD_PATTERNS = [
    # Десятичные: 49.9935, 36.2304
    r'(\d{1,2}\.\d{4,})\s*[,\s]\s*(\d{1,3}\.\d{4,})',
    r'(\d{1,2}\.\d+)[,\s]+(\d{1,3}\.\d+)',
    # Градусы: 49°59'36.6"N 36°13'49.4"E
    r'(\d{1,2})°(\d{1,2})\'([\d\.]+)"[NS]\s+(\d{1,3})°(\d{1,2})\'([\d\.]+)"[EW]',
]

# Поиск направления/курса
BEARING_PATTERNS = [
    r'курс[:\s]+(\d{1,3})°',
    r'направление[:\s]+(\d{1,3})°',
    r'bearing[:\s]+(\d{1,3})',
    r'азимут[:\s]+(\d{1,3})',
]

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def log_message(msg: str):
    """Запись в лог"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_msg = f'[{timestamp}] {msg}'
    print(full_msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(full_msg + '\n')
    except:
        pass


def git_push():
    """Автоматический пуш изменений на GitHub"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    
    try:
        repo_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(['git', 'config', '--global', 'user.email', 'bot@github.com'], capture_output=True)
        subprocess.run(['git', 'config', '--global', 'user.name', 'GitHub Actions Bot'], capture_output=True)
        subprocess.run(['git', 'add', DATA_FILE, LOG_FILE, STATE_FILE], capture_output=True)
        
        commit_msg = f"Update targets {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result = subprocess.run(['git', 'commit', '-m', commit_msg], capture_output=True)
        
        if result.returncode == 0:
            subprocess.run(['git', 'push', repo_url, 'HEAD:main'], capture_output=True)
            log_message("✅ Изменения запушены на GitHub")
            return True
    except Exception as e:
        log_message(f"❌ Ошибка git push: {e}")
    return False


def load_state() -> Dict:
    """Загрузка состояния последнего обработанного сообщения"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_state(state: Dict):
    """Сохранение состояния"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_message(f"Ошибка сохранения состояния: {e}")


def load_targets() -> Dict[str, Any]:
    """Загрузка целей из JSON"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'items' not in data:
                    data = {'items': []}
                return data
        except:
            return {'items': []}
    return {'items': []}


def save_targets(data: Dict[str, Any]) -> bool:
    """Сохранение целей"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        git_push()
        return True
    except Exception as e:
        log_message(f"Ошибка сохранения: {e}")
        return False


def parse_coordinates(text: str) -> Optional[Tuple[float, float]]:
    """Извлечение координат из текста"""
    text = text.replace(',', '.').replace(' ', ' ')
    
    # Поиск десятичных координат
    for pattern in COORD_PATTERNS[:2]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                lat = float(match.group(1))
                lon = float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return (lat, lon)
            except:
                pass
    
    # Поиск градусного формата
    match = re.search(COORD_PATTERNS[2], text, re.IGNORECASE)
    if match:
        try:
            lat_deg = int(match.group(1))
            lat_min = int(match.group(2))
            lat_sec = float(match.group(3))
            lat = lat_deg + lat_min/60 + lat_sec/3600
            
            lon_deg = int(match.group(4))
            lon_min = int(match.group(5))
            lon_sec = float(match.group(6))
            lon = lon_deg + lon_min/60 + lon_sec/3600
            
            return (lat, lon)
        except:
            pass
    
    return None


def parse_bearing(text: str) -> Optional[int]:
    """Извлечение направления/курса из текста"""
    for pattern in BEARING_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                bearing = int(match.group(1))
                if 0 <= bearing <= 360:
                    return bearing
            except:
                pass
    return None


def detect_target_type(text: str) -> str:
    """Автоопределение типа цели по ключевым словам"""
    text_lower = text.lower()
    
    for target_type, keywords in TARGET_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return target_type
    
    return 'shahed'  # тип по умолчанию


def parse_target_from_message(message_text: str, message_id: int, channel_name: str) -> Optional[Dict]:
    """Парсинг цели из текста сообщения"""
    if not message_text:
        return None
    
    # Поиск координат
    coords = parse_coordinates(message_text)
    if not coords:
        return None
    
    lat, lon = coords
    
    # Определение типа цели
    target_type = detect_target_type(message_text)
    
    # Поиск направления
    bearing = parse_bearing(message_text)
    
    # Формирование описания
    description = f"Источник: {channel_name} | ID сообщения: {message_id}"
    
    # Обрезаем описание, если слишком длинное
    if len(message_text) > 200:
        description += f"\nТекст: {message_text[:200]}..."
    else:
        description += f"\nТекст: {message_text}"
    
    target = {
        "id": str(uuid.uuid4())[:8],
        "type": target_type,
        "lat": lat,
        "lon": lon,
        "bearing": bearing if bearing else 0,
        "description": description,
        "source_channel": channel_name,
        "source_message_id": message_id,
        "created_at": datetime.now().isoformat(),
        "timestamp": int(datetime.now().timestamp())
    }
    
    return target


def add_target(target: Dict) -> bool:
    """Добавление цели в базу"""
    data = load_targets()
    
    # Проверка на дубликаты (по координатам и источнику за последние 5 минут)
    current_time = datetime.now().timestamp()
    for existing in data['items']:
        if (existing.get('lat') == target['lat'] and 
            existing.get('lon') == target['lon'] and
            existing.get('source_channel') == target.get('source_channel') and
            current_time - existing.get('timestamp', 0) < 300):  # 5 минут
            log_message(f"Пропущен дубликат: {target['lat']}, {target['lon']}")
            return False
    
    data['items'].append(target)
    
    # Ограничиваем количество целей (оставляем последние 500)
    if len(data['items']) > 500:
        data['items'] = data['items'][-500:]
    
    if save_targets(data):
        log_message(f"✅ Добавлена цель: {target['type']} | {target['lat']}, {target['lon']} | канал: {target['source_channel']}")
        return True
    
    return False


# ==================== ОСНОВНАЯ ЛОГИКА ПАРСЕРА ====================

async def parse_existing_messages(client: TelegramClient):
    """Парсинг существующих сообщений из каналов (при первом запуске)"""
    state = load_state()
    
    for channel in SOURCE_CHANNELS:
        channel = channel.strip()
        if not channel:
            continue
        
        try:
            log_message(f"📥 Парсинг истории канала: {channel}")
            
            # Получаем последнее обработанное сообщение для этого канала
            last_msg_id = state.get(channel, 0)
            
            # Получаем сообщения (последние 100, начиная с last_msg_id)
            async for message in client.iter_messages(channel, limit=100, min_id=last_msg_id):
                if not message or not message.text:
                    continue
                
                # Парсим цель из сообщения
                target = parse_target_from_message(
                    message.text, 
                    message.id, 
                    channel
                )
                
                if target:
                    add_target(target)
                    
                    # Обновляем состояние
                    if message.id > state.get(channel, 0):
                        state[channel] = message.id
                        save_state(state)
                
                # Небольшая задержка, чтобы не превысить лимиты
                await asyncio.sleep(0.5)
                
        except Exception as e:
            log_message(f"❌ Ошибка при парсинге канала {channel}: {e}")


async def listen_for_new_messages(client: TelegramClient):
    """Прослушивание новых сообщений в реальном времени"""
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNELS))
    async def message_handler(event):
        message = event.message
        channel = await event.get_chat()
        channel_name = channel.username or str(channel.id)
        
        if not message or not message.text:
            return
        
        log_message(f"📨 Новое сообщение из {channel_name}: {message.text[:100]}...")
        
        # Парсим цель
        target = parse_target_from_message(message.text, message.id, channel_name)
        
        if target:
            add_target(target)
            
            # Обновляем состояние
            state = load_state()
            if message.id > state.get(channel_name, 0):
                state[channel_name] = message.id
                save_state(state)
            
            # Отправляем уведомление админам (опционально)
            for admin_id in ADMIN_IDS:
                try:
                    await client.send_message(
                        admin_id,
                        f"🎯 **Новая цель!**\n"
                        f"Тип: {target['type']}\n"
                        f"Координаты: {target['lat']}, {target['lon']}\n"
                        f"Источник: {channel_name}"
                    )
                except:
                    pass


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def handle_start(event):
    text = """🤖 **Sky Kharkiv Parser Bot**

Бот автоматически парсит цели из Telegram-каналов и добавляет их на карту.

**Команды:**
/start - помощь
/stats - статистика
/status - статус парсера
/clear - очистить все цели
"""
    await event.respond(text, parse_mode='markdown')


async def handle_stats(event):
    data = load_targets()
    items = data.get('items', [])
    
    if not items:
        await event.respond("📊 Нет активных целей")
        return
    
    # Статистика по типам
    types = {}
    for item in items[-100:]:  # последние 100
        t = item.get('type', 'unknown')
        types[t] = types.get(t, 0) + 1
    
    type_lines = '\n'.join([f"• {t}: {c}" for t, c in sorted(types.items(), key=lambda x: -x[1])])
    
    text = f"""
📊 **Статистика парсера**

**Всего целей в базе:** {len(items)}
**За последние 100:** {sum(types.values())}

**По типам:**
{type_lines}

🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}
"""
    await event.respond(text, parse_mode='markdown')


async def handle_status(event):
    """Статус парсера - какие каналы отслеживаются"""
    text = f"""
🔍 **Статус парсера**

**Отслеживаемые каналы:**
{chr(10).join([f'• {ch}' for ch in SOURCE_CHANNELS if ch])}

**Последние обработанные сообщения:**
"""
    state = load_state()
    for channel, msg_id in state.items():
        text += f"\n• {channel}: сообщение {msg_id}"
    
    await event.respond(text, parse_mode='markdown')


async def handle_clear(event):
    if not is_admin(event.sender_id):
        await event.respond("⛔ Доступ запрещен")
        return
    
    if save_targets({'items': []}):
        await event.respond("✅ База целей очищена")
    else:
        await event.respond("❌ Ошибка")


async def handle_force_parse(event):
    """Принудительный парсинг истории"""
    if not is_admin(event.sender_id):
        await event.respond("⛔ Доступ запрещен")
        return
    
    await event.respond("🔄 Начинаю принудительный парсинг истории...")
    await parse_existing_messages(event.client)
    await event.respond("✅ Парсинг завершен")


# ==================== MAIN ====================

async def main():
    """Запуск бота-парсера"""
    
    # Проверка конфигурации
    if not API_ID or not API_HASH:
        log_message("❌ Ошибка: не заданы API_ID или API_HASH")
        return
    
    if not SOURCE_CHANNELS or SOURCE_CHANNELS == ['']:
        log_message("⚠️ ВНИМАНИЕ: не заданы SOURCE_CHANNELS! Парсинг не будет работать.")
    
    # Создаем клиента (user account для парсинга каналов)
    client = TelegramClient('parser_session', API_ID, API_HASH)
    
    # Регистрируем обработчики команд
    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(e): await handle_start(e)
    
    @client.on(events.NewMessage(pattern='/stats'))
    async def stats_handler(e): await handle_stats(e)
    
    @client.on(events.NewMessage(pattern='/status'))
    async def status_handler(e): await handle_status(e)
    
    @client.on(events.NewMessage(pattern='/clear'))
    async def clear_handler(e): await handle_clear(e)
    
    @client.on(events.NewMessage(pattern='/force'))
    async def force_handler(e): await handle_force_parse(e)
    
    # Запуск
    await client.start()
    
    log_message(f"✅ Бот-парсер запущен!")
    log_message(f"📡 Отслеживаемые каналы: {SOURCE_CHANNELS}")
    log_message(f"👥 Админы: {ADMIN_IDS}")
    
    # Отправляем уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await client.send_message(
                admin_id,
                f"🤖 **Парсер запущен!**\n\n"
                f"📡 Отслеживаемые каналы:\n{chr(10).join([f'• {ch}' for ch in SOURCE_CHANNELS if ch])}\n\n"
                f"Команды: /stats, /status, /force"
            )
        except:
            pass
    
    # При первом запуске парсим историю
    await parse_existing_messages(client)
    
    # Запускаем прослушивание новых сообщений
    await listen_for_new_messages(client)
    
    # Держим бота активным
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
