/**
 * TACTICAL MONITOR CORE v3.6.1 (RECOVERY)
 */

"use strict";

const state = {
    targets: [],
    markers: new Map(),
    alertRadius: 50,
    missileAlerts: true,
    autoFocus: false,
    activePage: 'map'
};

// --- РОУТЕР (ЗБЕРЕЖЕНО ОРИГІНАЛЬНІ АНІМАЦІЇ GSAP) ---
const router = {
    go(pageId) {
        const pages = document.querySelectorAll('.page');
        const navBtns = document.querySelectorAll('.nav-btn');
        
        pages.forEach(p => {
            p.classList.remove('active');
            gsap.set(p, { opacity: 0, y: 10 });
        });
        
        const next = document.getElementById(`page-${pageId}`);
        if (next) {
            next.classList.add('active');
            gsap.to(next, { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" });
            state.activePage = pageId;
        }

        navBtns.forEach(btn => {
            const isTarget = btn.id === `nav-${pageId}`;
            btn.style.opacity = isTarget ? "1" : "0.5";
            btn.classList.toggle('text-orange-500', isTarget);
        });

        if (pageId === 'map' && mapManager.instance) {
            setTimeout(() => mapManager.instance.invalidateSize(), 200);
        }
    }
};

// --- КЕРУВАННЯ UI ---
const ui = {
    init() {
        this.loadSettings();
        this.updateClock();
        setInterval(() => this.updateClock(), 1000);
    },

    updateClock() {
        const el = document.getElementById('clock');
        if (el) el.innerText = new Date().toLocaleTimeString('uk-UA');
    },

    toggleSetting(key) {
        state[key] = !state[key];
        this.saveSettings();
        this.applyVisualSettings();
        this.log(`Налаштування: ${key} = ${state[key]}`);
    },

    updateRadius(val) {
        state.alertRadius = parseInt(val);
        this.saveSettings();
    },

    saveSettings() {
        localStorage.setItem('tactical_settings', JSON.stringify({
            radius: state.alertRadius,
            missile: state.missileAlerts,
            focus: state.autoFocus
        }));
    },

    loadSettings() {
        const saved = localStorage.getItem('tactical_settings');
        if (saved) {
            const d = JSON.parse(saved);
            state.alertRadius = d.radius || 50;
            state.missileAlerts = d.missile ?? true;
            state.autoFocus = d.focus ?? false;
            
            const rInput = document.getElementById('alert-radius');
            if (rInput) rInput.value = state.alertRadius;
            this.applyVisualSettings();
        }
    },

    applyVisualSettings() {
        // Missile Toggle
        const dotM = document.getElementById('dot-missile');
        const bgM = document.getElementById('toggle-missile');
        if (dotM) dotM.style.transform = state.missileAlerts ? 'translateX(20px)' : 'translateX(0)';
        if (bgM) bgM.style.backgroundColor = state.missileAlerts ? '#f97316' : '#292524';

        // Focus Toggle
        const dotF = document.getElementById('dot-focus');
        const bgF = document.getElementById('toggle-focus');
        if (dotF) dotF.style.transform = state.autoFocus ? 'translateX(20px)' : 'translateX(0)';
        if (bgF) bgF.style.backgroundColor = state.autoFocus ? '#f97316' : '#292524';
    },

    renderTargets(targets) {
        const container = document.getElementById('targets-container');
        if (!container) return;

        container.innerHTML = targets.length ? targets.map(t => `
            <div class="glass p-3 mb-2 border-l-4 border-orange-500 flex justify-between items-center" 
                 onclick="router.go('map'); mapManager.instance.flyTo([${t.lat}, ${t.lng}], 12)">
                <div>
                    <div class="text-[11px] font-bold text-orange-500 uppercase">${t.label}</div>
                    <div class="text-[9px] opacity-60">${t.time} | Lat: ${t.lat.toFixed(2)}</div>
                </div>
                <img src="${t.icon}" class="w-8 h-8 opacity-80 object-contain">
            </div>
        `).join('') : '<p class="text-center opacity-20 py-10 text-xs">НЕБО ЧИСТЕ</p>';
    },

    log(msg) {
        const container = document.getElementById('logs-container');
        if (!container) return;
        const div = document.createElement('div');
        div.className = "border-l border-white/10 pl-2 py-1 opacity-70";
        div.innerHTML = `<span class="text-orange-500/50">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        container.prepend(div);
    }
};

// --- КАРТА ---
const mapManager = {
    instance: null,

    init() {
        this.instance = L.map('map', { zoomControl: false, attributionControl: false })
            .setView([49.99, 36.23], 9);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(this.instance);
    },

    sync(targets) {
        const now = new Date().toISOString();
        const activeIds = new Set(targets.map(t => String(t.id)));

        // Прибирання старих
        this.instance.eachLayer(layer => {
            if (layer instanceof L.Marker && layer.options.id) {
                if (!activeIds.has(layer.options.id)) this.instance.removeLayer(layer);
            }
        });

        // Додавання нових
        targets.forEach(t => {
            if (t.expire_at && t.expire_at < now) return;

            const icon = L.icon({
                iconUrl: t.icon,
                iconSize: [32, 32],
                iconAnchor: [16, 16],
                className: (['missile', 'ballistics', 'kab'].includes(t.type)) ? 'threat-pulse' : ''
            });

            const marker = L.marker([t.lat, t.lng], { icon, id: t.id }).addTo(this.instance);
            marker.bindPopup(`<div class="text-[10px] uppercase font-bold text-orange-500">${t.label}</div>`);
            
            if (state.autoFocus && targets.length === 1) this.instance.flyTo([t.lat, t.lng], 11);
        });
    }
};

// --- СИНХРОНІЗАЦІЯ З ПАРСЕРОМ ---
async function engine() {
    try {
        const res = await fetch(`targets.json?v=${Date.now()}`);
        const data = await res.json();
        
        state.targets = data;
        mapManager.sync(data);
        ui.renderTargets(data);
        
        document.getElementById('sync-status').innerText = "ONLINE";
        document.getElementById('obj-count').innerText = data.length;
    } catch (e) {
        document.getElementById('sync-status').innerText = "ERROR";
    }
}

// Експорт об'єктів у глобальну видимість (щоб onclick працював)
window.router = router;
window.ui = ui;

document.addEventListener('DOMContentLoaded', () => {
    mapManager.init();
    ui.init();
    engine();
    setInterval(engine, 5000);
});
