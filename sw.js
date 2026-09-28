// Moto Parking service worker. Paths are relative to this file, so it works from a subpath.
const VERSION = '5893a7c835';
const STATIC_CACHE = 'moto-parking-static-' + VERSION;
const TILE_CACHE = 'moto-parking-tiles-v1';
const TILE_MAX = 400; // max cached map tiles
const PRECACHE = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "apple-touch-icon.png",
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-512.png",
  "favicon-32.png",
  "vendor/leaflet/leaflet.js",
  "vendor/leaflet/leaflet.css",
  "vendor/leaflet/images/layers.png",
  "vendor/leaflet/images/layers-2x.png",
  "vendor/leaflet/images/marker-icon.png",
  "vendor/leaflet/images/marker-icon-2x.png",
  "vendor/leaflet/images/marker-shadow.png"
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(STATIC_CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith('moto-parking-static-') && k !== STATIC_CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

async function trimTiles() {
  const c = await caches.open(TILE_CACHE);
  const keys = await c.keys();
  for (let i = 0; i < keys.length - TILE_MAX; i++) await c.delete(keys[i]);
}

async function tileFetch(req) {
  const c = await caches.open(TILE_CACHE);
  const hit = await c.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res && (res.ok || res.type === 'opaque')) { await c.put(req, res.clone()); trimTiles(); }
    return res;
  } catch (e) {
    return new Response('', { status: 504, statusText: 'Offline' });
  }
}

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname.endsWith('tile.openstreetmap.org')) { event.respondWith(tileFetch(req)); return; }
  if (url.origin !== self.location.origin) return;
  // Navigations and other requests under this path are not stored and must not replace the cached page.
  if (/\/b-7k3q(?:\/|$)/.test(url.pathname)) {
    event.respondWith(fetch(req).catch(() => new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } })));
    return;
  }
  if (req.mode === 'navigate') {
    // Network first so data updates show up; fall back to the cached page offline.
    // Checklist visits must not replace the cached parking map.
    event.respondWith((async () => {
      const path = url.pathname;
      const isChecklist = /\/checklist(?:\/(?:index\.html)?)?$/.test(path);
      try {
        const res = await fetch(req);
        if (res.ok) {
          const c = await caches.open(STATIC_CACHE);
          c.put(isChecklist ? 'checklist/index.html' : 'index.html', res.clone());
        }
        return res;
      } catch (e) {
        if (isChecklist) {
          return (await caches.match('checklist/index.html')) || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
        }
        return (await caches.match('index.html', { ignoreSearch: true })) || (await caches.match('./'));
      }
    })());
    return;
  }
  event.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => hit || fetch(req)));
});
