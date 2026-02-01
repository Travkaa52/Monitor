/**
 * TACTICAL MONITOR CORE v4.0 PRO
 * Реліз: Лютий 2026
 */

"use strict";

const AppState = {
    targets: [],
    markers: new Map(),
    userCoords: null,
    alertRadius: 50,
    activeLayerName: "Тактична (Темна)",
    missileAlerts: true,
    autoFocus: false,
    activePage: 'map',
    notifiedIds: new Set(),

    save() {
        try {
            const data = {
                alertRadius: this.alertRadius,
                activeLayerName: this.activeLayerName,
                missileAlerts: this.missileAlerts,
                autoFocus: this.autoFocus
            };
            localStorage.setItem('tactical_monitor_v4', JSON.stringify(data));
        } catch (e) {
            console.error("Помилка збереження налаштувань:", e);
        }
    },

    load() {
        try {
            const saved = localStorage.getItem('tactical_monitor_v4');
            if (saved) {
                const data = JSON.parse(saved);
                Object.assign(this, data);
            }
        } catch (e) {
            console.warn("Помилка завантаження налаштувань, використано дефолтні.");
        }
    }
};

// --- МАТЕМАТИЧНИЙ МОДУЛЬ ---
const GeoUtils = {
    getDistance(lat1, lon1, lat2, lon2) {
        const R = 6371; // Радіус Землі
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
    }
};

// --- МОДУЛЬ КАРТИ ---
const MapManager = {
    instance: null,
    userMarker: null,
    tileLayers: {
        "Тактична (Темна)": L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'),
        "Супутник": L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'),
        "Топографія": L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png')
    },

    init() {
        this.instance = L.map('map', { 
            zoomControl: false, 
            attributionControl: false,
            fadeAnimation: true,
            markerZoomAnimation: true
        }).setView([49.0, 31.0], 6);

        const base = this.tileLayers[AppState.activeLayerName] || this.tileLayers["Тактична (Темна)"];
        base.addTo(this.instance);

        L.control.layers(this.tileLayers, null, { collapsed: true }).addTo(this.instance);

        this.instance.on('baselayerchange', (e) => {
            AppState.activeLayerName = e.name;
            AppState.save();
        });
    },

    updateUserPosition(coords) {
        const pos = [coords.lat, coords.lng];
        if (this.userMarker) {
            this.userMarker.setLatLng(pos);
        } else {
            this.userMarker = L.circleMarker(pos, {
                radius: 8, color: '#22c55e', fillColor: '#22c55e', fillOpacity: 0.8, weight: 2
            }).addTo(this.instance).bindPopup("ВАША ПОЗИЦІЯ");
        }
    },

    syncMarkers(targets) {
        const currentIds = new Set(targets.map(t => String(t.id)));

        // Видалення застарілих
        AppState.markers.forEach((marker, id) => {
            if (!currentIds.has(id)) {
                this.instance.removeLayer(marker);
                AppState.markers.delete(id);
                UIManager.notify(`ОБ'ЄКТ ${id} ЗНИК`, "warning");
            }
        });

        // Додавання/Оновлення
        targets.forEach(t => {
            const id = String(t.id);
            const icon = L.icon({
                iconUrl: `img/${t.type}.png`,
                iconSize: [32, 32],
                iconAnchor: [16, 16],
                className: (t.type === 'missile' || t.type === 'kab') ? 'threat-pulse' : ''
            });

            if (AppState.markers.has(id)) {
                const m = AppState.markers.get(id);
                m.setLatLng([t.lat, t.lng]);
            } else {
                const m = L.marker([t.lat, t.lng], { icon }).addTo(this.instance);
                m.bindPopup(`<b>${t.label}</b><br><small>ID: ${t.id}</small>`);
                AppState.markers.set(id, m);
            }
        });
    }
};

