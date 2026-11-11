const CACHE_NAME = 'compostaje-cache-v2';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/js/script.js',
  '/login',
  '/registrar_composta',
  '/mis_compostas',
  '/perfil'
];

self.addEventListener('install', event => {
  self.skipWaiting(); // Forzar actualización
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) return caches.delete(cacheName);
        })
      );
    })
  );
});

self.addEventListener('fetch', event => {
  // No interceptar peticiones POST (como el envío de formularios)
  if (event.request.method !== 'GET') return;

  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});