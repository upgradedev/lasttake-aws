import {test,expect,type Page} from '@playwright/test';

async function nav(page:Page,name:string){await page.getByRole('navigation').getByRole('link',{name,exact:true}).click();}
async function saved(page:Page){return page.evaluate(()=>({session_id:localStorage.getItem('lasttake.session'),run_id:new URLSearchParams(location.hash.split('?')[1]).get('run')}));}
async function create(page:Page){await page.goto('/');await page.getByRole('button',{name:'New shoot-day run',exact:true}).click();await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();}

test('LT-HISTORY bounded pages retain older owned runs, stale cursors recover without deleting history',async({page},info)=>{
  await create(page);
  const body=await saved(page);
  const observed=await page.request.post('/api/state',{data:body});
  expect(observed.status()).toBe(200);
  const backend=(await observed.json()).run_state_store;
  expect(['local-files','s3','aurora-dsql']).toContain(backend);
  for(let i=0;i<11;i++)expect((await page.request.post('/api/reset',{data:{session_id:body.session_id}})).ok()).toBe(true);
  await page.goto(`/#history?run=${body.run_id}`);
  await page.getByRole('button',{name:'Refresh newest runs'}).click();
  await expect(page.locator('.run-list li')).toHaveCount(10);
  await expect(page.getByRole('button',{name:'Load older runs'})).toBeEnabled();
  const first=await (await page.request.post('/api/session',{data:{session_id:body.session_id}})).json();
  expect(first.runs).toHaveLength(10);expect(first.has_more).toBe(true);
  const other=await (await page.request.post('/api/session',{data:{}})).json();
  expect((await page.request.post('/api/session',{data:{session_id:other.session_id,cursor:first.next_cursor}})).status()).toBe(400);
  await page.getByRole('button',{name:'Load older runs'}).click();
  await expect(page.locator('.run-list li')).toHaveCount(2);
  await expect(page.locator('.run-list')).toContainText(body.run_id!);
  await expect(page.getByRole('button',{name:'Load older runs'})).toBeDisabled();
  await page.locator('.run-list a').first().click();
  await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
  await page.reload();
  await expect(page.locator('.run-list li')).toHaveCount(10);
  // Observe the real adapter: appending invalidates fallback versions, not DSQL keysets.
  const appended=await page.request.post('/api/reset',{data:{session_id:body.session_id}});
  expect(appended.status()).toBe(200);
  const appendedRun=(await appended.json()).run_id;
  expect(typeof appendedRun).toBe('string');expect(appendedRun).toBeTruthy();
  const olderResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/session' && Boolean(response.request().postDataJSON()?.cursor));
  await page.getByRole('button',{name:'Load older runs'}).click();
  const older=await olderResponse;
  if(backend==='aurora-dsql'){
    expect(older.status()).toBe(200);
    expect((await older.json()).runs).toHaveLength(2);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.locator('.run-list li')).toHaveCount(2);
    await expect(page.locator('.run-list')).toContainText(body.run_id!);
    await expect(page.getByRole('button',{name:'Load older runs'})).toBeDisabled();
  }else{
    expect(older.status()).toBe(409);
    await expect(page.getByRole('alert')).toContainText('Saved history changed');
    await expect(page.locator('.run-list li')).toHaveCount(10);
  }
  await expect(page.locator('.run-list')).not.toContainText(appendedRun);
  await page.getByRole('button',{name:'Refresh newest runs'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('.run-list li')).toHaveCount(10);
  await expect(page.locator('.run-list')).toContainText(appendedRun);
  await page.getByRole('button',{name:'Load older runs'}).click();
  await expect(page.locator('.run-list li')).toHaveCount(3);
  await expect(page.locator('.run-list')).toContainText(body.run_id!);
  await expect(page.locator('.run-list')).not.toContainText(appendedRun);
  await expect(page.getByRole('button',{name:'Load older runs'})).toBeDisabled();
  expect((await page.request.post('/api/state',{data:body})).ok()).toBe(true);
  await info.attach('history-backend-contract',{body:JSON.stringify({run_state_store:backend,old_cursor_status:older.status(),initial_page:10,initial_older:2,refreshed_page:10,refreshed_older:3}),contentType:'application/json'});
});

