/**
 * TACTICAL MONITOR CORE v4.2 PRO
 * CONNECTED TO NEPTUN PARSER v4.0
 */

"use strict";

const AppState = {
    targets: [],
    markers: new Map(),
    userCoords: null,
    alertRadius: 50,
    missileAlerts: true,
    autoFocus: false,
    activePage: 'map',
    notifiedIds: new Set(),

    save() {
        localStorage.setItem('tactical_monitor_v4', JSON.stringify({
            alertRadius: this.alertRadius,
            missileAlerts: this.missileAlerts,
            autoFocus: this.autoFocus
        }));
    },

    load() {
        const saved = localStorage.getItem('tactical_monitor_v4');
        if (saved) Object.assign(this, JSON.parse(saved));
    }
};

// --- ГЕО-ЛОГІКА ---
const GeoUtils = {
    getDistance(lat1, lon1, lat2, lon2) {
        const R = 6371; 
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2 +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon / 2) ** 2;
        return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
    }
};

// --- МОДУЛЬ КАРТИ ---
const MapManager = {
    instance: null,
    userMarker: null,

    init() {
        this.instance = L.map('map', { 
            zoomControl: false, 
            attributionControl: false,
            maxZoom: 18
        }).setView([49.9935, 36.2304], 9);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(this.instance);
    },

    syncMarkers(targets) {
        const now = new Date().toISOString();
        const currentIds = new Set(targets.map(t => String(t.id)));

        // 1. Видалення застарілих маркерів (якщо ID зник з JSON)
        this.markers.forEach((marker, id) => {
            if (!currentIds.has(id)) {
                this.instance.removeLayer(marker);
                this.markers.delete(id);
            }
        });

        // 2. Оновлення або додавання нових
        targets.forEach(t => {
            // Перевірка TTL (не відображати, якщо expire_at вже в минулому)
            if (t.expire_at < now) return;

            if (this.markers.has(t.id)) {
                // Оновлюємо позицію, якщо вона змінилася
                this.markers.get(t.id).setLatLng([t.lat, t.lng]);
            } else {
                // Створюємо новий маркер
                const icon = L.icon({
                    iconUrl: t.icon, // Шлях img/*.png з парсера
                    iconSize: [32, 32],
                    iconAnchor: [16, 16],
                    className: (['missile', 'ballistics', 'kab'].includes(t.type)) ? 'threat-pulse' : ''
                });

                const m = L.marker([t.lat, t.lng], { icon }).addTo(this.instance);
                m.bindPopup(`<div class="text-[10px] font-mono"><b>${t.label}</b><br>ЧАС: ${t.time}</div>`);
                this.markers.set(t.id, m);

                // Сповіщення про нову загрозу
                UIManager.notify(`НОВА ЦІЛЬ: ${t.label}`, t.type === 'ballistics' ? 'danger' : 'warning');
            }
        });
    }
};

// --- МОДУЛЬ UI ---
const UIManager = {
    init() {
        AppState.load();
        this.updateClock();
        setInterval(() => this.updateClock(), 1000);
    },

    updateClock() {
        const el = document.getElementById('clock');
        if (el) el.innerText = new Date().toLocaleTimeString('uk-UA');
    },

    renderList(targets) {
        const container = document.getElementById('targets-container');
        if (!container) return;

        if (targets.length === 0) {
            container.innerHTML = `<div class="text-center opacity-30 py-20 text-xs uppercase tracking-widest">Небо чисте</div>`;
            return;
        }

        container.innerHTML = targets.map(t => `
            <div class="glass p-3 mb-2 border-l-4 ${t.type === 'missile' ? 'border-red-600' : 'border-orange-500'} flex items-center gap-3 active:scale-95 transition-all" 
                 onclick="Router.go('map'); MapManager.instance.flyTo([${t.lat}, ${t.lng}], 12)">
                <img src="${t.icon}" class="w-8 h-8 object-contain">
                <div class="flex-grow">
                    <div class="text-[11px] font-bold text-orange-500 uppercase">${t.label}</div>
                    <div class="text-[9px] opacity-60 font-mono">ID: ${t.id} | ЧАС: ${t.time}</div>
                </div>
            </div>
        `).join('');
    },

    notify(text, type = 'info') {
        const log = document.getElementById('logs-container');
        if (!log) return;
        const entry = document.createElement('div');
        const color = type === 'danger' ? 'border-red-600 bg-red-900/10' : 'border-orange-500 bg-orange-900/10';
        entry.className = `p-2 border-l-2 ${color} mb-1 text-[9px] font-mono animate-pulse`;
        entry.innerHTML = `<span class="opacity-40">[${new Date().toLocaleTimeString()}]</span> ${text}`;
        log.prepend(entry);
    },

    toggleSetting(key) {
        AppState[key] = !AppState[key];
        AppState.save();
        location.reload(); // Для швидкого застосування стилів перемикачів
    }
};

// --- РОУТЕР ---
const Router = {
    go(pageId) {
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(`page-${pageId}`).classList.add('active');
        AppState.activePage = pageId;
        if (pageId === 'map') MapManager.instance.invalidateSize();
    }
};

// --- ENGINE (СИНХРОНІЗАЦІЯ) ---
async function syncEngine() {
    try {
        const response = await fetch(`targets.json?v=${Date.now()}`);
        if (!response.ok) throw new Error();
        
        const data = await response.json();
        AppState.targets = data;

        MapManager.syncMarkers(data);
        UIManager.renderList(data);
        
        document.getElementById('sync-status').innerText = "Online";
        document.getElementById('obj-count').innerText = data.length;
    } catch (e) {
        document.getElementById('sync-status').innerText = "Sync Error";
    }
}

// ЗАПУСК
window.addEventListener('DOMContentLoaded', () => {
    UIManager.init();
    MapManager.init();
    
    // GPS Трекінг користувача
    if (navigator.geolocation) {
        navigator.geolocation.watchPosition(p => {
            const pos = [p.coords.latitude, p.coords.longitude];
            AppState.userCoords = { lat: pos[0], lng: pos[1] };
            if (MapManager.userMarker) {
                MapManager.userMarker.setLatLng(pos);
            } else {
                MapManager.userMarker = L.circleMarker(pos, { radius: 6, color: '#22c55e', fillOpacity: 1 }).addTo(MapManager.instance);
            }
        });
    }

    syncEngine();
    setInterval(syncEngine, 8000); // Оновлення кожні 8 секунд
});
