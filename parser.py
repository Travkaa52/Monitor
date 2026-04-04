#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser Bot для мониторинга Харьковской области
Парсит сообщения канала monitor 1654, преобразует названия населенных пунктов в координаты
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

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# Каналы для парсинга
SOURCE_CHANNELS = os.environ.get('SOURCE_CHANNELS', '@monitor1654').split(',')

# ID админов
ADMIN_IDS = [int(i.strip()) for i in os.environ.get('ADMIN_IDS', '').split(',') if i.strip()]

# Файлы
DATA_FILE = 'targets.json'
LOG_FILE = 'bot.log'
STATE_FILE = 'last_message_state.json'
LOCATIONS_FILE = 'locations.json'  # База населенных пунктов с координатами

# GitHub настройки
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '')

# ==================== БАЗА НАСЕЛЕННЫХ ПУНКТОВ ХАРЬКОВСКОЙ ОБЛАСТИ ====================
# Координаты населенных пунктов (широта, долгота)
LOCATIONS_DB = {
    # Харьков и пригороды
    "харків": (49.9935, 36.2304),
    "харьков": (49.9935, 36.2304),
    "центр": (49.9935, 36.2304),
    "місто": (49.9935, 36.2304),
    "город": (49.9935, 36.2304),
    
    # Северное направление
    "липці": (50.2031, 36.4147),
    "липцы": (50.2031, 36.4147),
    "циркуни": (50.0058, 36.4164),
    "циркуны": (50.0058, 36.4164),
    "руська лозова": (50.1369, 36.3036),
    "русская лозовая": (50.1369, 36.3036),
    "прудянка": (50.2278, 36.1686),
    "слатине": (50.2197, 36.1528),
    "слатино": (50.2197, 36.1528),
    "дергачі": (50.1142, 36.1208),
    "дергачи": (50.1142, 36.1208),
    "козача лопань": (50.3369, 36.1711),
    "казачья лопань": (50.3369, 36.1711),
    "зупинка": (50.2031, 36.4147),
    
    # Северо-восточное
    "велика данилівка": (50.0747, 36.3297),
    "большая даниловка": (50.0747, 36.3297),
    "мала данилівка": (50.0558, 36.3331),
    "малая даниловка": (50.0558, 36.3331),
    "жуковського": (50.0747, 36.3297),
    "жуковского": (50.0747, 36.3297),
    
    # Восточное направление
    "чугунів": (49.8358, 36.6886),
    "чугуев": (49.8358, 36.6886),
    "чугуїв": (49.8358, 36.6886),
    "печеніги": (49.8703, 36.9358),
    "печенеги": (49.8703, 36.9358),
    "кочеток": (49.8747, 36.7386),
    "момотове": (50.0042, 36.4758),
    "момотово": (50.0042, 36.4758),
    "північна салтівка": (50.0347, 36.3964),
    "северная салтовка": (50.0347, 36.3964),
    "салтівка": (50.0347, 36.3964),
    "салтовка": (50.0347, 36.3964),
    
    # Юго-восточное
    "безлюдівка": (49.8706, 36.2767),
    "безлюдовка": (49.8706, 36.2767),
    "докучаєвське": (49.8853, 36.2664),
    "докучаевское": (49.8853, 36.2664),
    "хроли": (49.9208, 36.2411),
    "рогань": (49.9053, 36.4806),
    "рогань": (49.9053, 36.4806),
    
    # Южное направление
    "пісочин": (49.9564, 36.1136),
    "песочин": (49.9564, 36.1136),
    "буди": (49.8942, 36.0181),
    "люботин": (49.9486, 35.9258),
    "люботин": (49.9486, 35.9258),
    "південне": (49.8833, 36.0667),
    "южное": (49.8833, 36.0667),
    "ков'яги": (49.8347, 35.8875),
    "ковяги": (49.8347, 35.8875),
    
    # Западное направление
    "веселе": (50.0139, 36.1167),
    "шестакове": (50.0158, 36.1486),
    "шестаково": (50.0158, 36.1486),
    "кутузівка": (50.0042, 36.1758),
    "кутузовка": (50.0042, 36.1758),
    "золочів": (50.2803, 35.9758),
    "золочев": (50.2803, 35.9758),
    "вільшани": (50.0561, 35.8917),
    "ольшаны": (50.0561, 35.8917),
    "старий мерчик": (49.9764, 35.7556),
    "старый мерчик": (49.9764, 35.7556),
    "богодухів": (50.1647, 35.5272),
    "богодухов": (50.1647, 35.5272),
    "краснокутськ": (50.0558, 35.1575),
    "краснокутск": (50.0558, 35.1575),
    
    # Другие важные точки
    "аеропорт": (49.9247, 36.2867),
    "аэропорт": (49.9247, 36.2867),
    "питомник": (50.0331, 36.3264),
    "лісне": (50.0497, 36.3694),
    "лесное": (50.0497, 36.3694),
    "кам'яна яруга": (50.2769, 36.3586),
    "каменная яруга": (50.2769, 36.3586),
    "тетлега": (50.1406, 36.4369),
    "полтавщина": (49.5894, 34.5514),
    "полтавская": (49.5894, 34.5514),
    "сумщина": (50.9072, 34.7989),
    "бельгород": (50.5975, 36.5858),
    "белгород": (50.5975, 36.5858),
    "оскіл": (49.1706, 37.4092),
    "изюм": (49.2125, 37.2628),
    "ізюм": (49.2125, 37.2628),
}

