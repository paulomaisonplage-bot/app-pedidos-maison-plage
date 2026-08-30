// Service Worker - Modo Seguro (Zero interferência em POST e APIs)
const CACHE_VERSION = 'maison-plage-v20260830_v2';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  // NUNCA intercepta requisições POST, PUT, DELETE ou rotas de API
  if (e.request.method !== 'GET' || e.request.url.includes('/api/')) {
    return; // Pass-through nativo do navegador
  }

  // Para recursos estáticos GET, sempre busca da rede primeiro
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
