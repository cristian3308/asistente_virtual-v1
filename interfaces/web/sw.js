// Guarda solo la "carcasa" de la app para que abra rápido; la API nunca se guarda en caché.
const CACHE = "asistente-v3";
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

// Notificaciones push: llegan aunque la app esté cerrada.
self.addEventListener("push", (e) => {
  let datos = { titulo: "Jarvis", cuerpo: "", url: "/" };
  try { datos = { ...datos, ...e.data.json() }; } catch (_) { if (e.data) datos.cuerpo = e.data.text(); }
  e.waitUntil(self.registration.showNotification(datos.titulo, {
    body: datos.cuerpo, icon: "/static/icon-192.png", badge: "/static/icon-192.png", data: { url: datos.url }, tag: "jarvis",
    renotify: true,
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const destino = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((ventanas) => {
    for (const v of ventanas) if ("focus" in v) return v.focus();
    return self.clients.openWindow(destino);
  }));
});
