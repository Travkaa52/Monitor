const CACHE_NAME = 'neptun-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/img/drone.png',
  '/img/missile.png',
  '/img/kab.png',
  '/img/mrls.png',
  '/img/recon.png',
  '/img/unknown.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});