import {test,expect,type Page} from '@playwright/test';

async function start(page:Page){
  await page.goto('/');
  await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
  await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
  return page.evaluate(()=>({session_id:localStorage.getItem('lasttake.session'),run_id:new URLSearchParams(location.hash.split('?')[1]).get('run')}));
}

async function reloadFromPage(page:Page){
  // WebKit's reload flag bypasses its service-worker navigation path while
  // offline. A same-tab navigation to the identical route plus a cache-buster
  // still performs a full document load through the cached shell. Do not use
  // a Playwright navigation waiter here: WebKit reports an internal protocol
  // error for an offline service-worker navigation even when the document is
  // replaced. The DOM sentinel proves this is a new document, not a hash edit.
  const target=new URL(page.url());
  target.searchParams.set('offline-reload',Date.now().toString());
  const marker=`before-${Date.now()}`;
  await page.evaluate(({url,sentinel})=>{
    document.documentElement.dataset.offlineReloadSentinel=sentinel;
    window.setTimeout(()=>window.location.assign(url),0);
  },{url:target.toString(),sentinel:marker});
  await expect.poll(()=>page.url()).toBe(target.toString());
  await expect(page.locator('html')).not.toHaveAttribute('data-offline-reload-sentinel',marker);
}

test('LT-RELIABLE-INTAKE editable refusal, correction, and missing-report recovery use real HTTP',async({page},info)=>{
  const body=await start(page);
  const initial=await (await page.request.post('/api/state',{data:body})).json();
  await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByRole('button',{name:'Try refused date'}).click();
  const refused=page.waitForResponse(r=>r.url().endsWith('/api/ingest'));
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  expect((await refused).status()).toBe(400);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('Document JSON')).toHaveValue(/2026-02-30/);
  const after=await (await page.request.post('/api/state',{data:body})).json();
  expect(after.package_revision_digest).toBe(initial.package_revision_digest);
  expect(after.delivery_outcomes).toEqual(initial.delivery_outcomes);
  await page.getByRole('button',{name:'Try corrected date'}).click();
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
  await page.reload();
  await expect(page.getByRole('button',{name:'Add take or release'})).toBeEnabled();
  await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByRole('button',{name:'Try valid take'}).click();
  await page.getByLabel('No independent camera report supplied').check();
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
  await page.reload();
  const saved=await (await page.request.post('/api/state',{data:body})).json();
  expect(saved.exceptions.find((f:{check_type:string;requirement_id:string})=>f.check_type==='metadata' && f.requirement_id==='T-900').truth_state).toBe('missing');
  const scene=await (await page.request.post('/api/scene',{data:body})).json();
  expect(scene.beats.flatMap((b:{takes:unknown[]})=>b.takes).find((t:{take_id:string})=>t.take_id==='T-900').camera_report).toBeNull();
  await page.getByRole('navigation').getByRole('link',{name:'Handoff',exact:true}).click();
  await page.getByRole('button',{name:'Prepare receipt'}).click();
  await expect(page.getByRole('button',{name:'Download evidence summary'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('reliability-intake.png'),fullPage:true});
});

