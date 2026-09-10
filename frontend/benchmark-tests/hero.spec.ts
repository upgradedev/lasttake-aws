import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
const measurement=await import(new URL('../scripts/hero-measurement.mjs',import.meta.url).href);
const helper=await import(new URL('../../web/video/hero-journey.mjs',import.meta.url).href);
test('fixed full source hero',async({page},info)=>{
  const root=process.env.LASTTAKE_BENCHMARK_ROOT!;
  const identity=measurement.readJSON(join(root,'identity.json'));
  const slot=measurement.beginSlot(root,(info.project.name==='desktop'?0:10)+info.repeatEachIndex+1);
  const save=()=>measurement.durableJSON(measurement.slotPath(root,slot.index),slot);
  const origin='http://127.0.0.1:4173';
  let started:number|null=null,active=false,blocked=0;
  const errors:string[]=[];
  const pending=new Map<unknown,number>();
  await page.context().route('**/*',async route=>{
    if(new URL(route.request().url()).origin!==origin){blocked++;return route.abort('blockedbyclient');}
    return route.continue();
  });
  page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('request',request=>{
    if(!active)return;
    let bytes:number|null=null;try{bytes=request.postDataBuffer()?.byteLength??0;}catch{}
    pending.set(request,slot.requests.length);
    slot.requests.push({method:request.method(),path:new URL(request.url()).pathname,body_bytes:bytes,status:null,
      start_ms:performance.now()-started!,end_ms:null});save();
  });
  page.on('response',response=>{
    const index=pending.get(response.request());if(index===undefined)return;
    Object.assign(slot.requests[index],{status:response.status(),end_ms:performance.now()-started!});save();
  });
  async function provenance(){
    const health=await page.request.get('/healthz');expect(health.status()).toBe(200);
    const data=await health.json();expect(data.commit).toBe(identity.commit);expect(data.run_state_store).toBe('local-files');
    const index=await page.request.get('/');expect(index.status()).toBe(200);
    const html=await index.body(),hashes:Record<string,string>={'index.html':measurement.sha256(html)};
    expect(html).toEqual(readFileSync('dist/index.html'));
    for(const match of html.toString().matchAll(/(?:src|href)="(\/assets\/[^"?]+)"/g)){
      const response=await page.request.get(match[1]);expect(response.status()).toBe(200);
      const bytes=await response.body();expect(bytes).toEqual(readFileSync(join('dist',match[1].slice(1))));
      hashes[match[1]]=measurement.sha256(bytes);
    }
    expect(Object.keys(hashes).length).toBeGreaterThan(1);return {health:data,asset_hashes:hashes};
  }
  try{
    slot.preflight=await provenance();slot.browser=page.context().browser()!.version();save();
    await page.goto('/');await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
    await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
    const scenes=helper.heroScenes(page,expect);
    await scenes.hook();await scenes.surface();
    slot.guard_before=measurement.readJSON(join(root,'guards.json'));
    started=performance.now();active=true;slot.timing_started_at=new Date().toISOString();save();
    for(const stage of slot.stages){
      slot.stage=stage.id;stage.status='RUNNING';stage.start_ms=performance.now()-started;slot.failed_elapsed_ms=stage.start_ms;save();
      const result=await scenes[stage.id]();
      stage.end_ms=performance.now()-started;stage.elapsed_ms=stage.end_ms-stage.start_ms;stage.status='PASSED';
      if(stage.id==='close')slot.receipt=result;
      slot.failed_elapsed_ms=performance.now()-started;save();
    }
    slot.elapsed_ms=performance.now()-started;active=false;
    slot.guard_after=measurement.readJSON(join(root,'guards.json'));
    slot.offline_verified=measurement.verifyOffline(slot.guard_before,slot.guard_after,identity.commit)&&blocked===0;
    expect(slot.offline_verified).toBe(true);expect(errors).toEqual([]);
    slot.postflight=await provenance();expect(slot.postflight.asset_hashes).toEqual(slot.preflight.asset_hashes);
    slot.model_calls=0;slot.model_cost_usd=0;slot.scripted_stream_calls=slot.guard_after.scripted_stream_calls-slot.guard_before.scripted_stream_calls;
    slot.status='PASSED';slot.failed_elapsed_ms=null;
  }catch(error){
    active=false;slot.status='FAILED';slot.failure=error instanceof Error?error.name:'UNKNOWN';
    slot.failed_elapsed_ms=started===null?null:performance.now()-started;slot.elapsed_ms=null;
    const stage=slot.stages.find((s:{status:string})=>s.status==='RUNNING');
    if(stage){stage.status='FAILED';stage.end_ms=slot.failed_elapsed_ms;stage.elapsed_ms=stage.end_ms-stage.start_ms;}
    throw error;
  }finally{slot.blocked_browser_requests=blocked;slot.ended_at=new Date().toISOString();save();}
});