# Типы целей по ключевым словам
TARGET_KEYWORDS = {
    'shahed': ['шахед', 'шахедів', 'шахедом', 'shahed', 'байрактар'],
    'rocket': ['ракета', 'ракет', 'крилата', 'крилату', 'калібр'],
    'kab': ['каб', 'авіабомба', 'умкп'],
    'molniya': ['молнія', 'молния'],
    'gerbera': ['гербера'],
    'orlan': ['орлан', 'розвідник'],
    'rszo': ['рсзо', 'град', 'смерч'],
    'explosion': ['приліт', 'вибух', 'впав', 'удар'],
    'balistika': ['балістика', 'баллистика', 'іскандер'],
}

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
    """Автоматический пуш на GitHub"""
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
            log_message("✅ Изменения запушены")
            return True
    except Exception as e:
        log_message(f"❌ Ошибка git push: {e}")
    return False


def load_state() -> Dict:
    """Загрузка состояния"""
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
    except:
        pass


def load_targets() -> Dict:
    """Загрузка целей"""
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


def save_targets(data: Dict) -> bool:
    """Сохранение целей"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        git_push()
        return True
    except Exception as e:
        log_message(f"Ошибка сохранения: {e}")
        return False


def extract_location(text: str) -> Optional[Tuple[str, Tuple[float, float]]]:
    """Извлечение названия населенного пункта и его координат"""
    text_lower = text.lower()
    
    # Поиск всех известных локаций в тексте
    found_locations = []
    for location_name, coords in LOCATIONS_DB.items():
        if location_name in text_lower:
            found_locations.append((location_name, coords))
    
    if not found_locations:
        return None
    
    # Возвращаем первую найденную локацию (самую длинную, наиболее точную)
    found_locations.sort(key=lambda x: len(x[0]), reverse=True)
    return found_locations[0]


def detect_target_type(text: str) -> str:
    """Определение типа цели"""
    text_lower = text.lower()
    
    for target_type, keywords in TARGET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return target_type
    
    return 'shahed'  # по умолчанию


def extract_bearing(text: str) -> Optional[int]:
    """Извлечение направления/курса"""
    patterns = [
        r'курс[:\s]+(\d{1,3})',
        r'направление[:\s]+(\d{1,3})',
        r'рух[:\s]+на\s+(\w+)',  # направление движения
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except:
                pass
    return None


def parse_message(message_text: str, message_id: int, channel_name: str) -> Optional[List[Dict]]:
    """
    Парсинг сообщения и извлечение целей
    Возвращает список целей (одно сообщение может содержать несколько целей)
    """
    if not message_text:
        return None
    
    targets = []
    
    # 1. Проверяем на формат "▪️1 на Название⚠️"
    bullet_pattern = r'▪️\d+\s+на\s+([А-Яа-яІіЇїЄє\'\-/\s]+?)[⚠️❗️]'
    bullet_matches = re.findall(bullet_pattern, message_text)
    
    if bullet_matches:
        for location_name in bullet_matches:
            location_name = location_name.strip().lower()
            # Ищем координаты для этого названия
            for loc_name, coords in LOCATIONS_DB.items():
                if loc_name in location_name or location_name in loc_name:
                    target_type = detect_target_type(message_text)
                    target = {
                        "id": str(uuid.uuid4())[:8],
                        "type": target_type,
                        "lat": coords[0],
                        "lon": coords[1],
                        "bearing": 0,
                        "description": f"Источник: {channel_name} | {message_text[:150]}",
                        "location_name": loc_name,
                        "source_channel": channel_name,
                        "source_message_id": message_id,
                        "created_at": datetime.now().isoformat(),
                        "timestamp": int(datetime.now().timestamp())
                    }
                    targets.append(target)
                    break
    
    # 2. Если нет маркированного списка, ищем обычное упоминание
    if not targets:
        location_info = extract_location(message_text)
        if location_info:
            location_name, coords = location_info
            target_type = detect_target_type(message_text)
            bearing = extract_bearing(message_text)
            
            target = {
                "id": str(uuid.uuid4())[:8],
                "type": target_type,
                "lat": coords[0],
                "lon": coords[1],
                "bearing": bearing if bearing else 0,
                "description": f"Источник: {channel_name} | {message_text[:200]}",
                "location_name": location_name,
                "source_channel": channel_name,
                "source_message_id": message_id,
                "created_at": datetime.now().isoformat(),
                "timestamp": int(datetime.now().timestamp())
            }
            targets.append(target)
    
    # 3. Специальная обработка для сообщений типа "впал", "не фіксується" - удаляем цели
    if 'впав' in message_text or 'не фіксується' in message_text or 'більше не фіксується' in message_text:
        # Возвращаем специальный маркер для удаления последней цели
        return [{"action": "clear_last", "source_channel": channel_name}]
    
    # 4. Обработка отбоя
    if 'відбій' in message_text:
        return [{"action": "clear_all", "source_channel": channel_name}]
    
    return targets if targets else None


def add_target(target: Dict) -> bool:
    """Добавление цели"""
    data = load_targets()
    
    # Проверка на дубликаты (та же локация за последние 10 минут)
    current_time = datetime.now().timestamp()
    for existing in data['items'][-50:]:
        if (existing.get('location_name') == target.get('location_name') and
            current_time - existing.get('timestamp', 0) < 600):
            log_message(f"Пропущен дубликат локации: {target.get('location_name')}")
            return False
    
    data['items'].append(target)
    
    # Ограничиваем количество целей (последние 200)
    if len(data['items']) > 200:
        data['items'] = data['items'][-200:]
    
    if save_targets(data):
        log_message(f"✅ Добавлена цель: {target['type']} | {target.get('location_name', '?')} | {target['lat']}, {target['lon']}")
        return True
    return False


def clear_last_target(channel_name: str) -> bool:
    """Удаление последней цели из указанного канала"""
    data = load_targets()
    
    # Находим последнюю цель из этого канала
    for i in range(len(data['items']) - 1, -1, -1):
        if data['items'][i].get('source_channel') == channel_name:
            removed = data['items'].pop(i)
            if save_targets(data):
                log_message(f"🗑️ Удалена цель: {removed.get('location_name', '?')} ({channel_name})")
                return True
            break
    return False


def clear_all_targets() -> bool:
    """Очистка всех целей"""
    if save_targets({'items': []}):
        log_message("🗑️ Все цели удалены")
        return True
    return False


# ==================== ОСНОВНАЯ ЛОГИКА ====================

async def parse_existing_messages(client: TelegramClient):
    """Парсинг истории сообщений"""
    state = load_state()
    
    for channel in SOURCE_CHANNELS:
        channel = channel.strip()
        if not channel:
            continue
        
        try:
            log_message(f"📥 Парсинг истории: {channel}")
            last_msg_id = state.get(channel, 0)
            
            async for message in client.iter_messages(channel, limit=100, min_id=last_msg_id):
                if not message or not message.text:
                    continue
                
                targets = parse_message(message.text, message.id, channel)
                
                if targets:
                    for target in targets:
                        if target.get('action') == 'clear_last':
                            clear_last_target(channel)
                        elif target.get('action') == 'clear_all':
                            clear_all_targets()
                        else:
                            add_target(target)
                    
                    if message.id > state.get(channel, 0):
                        state[channel] = message.id
                        save_state(state)
                
                await asyncio.sleep(0.3)
                
        except Exception as e:
            log_message(f"❌ Ошибка парсинга {channel}: {e}")


async def listen_for_new_messages(client: TelegramClient):
    """Прослушивание новых сообщений"""
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNELS))
    async def message_handler(event):
        message = event.message
        channel = await event.get_chat()
        channel_name = channel.username or str(channel.id)
        
        if not message or not message.text:
            return
        
        log_message(f"📨 Новое сообщение: {message.text[:100]}...")
        
        targets = parse_message(message.text, message.id, channel_name)
        
        if targets:
            for target in targets:
                if target.get('action') == 'clear_last':
                    clear_last_target(channel_name)
                elif target.get('action') == 'clear_all':
                    clear_all_targets()
                else:
                    add_target(target)
            
            # Обновляем состояние
            state = load_state()
            if message.id > state.get(channel_name, 0):
                state[channel_name] = message.id
                save_state(state)


# ==================== КОМАНДЫ ====================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def handle_start(event):
    text = """🤖 **Sky Kharkiv Parser Bot**

