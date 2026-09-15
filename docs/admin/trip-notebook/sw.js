// Deliberate opt-in, limited to the notebook. Never cache admin APIs or send a queue.
const CACHE = 'scout-trip-notebook-shell-__SHELL_VERSION__';
const BASE = new URL('./',self.location.href).pathname;
const ASSETS = ['', 'style.css','app.js','core.js','store.js','planning.js'];
self.addEventListener('install', event => event.waitUntil((async()=> {
  const cache=await caches.open(CACHE);
  await cache.addAll(ASSETS.map(file=>BASE+file));
  await self.skipWaiting();
})()));
self.addEventListener('activate', event=>event.waitUntil((async()=>{
  for(const name of await caches.keys()) if(name.startsWith('scout-trip-notebook-shell-') && name!==CACHE) await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event=>{
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== 'GET') return;
  const key = url.pathname === BASE ? BASE : ASSETS.slice(1).map(file=>BASE+file).includes(url.pathname) ? url.pathname : null;
  if (!key) return;
  event.respondWith((async()=>{
    const cached=await (await caches.open(CACHE)).match(key);
    return cached || fetch(event.request);
  })());
});