test('LT-RELIABLE-WRAP both API routes refuse stale review, decline recovers, new decline revokes authority',async({page},info)=>{
  const body={...await start(page),role:'first_ad'};
  const call=async(route:string,extra:Record<string,unknown>={})=>{
    const response=await page.request.post('/api/'+route,{data:{...body,...extra}});
    return {status:response.status(),...await response.json()};
  };
  let state=await call('checkpoint');
  await call('approve',{interrupt_id:state.pending_approval.id,approve:false});
  await call('late-take');state=await call('resolve-rights');
  for(const cause of state.causes){
    const f=state.exceptions.find((f:{finding_id:string})=>f.finding_id===cause.finding_id);
    expect((await call('decide',{finding_id:f.finding_id,finding_sha256:f.record_sha256,role:cause.required_role,action:'accept_exception',actor:'Synthetic reviewer',reason:'Reviewed this evidence.'})).status).toBe(200);
  }
  expect((await call('evaluate')).eligible).toBe(true);
  const pending=(await call('wrap')).pending_approval;
  expect((await call('ingest',{kind:'rights_record',document:{record_id:'REL-REFRESH',subject_id:'BG-07',subject_kind:'person',document_type:'background release',scope:'all media',territory:'worldwide',status:'executed'}})).status).toBe(200);
  for(const route of ['approve','wrap'])expect((await call(route,{interrupt_id:pending.id,approve:true})).status).toBe(409);
  await call('approve',{interrupt_id:pending.id,approve:false});
  const fresh=(await call('wrap')).pending_approval;
  expect(fresh.id).not.toBe(pending.id);
  expect((await call('approve',{interrupt_id:fresh.id,approve:true})).wrap_approved).toBe(true);
  const renewed=(await call('wrap')).pending_approval;
  expect((await call('wrap',{interrupt_id:renewed.id,approve:false})).wrap_approved).toBe(false);
  expect((await call('turnover')).message).toContain('Refusing');
  await page.reload();
  await page.getByRole('navigation').getByRole('link',{name:'Handoff',exact:true}).click();
  await expect(page.getByRole('button',{name:'Publish approved turnover'})).toBeDisabled();
  // Every attempt here was accepted, so the panel waits closed behind its title.
  // Open it only if it is closed: a bare click would shut a panel already open.
  const deliveryTitle=page.getByText('Delivery status',{exact:true});
  if(!await deliveryTitle.evaluate(el=>el.closest('details')?.open ?? false))await deliveryTitle.click();
  await expect(page.getByText('Wrap ready: accepted by the event bus')).toBeVisible();
  await info.attach('wrap-review-outcome',{body:JSON.stringify(await call('state')),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('reliability-wrap.png'),fullPage:true});
});

test('LT-OFFLINE reload keeps one scoped draft read-only and reconnect never replays it',async({page,context,request},info)=>{
  const body=await start(page);
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByLabel('Record type').selectOption('rights_record');
  await page.getByLabel('Advanced JSON entry').check();
  const draft=JSON.stringify({record_id:'REL-OFFLINE-DRAFT',subject_id:'BG-07',subject_kind:'person',
    document_type:'background release',scope:'all media',territory:'worldwide',status:'executed'});
  await page.getByLabel('Document JSON').fill(draft);
  await expect(page.getByText(/Unsent draft kept in this tab/)).toBeVisible();

  await page.evaluate(async()=>{
    if(navigator.serviceWorker.controller)return;
    await new Promise<void>((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('service worker did not control the page')),10_000);
      navigator.serviceWorker.addEventListener('controllerchange',()=>{clearTimeout(timer);resolve();},{once:true});
    });
  });

  let browserIngests=0;
  page.on('request',pending=>{if(new URL(pending.url()).pathname==='/api/ingest')browserIngests++;});
  await context.setOffline(true);
  await reloadFromPage(page);
  await expect(page.getByTestId('connectivity-status')).toContainText('Offline');
  await expect(page.getByTestId('connectivity-status')).toContainText('Saved snapshot · read-only');
  await page.getByRole('button',{name:'Add take or release'}).click();
  await expect(page.getByLabel('Document JSON')).toHaveValue(draft);
  await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeDisabled();
  expect(browserIngests).toBe(0);

  const changed=await request.post('/api/ingest',{data:{...body,kind:'rights_record',document:{
    record_id:'REL-OFFLINE-EXTERNAL',subject_id:'BG-07',subject_kind:'person',
    document_type:'background release',scope:'all media',territory:'worldwide',status:'executed',
  }}});
  expect(changed.status()).toBe(200);

  await context.setOffline(false);
  await expect(page.getByRole('heading',{name:'Saved evidence changed since your last confirmed view'})).toBeVisible();
  await expect(page.getByTestId('connectivity-status')).toContainText('Connected');
  await expect(page.getByLabel('Document JSON')).toHaveValue(draft);
  await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeDisabled();
  expect(browserIngests).toBe(0);

  await page.getByRole('button',{name:'I reviewed the current saved revision'}).click();
  await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeEnabled();
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
  expect(browserIngests).toBe(1);
  await info.attach('offline-reconnect',{body:JSON.stringify({run_id:body.run_id,browser_ingest_requests:browserIngests}),contentType:'application/json'});
});
