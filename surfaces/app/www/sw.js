// LifeOS service worker: cache the shell, never cache the API.
const CACHE = "lifeos-shell-v8";
const SHELL_FINGERPRINT = "0086a6cda6fd702a";  // see tests/test_sw_fingerprint.py
const SHELL = ["./", "./index.html", "./style.css", "./app.js", "./agent.js", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png"];

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
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/v1/") || url.pathname.endsWith("/health")) {
    return; // API: always network
  }
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((resp) => {
      const copy = resp.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return resp;
    }))
  );
});

// Web Push: the agent's morning check-in (modules/notifications/checkins.py). The payload
// arrives already decrypted by the browser; show it, and open the app when it is tapped.
self.addEventListener("push", (e) => {
  let msg = {};
  try { msg = e.data ? e.data.json() : {}; } catch (err) { msg = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(msg.title || "LifeOS", {
    body: msg.body || "", tag: msg.tag || "lifeos", data: { url: msg.url || "./" },
    icon: "./icons/icon-192.png", badge: "./icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    const open = wins.find((w) => w.url.startsWith(self.registration.scope));
    if (open) { open.focus(); return open.navigate ? open.navigate(target) : null; }
    return self.clients.openWindow(target);
  }));
});
