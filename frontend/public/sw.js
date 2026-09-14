const CACHE='lasttake-shell-v1';
const ASSET=/^\/assets\/[A-Za-z0-9._-]+\.(?:js|css)$/;

async function installShell() {
  const response=await fetch(new Request('/',{cache:'reload'}));
  if(!response.ok)throw new Error(`shell returned ${response.status}`);
  const html=await response.clone().text();
  const paths=['/',...[...html.matchAll(/(?:src|href)=["'](\/assets\/[A-Za-z0-9._-]+\.(?:js|css))["']/g)].map(match=>match[1])];
  if(paths.length<2)throw new Error('shell named no built asset');
  const cache=await caches.open(CACHE);
  await cache.addAll([...new Set(paths)]);
}

self.addEventListener('install',event=>{
  event.waitUntil(installShell().then(()=>self.skipWaiting()));
});

self.addEventListener('activate',event=>{
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch',event=>{
  const request=event.request;
  const url=new URL(request.url);
  if(request.method!=='GET' || url.origin!==self.location.origin)return;
  // API, health, proof and UAT responses are deliberately never cached. The
  // service worker preserves only the public application shell; the app keeps
  // one explicitly stale, read-only run snapshot in tab-scoped storage.
  if(url.pathname.startsWith('/api/') || url.pathname==='/api' || url.pathname==='/healthz' ||
      url.pathname.startsWith('/acceptance') || url.pathname.startsWith('/UAT.'))return;
  if(request.mode==='navigate'){
    event.respondWith(fetch(request).then(async response=>{
      if(response.ok)(await caches.open(CACHE)).put('/',response.clone());
      return response;
    }).catch(async()=>await caches.match('/') ?? Response.error()));
    return;
  }
  if(ASSET.test(url.pathname)){
    event.respondWith(caches.match(request).then(cached=>cached ?? fetch(request).then(async response=>{
      if(response.ok)(await caches.open(CACHE)).put(request,response.clone());
      return response;
    })));
  }
});
