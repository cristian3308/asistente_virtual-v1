// Guarda solo la "carcasa" de la app para que abra rápido; la API nunca se guarda en caché.
const CACHE = "asistente-v2";
const CARCASA = ["/", "/static/app.js", "/static/styles.css", "/static/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CARCASA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Red primero (siempre la versión nueva); la caché solo si el PC no responde.
  e.respondWith(fetch(e.request).then((resp) => {
    if (resp.ok) { const copia = resp.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia)); }
    return resp;
  }).catch(() => caches.match(e.request)));
});
