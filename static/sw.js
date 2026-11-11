const CACHE_NAME = 'compostaje-cache-v1';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/js/script.js'
];

// Instalar el Service Worker
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

// Activar y limpiar cachés viejos
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Interceptar peticiones (Modo Offline)
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Si está en caché, devuélvelo. Si no, búscalo en la red.
        return response || fetch(event.request);
      })
  );
});