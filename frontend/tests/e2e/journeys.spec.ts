import {test,expect,type Page} from '@playwright/test';

async function fresh(page:Page){
  await page.goto('/');
  await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
  await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
  const badges=page.locator('.beat .badge');
  await expect(badges.first()).toHaveText('Not assessed');
  expect((await badges.allTextContents()).every(text=>text==='Not assessed')).toBe(true);
  await page.getByRole('button',{name:'Run wrap checkpoint'}).click();
  await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
  await expect(page.getByText(/Of 34 required beats/).first()).toBeVisible();
}
async function navigate(page:Page,name:string){const labels:Record<string,string>={'Scene workspace':'Scene review','My actions':'Scene review','Overview':'Wrap status','Turnovers & history':'Handoff'};await page.getByRole('navigation').getByRole('link',{name:labels[name] ?? name,exact:true}).click();}
async function sample(page:Page,kind:'take'|'rights_record'){
  await navigate(page,'Scene workspace');
  if(await page.getByRole('button',{name:'Open guided demo'}).isVisible())await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByLabel('Record type').selectOption(kind);
  await page.getByRole('button',{name:'Fill synthetic example'}).click();
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
}
async function decide(page:Page,name:string,role:string){
  await page.getByLabel('Demo role').selectOption(role);
  await page.locator('.finding-picker a').filter({hasText:name.replace(' ',' · ')}).click();
  const card=page.getByRole('article',{name,exact:true});
  await card.getByLabel('Your name in this demo').fill('Synthetic reviewer');
  await card.getByLabel('Decision',{exact:true}).selectOption('accept_exception');
  await card.getByLabel('Reason for this exact evidence').fill('Reviewed the supplied records for this fictional scene. Intentional exception.');
  await card.getByRole('button',{name:'Record decision'}).click();
  await expect(card.getByText(/Recorded: accept exception/)).toBeVisible();
}
async function contract(page:Page){return page.evaluate(()=>({session_id:localStorage.getItem('lasttake.session'),run_id:new URLSearchParams(location.hash.split('?')[1]).get('run')}));}

test('LT01 intake validates, persists through reload and refuses duplicate records',async({page},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await fresh(page);
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByLabel('Advanced JSON entry').check();
  await page.getByLabel('Document JSON').fill('{');
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('alert')).toContainText('valid JSON');
  await page.getByLabel('Document JSON').fill('{"take_id":"T-900"}');
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('alert').first()).toContainText('does not match');
  await expect(page.getByLabel('Document JSON')).toHaveValue('{"take_id":"T-900"}');
  await page.getByRole('button',{name:'Close form'}).click();
  await expect(page.getByRole('button',{name:'Add take or release'})).toBeEnabled();
  await sample(page,'take');
  await expect(page.getByText('Slate 42L/1',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByText('Slate 42L/1',{exact:true})).toBeVisible();
  const body=await contract(page);
  const response=await page.request.post('/api/scene',{data:body});
  const scene=await response.json();expect(scene.take_count).toBe(41);
  await sampleOpen(page);
  await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
  await expect(page.getByRole('alert')).toContainText('already');
  expect(errors).toEqual([]);
  await info.attach('intake-persisted',{body:JSON.stringify({run_id:body.run_id,take_count:scene.take_count}),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('intake.png'),fullPage:true});
});
async function sampleOpen(page:Page){
  if(await page.getByRole('button',{name:'Open guided demo'}).isVisible())await page.getByRole('button',{name:'Open guided demo'}).click();
  await page.getByRole('button',{name:'Add take or release'}).click();
  await page.getByRole('button',{name:'Fill synthetic example'}).click();
}

test('LT02 changed evidence withdraws the exact prior decision and requires new review',async({page},info)=>{
  await fresh(page);await navigate(page,'My actions');
  await decide(page,'continuity CR-01','script_supervisor');
  await sample(page,'take');await navigate(page,'My actions');
  const card=page.getByRole('article',{name:'continuity CR-01',exact:true});
  await expect(card.getByText(/Earlier decision no longer applies/)).toBeVisible();
  await page.reload();await expect(card.getByText(/Earlier decision no longer applies/)).toBeVisible();
  await decide(page,'continuity CR-01','script_supervisor');
  await expect(card.getByText(/Earlier decision no longer applies/)).toHaveCount(0);
  await page.screenshot({path:info.outputPath('new-evidence-new-review.png'),fullPage:true});
});

