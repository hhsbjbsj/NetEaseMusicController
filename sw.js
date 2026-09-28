// NetEase Music Controller Service Worker
const CACHE_NAME = 'netease-controller-v2';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Always fetch live for dynamic actions and status
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
