const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..','html');

function worker(){
  const handlers={};const stored=new Map();const removed=[];let skipped=0;let calls=0;
  const cache={addAll:async requests=>{for(const r of requests){const p=new URL(r.url).pathname;assert.ok(fs.existsSync(path.join(root,p)));stored.set(p,new Response('cached:'+p));}},match:async p=>stored.get(p)?.clone()};
  const self={location:{origin:'https://example.org'},addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting:()=>{skipped++;}};
  const context=vm.createContext({self,URL,Request:class{constructor(url){this.url=new URL(url,self.location.origin).href;}},
    caches:{open:async()=>cache,keys:async()=>['donga-ui-v0','donga-ui-v1','donga-ui-v2','donga-ui-v3','donga-ui-v4','another-app-cache'],delete:async key=>removed.push(key)},
    fetch:async()=>{calls++;throw Error('offline');}});
  vm.runInContext(fs.readFileSync(path.join(root,'sw.js'),'utf8'),context);
  return {handlers,stored,removed,get skipped(){return skipped;},get calls(){return calls;},context};
}

test('manifest points to existing standalone app and correctly sized PNG icons',()=>{
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.webmanifest'),'utf8'));
  assert.equal(manifest.display,'standalone');assert.equal(manifest.scope,'/');
  assert.ok(fs.existsSync(path.join(root,manifest.start_url)));
  for(const icon of manifest.icons){
    const image=fs.readFileSync(path.join(root,icon.src));const [w,h]=icon.sizes.split('x').map(Number);
    assert.equal(image.readUInt32BE(16),w);assert.equal(image.readUInt32BE(20),h);
  }
  for(const file of ['index.html','chat.html','meals.html','install.html','offline.html']){
    const html=fs.readFileSync(path.join(root,file),'utf8');
    assert.match(html,/manifest\.webmanifest/);assert.match(html,/viewport-fit=cover/);assert.match(html,/pwa\.js/);
  }
});
test('installation caches only complete public assets',async()=>{
  const w=worker();let done;
  w.handlers.install({waitUntil:p=>done=p});await done;
  assert.ok(w.stored.has('/offline.html'));
  assert.ok([...w.stored.keys()].every(p=>!p.startsWith('/api/')&&!p.includes('.env')));
});
test('API, private, POST, and external requests are never intercepted',()=>{
  const w=worker();
  for(const [url,method] of [['/api/v1/ask','POST'],['/api/v1/meals?month=2026-09','GET'],['/api/v1/admin/feedback','GET'],['/private/report','GET'],['https://other.example/app.js','GET'],['/app.js','POST']]){
    w.handlers.fetch({request:{url:new URL(url,'https://example.org').href,method,mode:'cors'},respondWith:()=>assert.fail('request intercepted')});
  }
  assert.equal(w.calls,0);
});
test('offline navigation uses shell without caching the query string',async()=>{
  const w=worker();let install;
  w.handlers.install({waitUntil:p=>install=p});await install;
  let response;
  w.handlers.fetch({request:{url:'https://example.org/meals.html?month=2026-09&campus=2',method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal(await (await response).text(),'cached:/meals.html');
  assert.ok(![...w.stored.keys()].some(key=>key.includes('?')));
});
test('online content is fresh and API content cannot enter the cache',async()=>{
  const w=worker();w.context.fetch=async()=>new Response('new UI');let response;
  w.handlers.fetch({request:{url:'https://example.org/chat.html',method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal(await (await response).text(),'new UI');assert.equal(w.stored.size,0);
});
test('activation only removes this app old cache and updates require an explicit message',async()=>{
  const w=worker();let done;w.handlers.activate({waitUntil:p=>done=p});await done;
  assert.deepEqual(w.removed,['donga-ui-v0','donga-ui-v1','donga-ui-v2','donga-ui-v3']);assert.equal(w.skipped,0);
  w.handlers.message({data:{type:'OTHER'}});assert.equal(w.skipped,0);
  w.handlers.message({data:{type:'APPLY_UPDATE'}});assert.equal(w.skipped,1);
});

test('OAuth callbacks and account screens never enter service worker cache',()=>{
  const w=worker();
  for(const path of ['/account.html','/account.js','/api/v1/canvas/callback?code=secret','/api/v1/canvas/courses']){
    w.handlers.fetch({request:{url:'https://example.org'+path,method:'GET',mode:'navigate'},respondWith:()=>assert.fail('private request intercepted')});
  }
});