test('LT-DASH scoped metrics drill into matching evidence, and desktop/mobile cockpit captures are reviewable',async({page},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await create(page);await nav(page,'Dashboard');
  if(info.project.name==='mobile'){
    const role=await page.getByLabel('Demo role').boundingBox();
    expect(role!.width).toBeGreaterThanOrEqual(200);
  }
  await expect(page.getByTestId('metric-coverage')).toContainText('Not assessed');
  await expect(page.getByTestId('metric-exceptions')).toContainText('Not assessed');
  await expect(page.getByTestId('metric-releases')).toContainText('Not assessed');
  await expect(page.getByTestId('metric-eligibility')).toContainText('Not assessed');
  await expect(page.getByTestId('metric-approval')).toContainText('Not approved');
  await page.getByRole('button',{name:'Run wrap checkpoint'}).click();
  await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
  const body=await saved(page);
  const current=await (await page.request.post('/api/state',{data:body})).json();
  const scene=await (await page.request.post('/api/scene',{data:body})).json();
  await expect(page.getByTestId('metric-coverage').locator('strong')).toHaveText(String(current.counts.covered_with_evidence));
  await expect(page.getByTestId('metric-exceptions').locator('strong')).toHaveText(String(new Set(current.exceptions.map((f:{finding_id:string})=>f.finding_id)).size));
  await expect(page.getByTestId('metric-releases').locator('strong')).toHaveText(String(current.counts.without_release_record));
  await expect(page.getByTestId('metric-takes').locator('strong')).toHaveText(String(scene.take_count));
  await expect(page.getByTestId('metric-eligibility')).toContainText('Blocked');
  const brief=page.getByTestId('workflow-next');
  await expect(brief.getByTestId('decision-headline')).toHaveText('Wrap blocked by the supplied evidence');
  await expect(brief).toContainText(current.causes[0].reason);
  await expect(brief.getByRole('heading',{name:'Why wrap is blocked'})).toBeVisible();
  const positions=await page.evaluate(()=>({decision:document.querySelector('.decision-brief')!.getBoundingClientRect().top,metrics:document.querySelector('.metrics')!.getBoundingClientRect().top}));
  expect(positions.decision).toBeLessThan(positions.metrics);
  await page.reload();
  await expect(brief.getByTestId('decision-headline')).toHaveText('Wrap blocked by the supplied evidence');
  await page.screenshot({path:info.outputPath('product-wave-blocked-return.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:info.outputPath('dashboard-success.png'),fullPage:true});
  await page.getByTestId('metric-coverage').click();
  await expect(page.getByLabel('Show')).toHaveValue('covered');
  await expect(page.locator('.beat')).toHaveCount(current.counts.covered_with_evidence);
  await page.goBack();await expect(page.getByTestId('metric-releases')).toBeVisible();
  await page.getByTestId('metric-releases').click();
  await expect(page.locator('.beat')).toHaveCount(current.counts.without_release_record);
  await page.goBack();await page.getByTestId('metric-exceptions').click();
  await expect(page.locator('.finding-picker a')).toHaveCount(current.exceptions.length);
  const continuity=current.exceptions.find((f:{check_type:string})=>f.check_type==='continuity');
  await page.locator('.finding-picker a').filter({hasText:'continuity · '+continuity.requirement_id}).click();
  await expect(page.getByRole('article',{name:'continuity '+continuity.requirement_id,exact:true})).toBeVisible();
  expect(await page.locator('.beat.selected').first().evaluate(row=>{
    const list=row.closest('.pane-scroll')!.getBoundingClientRect();
    const beat=row.getBoundingClientRect();
    return beat.top>=list.top && beat.top<list.bottom;
  })).toBe(true);
  if(info.project.name==='desktop')await expect(page.locator('.beat.selected').first()).toBeInViewport();
  await page.getByRole('link',{name:'02 Evidence'}).click();
  await expect(page.getByRole('region',{name:'Evidence and exceptions'})).toBeFocused();
  await page.getByText('Source records & digests',{exact:true}).click();
  for(const source of continuity.sources)await expect(page.getByRole('region',{name:'Evidence and exceptions'})).toContainText(source.artifact_id);
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:info.outputPath('workspace-success.png'),fullPage:true});
  await expect(page.getByTestId('wrap-status')).toContainText('Not approved');
  if(info.project.name==='desktop')await expect(page.getByTestId('wrap-status')).toBeInViewport();
  else {await page.getByRole('link',{name:'03 Decision'}).click();await expect(page.getByTestId('wrap-status')).toBeInViewport();}
  await info.attach('current-scene-evidence',{body:JSON.stringify({run:body.run_id,scene:scene.scene_id,counts:current.counts,selected_finding:continuity.finding_id}),contentType:'application/json'});
  expect(errors).toEqual([]);
});

test('LT-SELECT bidirectional source selection, unmatched advisory and Records search survive back and reload',async({page})=>{
  await create(page);await page.getByRole('button',{name:'Run wrap checkpoint'}).click();await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
  const body=await saved(page);
  const current=await (await page.request.post('/api/state',{data:body})).json();
  const scene=await (await page.request.post('/api/scene',{data:body})).json();
  const continuity=current.exceptions.find((f:{check_type:string})=>f.check_type==='continuity');
  const beat=scene.beats.find((b:{continuity_ref:string})=>b.continuity_ref===continuity.requirement_id);
  await page.locator('#beat-'+beat.beat_id+' .beat-link').click();
  await expect(page.locator('.finding-picker a[aria-current=true]')).toContainText(continuity.requirement_id);
  await page.getByRole('link',{name:beat.beat_id+' · Page '+beat.page+', line '+beat.line,exact:true}).click();
  await page.reload();await expect(page.locator('#beat-'+beat.beat_id+' .beat-link')).toHaveAttribute('aria-current','location');
  await page.getByRole('link',{name:'Inspect in Records'}).click();
  await expect(page.getByRole('region',{name:'Record inspector'})).toContainText(continuity.observation);
  await page.getByLabel('Record type').selectOption('takes');
  await page.getByLabel('Search records').pressSequentially('T-013');
  await expect(page.getByLabel('Search records')).toHaveValue('T-013');
  await expect(page.getByLabel('Search records')).toBeFocused();
  await page.getByRole('region',{name:'Source records'}).getByRole('link').click();
  await page.reload();await expect(page.getByLabel('Search records')).toHaveValue('T-013');
  await expect(page.getByRole('region',{name:'Record inspector'})).toContainText('T-013');
  await nav(page,'Workspace');
  await expect(page.getByLabel('Show')).toHaveValue('all');
  await expect(page.locator('.beat')).toHaveCount(scene.beats.length);
  await page.goBack();await expect(page.getByLabel('Search records')).toHaveValue('T-013');
  await nav(page,'Workspace');await page.getByRole('link',{name:'Show all',exact:true}).click();
  await page.locator('.finding-picker a').filter({hasText:'Shot plan advisory'}).click();
  await expect(page.getByText(/Unmatched source:/)).toBeVisible();
  await expect(page.locator('.beat-link[aria-current=location]')).toHaveCount(0);
  await page.reload();await expect(page.getByText(/Unmatched source:/)).toBeVisible();
});

test('LT-OFFLINE transport outage freezes decisions, preserves the run and recovers without retrying a write',async({page,context})=>{
  await create(page);await page.getByRole('button',{name:'Run wrap checkpoint'}).click();await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
  await page.locator('.finding-picker a').filter({hasText:'continuity · CR-01'}).click();
  const run=(await saved(page)).run_id;
  let writes=0;page.on('request',request=>{if(/\/api\/(decide|approve|wrap|ingest)$/.test(request.url()))writes++;});
  await context.setOffline(true);
  await page.getByRole('button',{name:'Refresh saved state'}).click();
  await expect(page.getByRole('alert')).toContainText('Displayed evidence may be out of date');
  await expect(page.getByTestId('decision-headline')).toHaveText('Refresh before deciding');
  await expect(page.getByRole('button',{name:'Record decision'})).toBeDisabled();
  await context.setOffline(false);
  await page.getByRole('button',{name:'Retry loading saved state'}).click();
  await expect(page.getByRole('button',{name:'Record decision'})).toBeEnabled();
  await expect(page.getByTestId('decision-headline')).toHaveText('Wrap blocked by the supplied evidence');
  expect((await saved(page)).run_id).toBe(run);expect(writes).toBe(0);
});
