/**
 * TACTICAL MONITOR ENGINE v4.2
 * Повна синхронізація з HTML та Python-парсером
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
        localStorage.setItem('tactical_v4_data', JSON.stringify({
            alertRadius: this.alertRadius,
            missileAlerts: this.missileAlerts,
            autoFocus: this.autoFocus
        }));
    },

    load() {
        const saved = localStorage.getItem('tactical_v4_data');
        if (saved) {
            const data = JSON.parse(saved);
            this.alertRadius = data.alertRadius || 50;
            this.missileAlerts = data.missileAlerts ?? true;
            this.autoFocus = data.autoFocus ?? false;
        }
        // Оновити інпути в UI
        const radInput = document.getElementById('alert-radius');
        if (radInput) radInput.value = this.alertRadius;
    }
};

const Router = {
    go(pageId) {
        console.log(`Router: Navigating to ${pageId}`);
        
        // 1. Сховати всі сторінки
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        
        // 2. Активувати потрібну
        const next = document.getElementById(`page-${pageId}`);
        if (next) {
            next.classList.add('active');
            AppState.activePage = pageId;
            
            // GSAP анімація появи
            gsap.fromTo(next, { opacity: 0, y: 5 }, { opacity: 1, y: 0, duration: 0.3 });
        }

        // 3. Оновити кнопки навігації
        document.querySelectorAll('.nav-btn').forEach(btn => {
            const isTarget = btn.id === `nav-${pageId}`;
            btn.classList.toggle('opacity-100', isTarget);
            btn.classList.toggle('text-orange-500', isTarget);
            btn.classList.toggle('opacity-50', !isTarget);
        });

        // 4. Пофіксити розмір карти при переході
        if (pageId === 'map' && MapManager.instance) {
            setTimeout(() => MapManager.instance.invalidateSize(), 100);
        }
    }
};

const MapManager = {
    instance: null,

    init() {
        this.instance = L.map('map', { 
            zoomControl: false, 
            attributionControl: false 
        }).setView([49.9935, 36.2304], 9);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(this.instance);
    },

    syncMarkers(targets) {
        const now = new Date().toISOString();
        const currentIds = new Set(targets.map(t => String(t.id)));

        // Видалення
        this.instance.eachLayer(layer => {
            if (layer instanceof L.Marker && layer.options.id) {
                if (!currentIds.has(layer.options.id)) {
                    this.instance.removeLayer(layer);
                    AppState.markers.delete(layer.options.id);
                }
            }
        });

        // Додавання/Оновлення
        targets.forEach(t => {
            if (t.expire_at && t.expire_at < now) return;

            const icon = L.icon({
                iconUrl: t.icon || 'img/unknown.png',
                iconSize: [32, 32],
                iconAnchor: [16, 16],
                className: (['missile', 'ballistics', 'kab'].includes(t.type)) ? 'threat-pulse' : ''
            });

            if (AppState.markers.has(t.id)) {
                AppState.markers.get(t.id).setLatLng([t.lat, t.lng]);
            } else {
                const m = L.marker([t.lat, t.lng], { icon, id: t.id }).addTo(this.instance);
                m.bindPopup(`<b class="text-orange-500">${t.label}</b>`);
                AppState.markers.set(t.id, m);
                
                if (AppState.autoFocus) this.instance.flyTo([t.lat, t.lng], 11);
                UIManager.notify(`DETECTED: ${t.label}`, t.type === 'ballistics' ? 'danger' : 'warning');
            }
        });
    }
};

const UIManager = {
    init() {
        AppState.load();
        this.syncToggles();
        setInterval(() => {
            document.getElementById('clock').innerText = new Date().toLocaleTimeString('uk-UA');
        }, 1000);
    },

    toggleSetting(key) {
        AppState[key] = !AppState[key];
        AppState.save();
        this.syncToggles();
        this.notify(`SETTING: ${key.toUpperCase()} ${AppState[key] ? 'ON' : 'OFF'}`);
    },

    syncToggles() {
        const t1 = document.getElementById('toggle-missile');
        const t2 = document.getElementById('toggle-focus');
        
        if (t1) {
            t1.classList.toggle('bg-orange-600', AppState.missileAlerts);
            t1.querySelector('div').style.transform = AppState.missileAlerts ? 'translateX(24px)' : 'translateX(0)';
        }
        if (t2) {
            t2.classList.toggle('bg-orange-600', AppState.autoFocus);
            t2.querySelector('div').style.transform = AppState.autoFocus ? 'translateX(24px)' : 'translateX(0)';
        }
    },

    updateRadius(val) {
        AppState.alertRadius = parseInt(val);
        AppState.save();
        this.notify(`RADIUS UPDATED: ${val} KM`);
    },

    renderList(targets) {
        const container = document.getElementById('targets-container');
        if (!container) return;
        
        if (targets.length === 0) {
            container.innerHTML = `<div class="text-center py-20 opacity-20 text-xs">CLEAR SKY</div>`;
            return;
        }

        container.innerHTML = targets.map(t => `
            <div class="glass p-4 border-l-4 border-orange-500 flex items-center justify-between" onclick="Router.go('map'); MapManager.instance.flyTo([${t.lat}, ${t.lng}], 12)">
                <div>
                    <div class="text-xs font-bold text-orange-500">${t.label}</div>
                    <div class="text-[9px] opacity-50 font-mono">${t.time} | ID: ${t.id}</div>
                </div>
                <img src="${t.icon}" class="w-8 h-8 opacity-80">
            </div>
        `).join('');
    },

    notify(msg, type = 'info') {
        const log = document.getElementById('logs-container');
        if (!log) return;
        const div = document.createElement('div');
        div.className = `p-2 border-l-2 ${type === 'danger' ? 'border-red-600 bg-red-900/10' : 'border-orange-500 bg-orange-900/10'} mb-1`;
        div.innerHTML = `<span class="opacity-40">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        log.prepend(div);
        if (log.children.length > 30) log.lastChild.remove();
    }
};

// Робимо об'єкти доступними для HTML
window.Router = Router;
window.UIManager = UIManager;

// Запуск
async function engine() {
    try {
        const res = await fetch(`targets.json?v=${Date.now()}`);
        const data = await res.json();
        AppState.targets = data;
        MapManager.syncMarkers(data);
        UIManager.renderList(data);
        document.getElementById('sync-status').innerText = 'Online';
        document.getElementById('obj-count').innerText = data.length;
    } catch (e) {
        document.getElementById('sync-status').innerText = 'Offline';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    MapManager.init();
    UIManager.init();
    engine();
    setInterval(engine, 8000);
});
