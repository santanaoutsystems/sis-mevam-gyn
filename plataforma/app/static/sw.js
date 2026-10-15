/* Service worker mínimo: permite instalar o app (PWA) sem guardar dados pessoais em cache. */
const CACHE = "mevam-estaticos-v7";
const ESTATICOS = ["/static/css/app.css", "/static/js/mascaras.js", "/static/js/tema.js", "/static/img/logo_round.jpg",
  "/static/fonts/plus-jakarta-sans-latin-wght-normal.woff2", "/static/fonts/outfit-latin-wght-normal.woff2"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESTATICOS))));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/")) return; // páginas nunca vêm do cache
  if (url.pathname.startsWith("/static/fonts/") || url.pathname.startsWith("/static/img/")) {
    // Fontes e imagens não mudam: usa a cópia do aparelho
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
    return;
  }
  // CSS e JS: busca a versão nova; sem internet, usa a cópia guardada
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
