// Permet d'installer Radar Chantier comme une application. Les pages et les données sont toujours
// redemandées au site (sans utiliser la mémoire du navigateur) pour avoir la dernière version ;
// la dernière copie sert seulement quand il n'y a pas de réseau.
const CACHE = "radar-chantier-v2";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["./", "index.html", "icon.svg", "manifest.webmanifest"])));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(cles.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then((r) => { const copie = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copie)); return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