test('LT03 saved Strands approval resumes, retry acts once, then approved turnover and role receipts travel',async({page},info)=>{
  // Against the live URL this journey took 59.6s (desktop) and 1.0m (mobile) in the
  // accepted run 34755986941, and 66.9s on desktop in run 34768420634 (JUnit time),
  // where mobile was never reached. Mobile on this UI is an ESTIMATE of 67-86s: 66.9s
  // times the mobile/desktop ratios measured for this test (about 1.0 live, 1.11 and
  // 1.29 in source CI). That is 4-23s under the 90s file default, so this test gets
  // twice the default. Every assertion keeps its own 20s expect timeout.
  test.setTimeout(180_000);
  await fresh(page);await navigate(page,'My actions');
  await expect(page.getByRole('button',{name:'Approve pickup'})).toHaveCount(0);
  await page.getByLabel('Demo role').selectOption('first_ad');
  await page.reload();await expect(page.getByRole('button',{name:'Approve pickup'})).toBeVisible();
  const body=await contract(page);
  const before=await (await page.request.post('/api/state',{data:body})).json();
  await page.getByRole('button',{name:'Approve pickup'}).click();
  await expect(page.getByRole('button',{name:'Approve pickup'})).toHaveCount(0);
  await page.request.post('/api/approve',{data:{...body,interrupt_id:before.pending_approval.id,approve:true,role:'first_ad'}});
  const events=await (await page.request.post('/api/events',{data:body})).json();
  expect(events.events.filter((e:{event_type:string})=>e.event_type==='pickup.requested')).toHaveLength(1);
  await sample(page,'take');await sample(page,'rights_record');
  await navigate(page,'My actions');
  await decide(page,'continuity CR-01','script_supervisor');
  await decide(page,'metadata T-013','dit');
  await page.getByLabel('Demo role').selectOption('first_ad');
  await page.getByRole('button',{name:'Review wrap readiness'}).click();
  await page.getByRole('button',{name:'Request wrap approval'}).click();
  await expect(page.getByTestId('wrap-decision-scope')).toContainText('For SC-042, script');
  await expect(page.getByTestId('wrap-decision-scope')).toContainText('does not publish it');
  await expect(page.getByTestId('wrap-decision-scope')).toContainText('Declining leaves wrap unapproved');
  await expect(page.getByText('Wrap decision saved by the server',{exact:true})).toHaveCount(0);
  await page.getByText('Current package fingerprint · SHA-256',{exact:true}).click();
  const reviewedFingerprint=await page.locator('.approval-proof code').textContent();
  expect(reviewedFingerprint).toMatch(/^[a-f0-9]{64}$/);
  await page.getByRole('button',{name:'Approve wrap'}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText(/1st AD wrap decision is on record/)).toBeVisible();
  await expect(page.getByText('Wrap decision saved by the server',{exact:true})).toBeVisible();
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('.approval-check')).toHaveCSS('animation-name','none');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('wrap-command-center.png'),fullPage:true});
  await navigate(page,'Turnovers & history');
  await page.getByRole('button',{name:'Publish approved turnover'}).click();
  await expect(page.getByRole('button',{name:'Download turnover'})).toBeVisible();
  await page.reload();await expect(page.getByRole('button',{name:'Download turnover'})).toBeVisible();
  await page.getByLabel('Demo role').selectOption('script_supervisor');
  await page.getByRole('button',{name:'Prepare receipt'}).click();
  await expect(page.getByRole('heading',{name:'Receipt ready for review'})).toBeVisible();
  await page.getByLabel('Receipt purpose').selectOption('wrap');
  await page.getByRole('button',{name:'Prepare receipt'}).click();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download receipt'}).click();
  const download=await downloadPromise;await download.saveAs(info.outputPath('wrap-receipt.json'));
  const receipt=await (await page.request.post('/api/receipt',{data:{...body,kind:'wrap'}})).json();
  expect(receipt.receipt.approved_by.role).toBe('first_ad');expect(receipt.receipt.record_sha256).toHaveLength(64);
  expect(receipt.receipt.package_revision_digest).toBe(reviewedFingerprint);
  expect(receipt.receipt.still_open_count).toBeGreaterThan(0);
  const timeline=page.getByRole('region',{name:'Recorded events'});
  await expect(timeline.getByRole('listitem')).toHaveCount(20);
  await expect(timeline.getByRole('status')).toContainText('Events 1–20 of');
  await timeline.getByRole('button',{name:'Older events'}).click();
  await expect(timeline.getByRole('status')).toContainText('Events 21–40 of');
  await timeline.getByRole('button',{name:'Newer events'}).click();
  await expect(timeline.getByRole('status')).toContainText('Events 1–20 of');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('approved-turnover.png'),fullPage:true});
});

test('LT04 rejects caller-invented receipt claims and missing session authority',async({page})=>{
  await fresh(page);
  const body=await contract(page);
  const forged=await page.request.post('/api/receipt',{data:{...body,subject:{caller_assertion:'unchecked'}}});
  expect(forged.status()).toBe(400);
  const denied=await page.request.post('/api/state',{data:{run_id:body.run_id}});
  expect(denied.status()).toBe(403);
});

test('navigation keeps session-owned history and blocked browser storage remains usable',async({page},info)=>{
  await page.addInitScript(()=>{Storage.prototype.getItem=()=>{throw new DOMException('Blocked');};Storage.prototype.setItem=()=>{throw new DOMException('Blocked');};});
  await page.goto('/');
  await expect(page.getByText(/Browser storage is unavailable/)).toBeVisible();
  await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
  await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeVisible();
  await navigate(page,'Overview');await expect(page.getByText('Current saved run')).toBeVisible();
  // A shadow token must not also name an opaque Tailwind shadow-color token.
  await expect(page.locator('.summary.panel')).toHaveCSS('box-shadow',/rgba\(23, 38, 53, 0\.0?8\)/);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('overview.png'),fullPage:true});
});
