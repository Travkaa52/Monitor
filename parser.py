#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser - использует API ID/HASH (user account)
Читает каналы через API, не требует бота
"""

import os
import re
import json
import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from telethon import TelegramClient, events

# ==================== КОНФИГУРАЦИЯ ====================
# Обязательные переменные
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
PHONE_NUMBER = os.environ.get('PHONE_NUMBER', '')  # Номер телефона в формате +380...

# Каналы для парсинга (можно username или ID)
SOURCE_CHANNELS = os.environ.get('SOURCE_CHANNELS', '@monitor1654').split(',')

# Файлы
DATA_FILE = 'targets.json'
LOG_FILE = 'bot.log'
STATE_FILE = 'last_message_state.json'
SESSION_FILE = 'user_session.session'  # Сессия для сохранения авторизации

# ==================== БАЗА НАСЕЛЕННЫХ ПУНКТОВ ====================
LOCATIONS_DB = {
    "харків": (49.9935, 36.2304),
    "харьков": (49.9935, 36.2304),
    "центр": (49.9935, 36.2304),
    "місто": (49.9935, 36.2304),
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
    "велика данилівка": (50.0747, 36.3297),
    "большая даниловка": (50.0747, 36.3297),
    "мала данилівка": (50.0558, 36.3331),
    "малая даниловка": (50.0558, 36.3331),
    "чугуїв": (49.8358, 36.6886),
    "чугуев": (49.8358, 36.6886),
    "печеніги": (49.8703, 36.9358),
    "печенеги": (49.8703, 36.9358),
    "кочеток": (49.8747, 36.7386),
    "момотове": (50.0042, 36.4758),
    "момотово": (50.0042, 36.4758),
    "північна салтівка": (50.0347, 36.3964),
    "северная салтовка": (50.0347, 36.3964),
    "безлюдівка": (49.8706, 36.2767),
    "безлюдовка": (49.8706, 36.2767),
    "докучаєвське": (49.8853, 36.2664),
    "докучаевское": (49.8853, 36.2664),
    "пісочин": (49.9564, 36.1136),
    "песочин": (49.9564, 36.1136),
    "буди": (49.8942, 36.0181),
    "люботин": (49.9486, 35.9258),
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
    "аеропорт": (49.9247, 36.2867),
    "аэропорт": (49.9247, 36.2867),
    "питомник": (50.0331, 36.3264),
    "лісне": (50.0497, 36.3694),
    "лесное": (50.0497, 36.3694),
    "кам'яна яруга": (50.2769, 36.3586),
    "каменная яруга": (50.2769, 36.3586),
    "тетлега": (50.1406, 36.4369),
}

# Типы целей по ключевым словам
TARGET_KEYWORDS = {
    'shahed': ['шахед', 'шахедів', 'шахедом', 'shahed', 'реактивний шахед'],
    'rocket': ['ракета', 'ракет', 'крилата', 'крилату', 'калібр'],
    'kab': ['каб', 'каби', 'авіабомба', 'умкп'],
    'molniya': ['молнія', 'молния'],
    'gerbera': ['гербера'],
    'orlan': ['орлан', 'розвідник', 'розвідка'],
    'rszo': ['рсзо', 'град', 'смерч'],
    'explosion': ['приліт', 'вибух', 'впав', 'удар', 'попадання'],
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
        log_message(f"💾 Сохранено {len(data.get('items', []))} целей")
        return True
    except Exception as e:
        log_message(f"❌ Ошибка сохранения: {e}")
        return False


def extract_location(text: str) -> Optional[Tuple[str, Tuple[float, float]]]:
    """Извлечение локации из текста"""
    text_lower = text.lower()
    
    found = []
    for loc_name, coords in LOCATIONS_DB.items():
        if loc_name in text_lower:
            found.append((loc_name, coords))
    
    if not found:
        return None
    
    # Возвращаем самую длинную (наиболее точную)
    found.sort(key=lambda x: len(x[0]), reverse=True)
    return found[0]


def detect_target_type(text: str) -> str:
    """Определение типа цели"""
    text_lower = text.lower()
    
    for target_type, keywords in TARGET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return target_type
    
    return 'shahed'


def parse_message(message_text: str, message_id: int, channel_name: str) -> Optional[List[Dict]]:
    """Парсинг сообщения"""
    if not message_text:
        return None
    
    targets = []
    
    # Проверка на формат "▪️1 на Название⚠️"
    bullet_pattern = r'▪️\d+\s+на\s+([А-Яа-яІіЇїЄє\'\-/\s]+?)[⚠️❗️]'
    bullet_matches = re.findall(bullet_pattern, message_text)
    
    if bullet_matches:
        for location_name in bullet_matches:
            location_name = location_name.strip().lower()
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
                        "location": loc_name,
                        "source_channel": channel_name,
                        "source_message_id": message_id,
                        "created_at": datetime.now().isoformat(),
                        "timestamp": int(datetime.now().timestamp())
                    }
                    targets.append(target)
                    break
    
    # Обычное упоминание
    if not targets:
        loc_info = extract_location(message_text)
        if loc_info:
            loc_name, coords = loc_info
            target_type = detect_target_type(message_text)
            
            target = {
                "id": str(uuid.uuid4())[:8],
                "type": target_type,
                "lat": coords[0],
                "lon": coords[1],
                "bearing": 0,
                "description": f"Источник: {channel_name} | {message_text[:200]}",
                "location": loc_name,
                "source_channel": channel_name,
                "source_message_id": message_id,
                "created_at": datetime.now().isoformat(),
                "timestamp": int(datetime.now().timestamp())
            }
            targets.append(target)
    
    # Обработка "впал", "не фіксується" - удаляем последнюю цель
    if 'впав' in message_text or 'не фіксується' in message_text or 'більше не фіксується' in message_text:
        return [{"action": "clear_last"}]
    
    # Обработка отбоя
    if 'відбій' in message_text:
        return [{"action": "clear_all"}]
    
    return targets if targets else None


def add_target(target: Dict) -> bool:
    """Добавление цели"""
    data = load_targets()
    
    # Проверка на дубликаты (та же локация за последние 10 минут)
    current_time = datetime.now().timestamp()
    for existing in data['items'][-50:]:
        if (existing.get('location') == target.get('location') and
            current_time - existing.get('timestamp', 0) < 600):
            log_message(f"⏭️ Дубликат: {target.get('location')}")
            return False
    
    data['items'].append(target)
    
    # Ограничиваем количество (последние 200)
    if len(data['items']) > 200:
        data['items'] = data['items'][-200:]
    
    if save_targets(data):
        log_message(f"✅ Добавлено: {target['type']} | {target.get('location', '?')} | {target['lat']}, {target['lon']}")
        return True
    return False


def clear_last_target() -> bool:
    """Удаление последней цели"""
    data = load_targets()
    if data['items']:
        removed = data['items'].pop()
        if save_targets(data):
            log_message(f"🗑️ Удалено: {removed.get('location', '?')}")
            return True
    return False


def clear_all_targets() -> bool:
    """Очистка всех целей"""
    if save_targets({'items': []}):
        log_message("🗑️ Все цели удалены")
        return True
    return False


# ==================== ОСНОВНАЯ ЛОГИКА ПАРСЕРА ====================

async def parse_existing_messages(client: TelegramClient):
    """Парсинг истории сообщений"""
    state_file = 'last_state.json'
    state = {}
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except:
            pass
    
    for channel in SOURCE_CHANNELS:
        channel = channel.strip()
        if not channel:
            continue
        
        try:
            log_message(f"📥 Парсинг истории: {channel}")
            
            # Получаем последний обработанный ID
            last_id = state.get(channel, 0)
            
            # Получаем сообщения
            async for message in client.iter_messages(channel, limit=100, min_id=last_id):
                if not message or not message.text:
                    continue
                
                result = parse_message(message.text, message.id, channel)
                
                if result:
                    for item in result:
                        if item.get('action') == 'clear_last':
                            clear_last_target()
                        elif item.get('action') == 'clear_all':
                            clear_all_targets()
                        else:
                            add_target(item)
                    
                    # Обновляем состояние
                    if message.id > state.get(channel, 0):
                        state[channel] = message.id
                        with open(state_file, 'w') as f:
                            json.dump(state, f)
                
                await asyncio.sleep(0.3)  # Задержка
                
        except Exception as e:
            log_message(f"❌ Ошибка парсинга {channel}: {e}")


async def listen_for_new_messages(client: TelegramClient):
    """Прослушивание новых сообщений в реальном времени"""
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNELS))
    async def message_handler(event):
        message = event.message
        channel = await event.get_chat()
        channel_name = channel.username or str(channel.id)
        
        if not message or not message.text:
            return
        
        log_message(f"📨 Новое сообщение из {channel_name}: {message.text[:80]}...")
        
        result = parse_message(message.text, message.id, channel_name)
        
        if result:
            for item in result:
                if item.get('action') == 'clear_last':
                    clear_last_target()
                elif item.get('action') == 'clear_all':
                    clear_all_targets()
                else:
                    add_target(item)


# ==================== АВТОРИЗАЦИЯ ====================

async def authorize(client: TelegramClient):
    """Авторизация через телефон (однократно)"""
    if not PHONE_NUMBER:
        log_message("❌ PHONE_NUMBER не задан!")
        return False
    
    try:
        # Пытаемся войти по сохраненной сессии
        await client.start(phone=PHONE_NUMBER)
        log_message(f"✅ Авторизация успешна! Аккаунт: {await client.get_me()}")
        return True
    except Exception as e:
        log_message(f"❌ Ошибка авторизации: {e}")
        return False


# ==================== ЗАПУСК ====================

async def main():
    """Запуск парсера"""
    
    # Проверка конфигурации
    if not API_ID or not API_HASH:
        log_message("❌ Ошибка: не заданы API_ID или API_HASH")
        log_message("Установите переменные окружения: API_ID, API_HASH, PHONE_NUMBER")
        return
    
    if not PHONE_NUMBER:
        log_message("❌ Ошибка: не задан PHONE_NUMBER")
        log_message("Установите переменную окружения PHONE_NUMBER (например: +380123456789)")
        return
    
    if not SOURCE_CHANNELS or SOURCE_CHANNELS == ['']:
        log_message("⚠️ Внимание: не заданы SOURCE_CHANNELS!")
    
    # Создаем клиента с сессией
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    
    # Авторизация
    if not await authorize(client):
        log_message("❌ Не удалось авторизоваться")
        return
    
    log_message(f"✅ Парсер запущен!")
    log_message(f"📡 Отслеживаемые каналы: {SOURCE_CHANNELS}")
    
    # Парсим историю
    await parse_existing_messages(client)
    
    # Запускаем прослушивание новых сообщений
    await listen_for_new_messages(client)
    
    # Держим бота активным
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
