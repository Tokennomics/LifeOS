// LifeOS Travel Mode service worker: cache the whole shell so it loads with no
// network at all. There is no API here — all data lives in IndexedDB, never cached.
const CACHE = "lifeos-travel-v6";
const SHELL = [
  "./travel.html", "./travel.js", "./horizon-core.js", "./travel-stats.js", "./travel-coach.js",
  "./style.css", "./travel.css", "./travel.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Cache-first: the shell must open in airplane mode. Fall back to travel.html
  // for navigations so a cold home-screen launch always resolves offline.
  e.respondWith(
    caches.match(e.request).then((hit) => hit
      || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      }).catch(() => e.request.mode === "navigate" ? caches.match("./travel.html") : undefined))
  );
});
