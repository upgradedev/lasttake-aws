import {test,expect} from '@playwright/test';
// Dynamic URL loads the same dependency-free JS journey used by production capture.
const source=await import(new URL('../../../web/video/hero-journey.mjs',import.meta.url).href);

test('LT-HERO complete capture source: changed evidence, human wrap decision and exact turnover downloads',async({page},info)=>{
  if(info.project.name==='mobile')await page.setViewportSize({width:375,height:812});
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Know what still blocks wrap.'})).toBeVisible();
  const welcome=page.getByRole('region',{name:'Start a shoot-day review'});
  await expect(welcome).toContainText('saved editorial turnover');
  await expect(page.getByText(/For the script supervisor and 1st AD:/)).toBeVisible();
  await expect(page.getByTestId('execution-mode')).toContainText('No footage/audio analysis');
  const start=page.getByRole('button',{name:'Start this fictional shoot day'});
  await expect(start).toBeInViewport({ratio:1});
  const firstAction=await start.boundingBox();
  expect(firstAction).not.toBeNull();
  expect(firstAction!.y).toBeGreaterThanOrEqual(0);
  expect(firstAction!.y+firstAction!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.screenshot({path:info.outputPath('product-wave-cold-viewport.png')});
  // Traverse real tab order from the untouched cold page, including the skip link.
  for(let i=0;i<24 && !await start.evaluate(el=>el===document.activeElement);i++)await page.keyboard.press('Tab');
  await expect(start).toBeFocused();
  await page.screenshot({path:info.outputPath('product-wave-cold-keyboard.png'),fullPage:true});
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
  const scenes=source.heroScenes(page,expect);
  let result:Record<string,string>={};
  for(const id of source.heroSceneIds){
    await test.step(id,async()=>{result=await scenes[id]();});
    await page.screenshot({path:info.outputPath(`hero-${id}.png`),fullPage:true});
  }
  expect(errors).toEqual([]);
  await expect(page.getByTestId('editorial-decision')).toContainText('1st AD');
  const retained=page.getByRole('region',{name:'Retained exceptions for editorial'});
  await expect(retained).toContainText('T-013');
  await expect(retained).toContainText('Next:');
  await page.getByRole('searchbox',{name:'Find beat or take in turnover'}).fill('B-17');
  await expect(page.getByRole('table',{name:'Saved beat-to-take map'})).toContainText('T-900');
  await page.getByRole('searchbox',{name:'Find beat or take in turnover'}).fill('NO-SUCH-SAVED-TAKE');
  await expect(page.getByText('No saved beat or take matches this search.')).toBeVisible();
  await page.getByRole('button',{name:'Clear turnover search'}).click();
  await page.screenshot({path:info.outputPath('product-wave-editorial-completion.png'),fullPage:true});
  await page.context().grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'Copy handoff summary'}).click();
  const copied=await page.evaluate(()=>navigator.clipboard.readText());
  expect(copied).toContain('LASTTAKE | EDITORIAL HANDOFF');
  expect(copied).toContain(result.package_revision_digest);
  expect(copied).toContain('not separately sealed');
  await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new DOMException('Denied');}}});});
  await page.getByRole('button',{name:'Copy handoff summary'}).click();
  await expect(page.getByText(/Clipboard unavailable/)).toBeVisible();
  await expect(page.getByLabel('Selectable copy text')).toHaveValue(copied);
  await page.screenshot({path:info.outputPath('hero-copy-fallback.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
  await info.attach('hero-saved-records',{body:JSON.stringify(result),contentType:'application/json'});
  // A subsequent evidence change must keep the existing turnover historical.
  await page.getByRole('navigation').getByRole('link',{name:'Workspace',exact:true}).click();
  await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByLabel('Record type').selectOption('rights_record');
  await page.getByRole('button',{name:'Fill synthetic example'}).click();
  await page.getByLabel('Record identifier').fill('REL-AFTER-TURNOVER');
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
  await page.getByRole('navigation').getByRole('link',{name:'History',exact:true}).click();
  await page.reload();
  await expect(page.getByTestId('editorial-decision')).toContainText('Historical record');
  await expect(page.getByTestId('workflow-next')).toContainText('Start a new shoot-day run for a new turnover');
  await expect(page.getByRole('button',{name:'Download turnover',exact:true})).toBeEnabled();
  await page.screenshot({path:info.outputPath('product-wave-historical-return.png'),fullPage:true});
  await info.attach('product-wave-source-context',{body:JSON.stringify({source_sha:process.env.GITHUB_SHA ?? 'UNKNOWN',project:info.project.name,run_id:result.run_id,human_uat:'NOT_RUN'}),contentType:'application/json'});
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