// --- МОДУЛЬ UI ---
const UIManager = {
    init() {
        AppState.load();
        this.syncToggles();
        this.setupEventListeners();
        
        // Годинник
        setInterval(() => {
            const clock = document.getElementById('clock');
            if (clock) clock.innerText = new Date().toLocaleTimeString('uk-UA');
        }, 1000);
    },

    setupEventListeners() {
        document.getElementById('alert-radius')?.addEventListener('input', (e) => {
            AppState.alertRadius = parseFloat(e.target.value) || 50;
            AppState.save();
            AppState.notifiedIds.clear();
        });
    },

    toggleSetting(key) {
        AppState[key] = !AppState[key];
        AppState.save();
        this.syncToggles();
        
        const label = { 'missileAlerts': 'СПОВІЩЕННЯ', 'autoFocus': 'АВТОФОКУС' }[key];
        this.notify(`${label}: ${AppState[key] ? 'УВІМК' : 'ВИМК'}`, "warning");
    },

    syncToggles() {
        const toggles = {
            'toggle-missile': AppState.missileAlerts,
            'toggle-focus': AppState.autoFocus
        };

        Object.entries(toggles).forEach(([id, active]) => {
            const btn = document.getElementById(id);
            if (!btn) return;
            const dot = btn.querySelector('div');
            
            // Використовуємо класи Tailwind для анімації
            if (active) {
                btn.classList.replace('bg-stone-800', 'bg-orange-600');
                dot.classList.add('translate-x-5');
            } else {
                btn.classList.replace('bg-orange-600', 'bg-stone-800');
                dot.classList.remove('translate-x-5');
            }
        });
    },

    renderList(targets) {
        const container = document.getElementById('targets-container');
        if (!container) return;

        if (targets.length === 0) {
            container.innerHTML = `<p class="text-center opacity-30 py-10">ЦІЛЕЙ НЕ ВИЯВЛЕНО</p>`;
            return;
        }

        container.innerHTML = targets.map(t => {
            const dist = AppState.userCoords ? 
                GeoUtils.getDistance(AppState.userCoords.lat, AppState.userCoords.lng, t.lat, t.lng).toFixed(1) : '--';
            
            return `
                <div class="glass p-3 rounded-xl flex items-center gap-3 border-l-4 ${t.type === 'missile' ? 'border-red-600' : 'border-orange-500'} active:scale-95 transition-all cursor-pointer" 
                     onclick="UIManager.focusTarget(${t.lat}, ${t.lng})">
                    <div class="w-10 h-10 bg-black/20 rounded-lg flex items-center justify-center">
                        <img src="img/${t.type}.png" class="w-7 h-7 object-contain" onerror="this.src='img/default.png'">
                    </div>
                    <div class="flex-grow">
                        <h4 class="font-bold text-[11px] text-orange-400 uppercase tracking-tight">${t.label}</h4>
                        <p class="text-[9px] opacity-60 font-mono">DIST: ${dist}KM | AZM: ${t.id}</p>
                    </div>
                    <div class="text-right font-mono text-[9px] text-orange-500/80">
                        ${t.lat.toFixed(3)}<br>${t.lng.toFixed(3)}
                    </div>
                </div>`;
        }).join('');
    },

    focusTarget(lat, lng) {
        Router.go('map');
        setTimeout(() => {
            MapManager.instance.flyTo([lat, lng], 11, { 
                animate: true, 
                duration: 1.5 
            });
        }, 250);
    },

    notify(text, type) {
        const container = document.getElementById('logs-container');
        if (!container) return;
        
        const entry = document.createElement('div');
        const colors = {
            danger: 'border-red-600 bg-red-500/5',
            warning: 'border-yellow-600 bg-yellow-500/5',
            info: 'border-blue-600 bg-blue-500/5'
        };
        
        entry.className = `p-2 border-l-2 ${colors[type] || colors.info} mb-1 text-[10px] font-mono animate-in fade-in slide-in-from-left-2 duration-300`;
        entry.innerHTML = `<span class="opacity-40">[${new Date().toLocaleTimeString()}]</span> ${text}`;
        
        container.prepend(entry);
        if (container.children.length > 25) container.lastChild.remove();
    }
};

// --- РОУТЕР ---
const Router = {
    go(pageId) {
        if (AppState.activePage === pageId) return;
        
        const oldPage = document.querySelector(`#page-${AppState.activePage}`);
        const newPage = document.querySelector(`#page-${pageId}`);
        
        if (!oldPage || !newPage) return;

        gsap.to(oldPage, { 
            opacity: 0, 
            y: 10, 
            duration: 0.2, 
            onComplete: () => {
                oldPage.classList.remove('active');
                newPage.classList.add('active');
                gsap.fromTo(newPage, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.3 });
                if (pageId === 'map') MapManager.instance.invalidateSize();
            }
        });

        AppState.activePage = pageId;
        this.updateNav();
    },

    updateNav() {
        document.querySelectorAll('.nav-btn').forEach(btn => {
            const isActive = btn.id === `nav-${AppState.activePage}`;
            btn.classList.toggle('opacity-100', isActive);
            btn.classList.toggle('text-orange-500', isActive);
            btn.classList.toggle('opacity-50', !isActive);
        });
    }
};

// --- ENGINE (ЯДРО) ---
async function engine() {
    try {
        const response = await fetch(`targets.json?v=${Date.now()}`);
        if (!response.ok) throw new Error("Server Sync Failed");
        
        const data = await response.json();
        AppState.targets = data;

        // Оновлення компонентів
        MapManager.syncMarkers(data);
        UIManager.renderList(data);
        
        // Перевірка загроз
        if (AppState.userCoords && AppState.missileAlerts) {
            data.forEach(t => {
                const dist = GeoUtils.getDistance(AppState.userCoords.lat, AppState.userCoords.lng, t.lat, t.lng);
                
                if (dist <= AppState.alertRadius && !AppState.notifiedIds.has(t.id)) {
                    // Логіка Push сповіщення тут...
                    UIManager.notify(`PUSH: ЗАГРОЗА ${t.label} - ${dist.toFixed(1)}км`, "danger");
                    AppState.notifiedIds.add(t.id);
                    if (AppState.autoFocus) UIManager.focusTarget(t.lat, t.lng);
                }
            });
        }

        const badge = document.getElementById('obj-count');
        if (badge) badge.innerText = data.length;

    } catch (e) {
        UIManager.notify("СИНХРОНІЗАЦІЯ ПЕРЕРВАНА", "danger");
    }
}

// Запуск
window.addEventListener('DOMContentLoaded', () => {
    UIManager.init();
    MapManager.init();
    Router.updateNav();
    
    // GPS
    if ("geolocation" in navigator) {
        navigator.geolocation.watchPosition(
            p => {
                AppState.userCoords = { lat: p.coords.latitude, lng: p.coords.longitude };
                MapManager.updateUserPosition(AppState.userCoords);
            },
            null, { enableHighAccuracy: true }
        );
    }

    engine();
    setInterval(engine, 5000);
});
