import {test,expect} from '@playwright/test';
// Dynamic URL loads the same dependency-free JS journey used by production capture.
const source=await import(new URL('../../../web/video/hero-journey.mjs',import.meta.url).href);

test('LT-HERO complete capture source: changed evidence, human wrap decision and exact turnover downloads',async({page},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
  await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
  const scenes=source.heroScenes(page,expect);
  let result;
  for(const id of source.heroSceneIds){
    await test.step(id,async()=>{result=await scenes[id]();});
    await page.screenshot({path:info.outputPath(`hero-${id}.png`),fullPage:true});
  }
  expect(errors).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
  await info.attach('hero-saved-records',{body:JSON.stringify(result),contentType:'application/json'});
});

test('LT-FILE ordinary JSON files remain owned, editable and durable; missing camera evidence stays missing',async({page},info)=>{
  await page.goto('/');await page.getByRole('button',{name:'New shoot-day run',exact:true}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  const body=await page.evaluate(()=>({session_id:localStorage.getItem('lasttake.session'),run_id:new URLSearchParams(location.hash.split('?')[1]).get('run')}));
  const readState=async()=>await (await page.request.post('/api/state',{data:body})).json();
  const before=await readState();
  const choose=async(text:string,name='take.json')=>page.getByLabel('Load a JSON record file').setInputFiles({name,mimeType:'application/json',buffer:Buffer.from(text)});
  await choose('{');
  await expect(page.getByLabel('Document JSON')).toHaveValue('{');
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('alert')).toContainText('valid JSON');
  await choose('{"take_id":"T-file"}');
  await expect(page.getByLabel('Document JSON')).toHaveValue('{"take_id":"T-file"}');
  const refusal=page.waitForResponse(r=>r.url().endsWith('/api/ingest'));
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  expect((await refusal).status()).toBe(400);
  await expect(page.getByLabel('Document JSON')).toHaveValue('{"take_id":"T-file"}');
  expect((await readState()).package_revision_digest).toBe(before.package_revision_digest);
  await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Try valid take'}).click();
  await page.getByLabel('No independent camera report supplied').check();
  const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'Download input JSON'}).click();
  const document=JSON.parse((await source.downloadBytes(await downloading)).toString('utf8'));
  document.take_id='T-file';expect(document.camera_report_row).toBeNull();
  await choose(JSON.stringify(document));
  await expect(page.getByLabel('Document JSON')).toHaveValue(/T-file/);
  // File contents never confer session ownership, even if the record is valid.
  const foreign=await (await page.request.post('/api/session',{data:{}})).json();
  for(const session_id of [undefined,foreign.session_id]){
    const response=await page.request.post('/api/ingest',{data:{run_id:body.run_id,session_id,kind:'take',document}});
    expect(response.status()).toBe(403);
  }
  expect((await readState()).package_revision_digest).toBe(before.package_revision_digest);
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
  await page.reload();await expect(page.getByRole('button',{name:'Add take or release'})).toBeEnabled();
  const saved=await readState();
  expect(saved.exceptions.find((f:{requirement_id:string;check_type:string})=>f.requirement_id==='T-file'&&f.check_type==='metadata').truth_state).toBe('missing');
  await page.getByRole('button',{name:'Add take or release'}).click();await choose(JSON.stringify(document));
  await expect(page.getByLabel('Document JSON')).toHaveValue(/T-file/);
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('alert')).toContainText('already');
  expect((await readState()).package_revision_digest).toBe(saved.package_revision_digest);
  await info.attach('ordinary-file-refusals',{body:JSON.stringify({run_id:body.run_id,missing_report:true,foreign_denied:true,duplicate_refused:true}),contentType:'application/json'});
});
