// Der Korrespondent – Service Worker
// Ausgaben & Seiten: Netz zuerst (immer aktuell), offline aus dem Zwischenspeicher.
// Schriften, Icons, Stylesheets: Zwischenspeicher zuerst (ändern sich selten).
const VERSION = 'korrespondent-v6';
const SHELL = [
  './', './index.html', './manifest.json', './icon.svg',
  './assets/fonts.css', './assets/site.css', './assets/icon-192.png',
  './data/ausgabe.json', './data/archiv/index.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Bilder von Wikimedia: Zwischenspeicher zuerst, damit gelesene Ausgaben offline vollständig sind
  if (url.hostname.endsWith('wikimedia.org')) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok || res.type === 'opaque') {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit))
    );
    return;
  }
  if (url.origin !== self.location.origin) return;

  const statisch = /\/assets\/|\.woff2$|icon\.svg$/.test(url.pathname);
  if (statisch) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
        return res;
      }))
    );
    return;
  }

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || caches.match('./index.html')))
  );
});
