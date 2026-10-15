/* Service worker mínimo: permite instalar o app (PWA) sem guardar dados pessoais em cache. */
const CACHE = "mevam-estaticos-v2";
const ESTATICOS = ["/static/css/app.css", "/static/js/mascaras.js", "/static/js/tema.js", "/static/img/logo_round.jpg"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESTATICOS))));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/")) return; // páginas nunca vêm do cache
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
