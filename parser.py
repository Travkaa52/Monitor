#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import asyncio
import uuid
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from telethon import TelegramClient, events, errors
from geopy.geocoders import Nominatim

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('defense_system.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ (Заполни своими данными) ---
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
PHONE = os.environ.get('PHONE_NUMBER', '')
CHANNELS = ['@monitor1654', '@kharkivlife', '@air_alert_ua'] # Список каналов

# Константы для расчетов
REGION_CONTEXT = "Харківська область, Україна"
SPEEDS = {
    'KAB': 650,        # КАБ (УМПК)
    'SHAHED': 180,     # БПЛА Герань/Шахед
    'ROCKET': 850,     # Крылатые ракеты
    'BALISTICS': 3500, # С-300 / Искандер-М
    'UNKNOWN': 300
}

class KharkivDefenseSystem:
    def __init__(self):
        self.client = TelegramClient('defense_session', API_ID, API_HASH)
        self.geolocator = Nominatim(user_agent="kharkiv_defense_v4")
        self.data_file = 'live_targets.json'
        self.cache_file = 'geo_cache.json'
        
        self.geo_cache = self._load_json(self.cache_file, {})
        self.active_targets = self._load_json(self.data_file, {"items": []})

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---
    def _load_json(self, path, default):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default

    def _save_json(self, path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --- МАТЕМАТИЧЕСКИЙ ДВИЖОК ---
    def calculate_bearing(self, lat1, lon1, lat2, lon2) -> float:
        """Расчет азимута (направления)"""
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)
        y = math.sin(delta_lambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def get_future_pos(self, lat, lon, bearing, speed, mins) -> Tuple[float, float]:
        """Экстраполяция: где будет цель через N минут"""
        R = 6371
        d = speed * (mins / 60)
        lat1, lon1 = math.radians(lat), math.radians(lon)
        brng = math.radians(bearing)
        lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(brng))
        lon2 = lon1 + math.atan2(math.sin(brng)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
        return math.degrees(lat2), math.degrees(lon2)

    # --- ГЕОКОДИНГ ---
    async def get_coords(self, name: str) -> Optional[Tuple[float, float]]:
        name_clean = name.lower().strip()
        if name_clean in self.geo_cache:
            return tuple(self.geo_cache[name_clean])
        
        try:
            query = f"{name}, {REGION_CONTEXT}"
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(None, lambda: self.geolocator.geocode(query, timeout=5))
            if location:
                res = (location.latitude, location.longitude)
                self.geo_cache[name_clean] = res
                self._save_json(self.cache_file, self.geo_cache)
                return res
        except: pass
        return None

    # --- ПАРСИНГ ТЕКСТА ---
    def detect_hazard(self, text: str) -> str:
        t = text.lower()
        if any(x in t for x in ['каб', 'керована', 'авіа']): return 'KAB'
        if any(x in t for x in ['шахед', 'бпла', 'shahed']): return 'SHAHED'
        if any(x in t for x in ['ракета', 'іскандер', 'калібр']): return 'ROCKET'
        if any(x in t for x in ['вибух', 'приліт']): return 'EXPLOSION'
        return 'UNKNOWN'

    async def process_text(self, text: str, source: str):
        t_low = text.lower()
        
        # 1. Команды очистки
        if any(w in t_low for w in ['відбій', 'чисто', 'спокійно']):
            self.active_targets["items"] = []
            logger.info("📢 КАРТА ОЧИЩЕНА")
            return True

        # 2. Поиск векторов (Маршрутов)
        # Пример: "КАБи из Липцев на Харьков" или "Шахеды: Волчанск -> Дергачи"
        route = re.findall(r'([А-ЯІЇЄ][а-яіїє\']+)\s*(?:на|—>|->|в напрямку)\s*([А-ЯІЇЄ][а-яіїє\']+)', text)
        hazard = self.detect_hazard(text)
        speed = SPEEDS.get(hazard, 300)

        new_entries = []
        
        if route:
            for start_n, end_n in route:
                c1 = await self.get_coords(start_n)
                c2 = await self.get_coords(end_n)
                if c1 and c2:
                    bearing = self.calculate_bearing(c1[0], c1[1], c2[0], c2[1])
                    preds = []
                    for m in [5, 10, 15]:
                        p_lat, p_lon = self.get_future_pos(c2[0], c2[1], bearing, speed, m)
                        preds.append({"min": m, "lat": p_lat, "lon": p_lon})
                    
                    new_entries.append({
                        "id": str(uuid.uuid4())[:6],
                        "type": hazard,
                        "location": end_n,
                        "lat": c2[0], "lon": c2[1],
                        "bearing": round(bearing, 1),
                        "speed": speed,
                        "predictions": preds,
                        "timestamp": int(datetime.now().timestamp())
                    })
        else:
            # Одиночные цели: "КАБ на Харьков"
            single_places = re.findall(r'(?:на|в|біля)\s+([А-ЯІЇЄ][а-яіїє\']+)', text)
            for p in list(set(single_places)):
                coords = await self.get_coords(p)
                if coords:
                    new_entries.append({
                        "id": str(uuid.uuid4())[:6],
                        "type": hazard,
                        "location": p,
                        "lat": coords[0], "lon": coords[1],
                        "timestamp": int(datetime.now().timestamp())
                    })

        if new_entries:
            # Обновляем список, удаляя дубликаты по локации
            for entry in new_entries:
                self.active_targets["items"] = [t for t in self.active_targets["items"] if t['location'] != entry['location']]
                self.active_targets["items"].append(entry)
            return True
        return False

    async def run(self):
        await self.client.start(phone=PHONE)
        logger.info("✅ Система запущена. Ожидание сообщений...")

        @self.client.on(events.NewMessage(chats=CHANNELS))
        async def handler(event):
            if event.message.text:
                if await self.process_text(event.message.text, "Telegram"):
                    self._save_json(self.data_file, self.active_targets)
                    logger.info(f"💾 Обновлено целей: {len(self.active_targets['items'])}")

        await self.client.run_until_disconnected()

if __name__ == "__main__":
    system = KharkivDefenseSystem()
    asyncio.run(system.run())
