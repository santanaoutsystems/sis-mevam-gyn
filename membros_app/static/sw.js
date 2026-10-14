// Service Worker básico para PWA do SIS MEVAM-GYN
const CACHE_NAME = 'mevam-gyn-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Pass-through padrão para requisições online
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
