const CACHE_NAME = 'compostaje-cache-v3';
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
  self.skipWaiting();
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
  if (event.request.method !== 'GET') return;

  event.respondWith(
    caches.match(event.request).then(response => {
      // Si está en caché, lo devuelve. Si no, va a la red.
      return response || fetch(event.request);
    }).catch(() => {
      // Si falla la red y no está en caché, no rompe la app
      return new Response("Estás offline.");
    })
  );
});