Бот парсит сообщения канала @monitor1654 и добавляет цели на карту.

**Команды:**
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
    
    types = {}
    for item in items[-50:]:
        t = item.get('type', 'unknown')
        types[t] = types.get(t, 0) + 1
    
    type_lines = '\n'.join([f"• {t}: {c}" for t, c in types.items()])
    
    text = f"""
📊 **Статистика**

**Всего целей:** {len(items)}
**Последние 50:** {sum(types.values())}

**По типам:**
{type_lines}

🕐 {datetime.now().strftime('%H:%M:%S')}
"""
    await event.respond(text, parse_mode='markdown')


async def handle_status(event):
    text = f"""
🔍 **Статус парсера**

**Каналы:** {', '.join(SOURCE_CHANNELS)}

**Последние обработанные сообщения:**
"""
    state = load_state()
    for ch, msg_id in state.items():
        text += f"\n• {ch}: {msg_id}"
    
    await event.respond(text, parse_mode='markdown')


async def handle_clear(event):
    if not is_admin(event.sender_id):
        await event.respond("⛔ Доступ запрещен")
        return
    
    if clear_all_targets():
        await event.respond("✅ Все цели удалены")
    else:
        await event.respond("❌ Ошибка")


# ==================== MAIN ====================

async def main():
    """Запуск парсера"""
    
    if not API_ID or not API_HASH:
        log_message("❌ Ошибка: не заданы API_ID или API_HASH")
        return
    
    client = TelegramClient('parser_session', API_ID, API_HASH)
    
    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(e): await handle_start(e)
    
    @client.on(events.NewMessage(pattern='/stats'))
    async def stats_handler(e): await handle_stats(e)
    
    @client.on(events.NewMessage(pattern='/status'))
    async def status_handler(e): await handle_status(e)
    
    @client.on(events.NewMessage(pattern='/clear'))
    async def clear_handler(e): await handle_clear(e)
    
    await client.start()
    
    log_message(f"✅ Парсер запущен!")
    log_message(f"📡 Каналы: {SOURCE_CHANNELS}")
    
    # Парсим историю
    await parse_existing_messages(client)
    
    # Слушаем новые сообщения
    await listen_for_new_messages(client)
    
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
