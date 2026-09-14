// Shared by source Playwright acceptance and the owner-gated production capture.
// Every transition uses the rendered controls and the real same-origin API.
export const heroSceneIds=['hook','surface','trigger','live','sponsor','evidence','close'];
export function assertSceneBudget(id,elapsed,hold) {
  if(!Number.isFinite(hold) || hold<=0 || !Number.isFinite(elapsed) || elapsed<0 || elapsed>hold)throw new Error(`Scene ${id} exceeds or lacks its measured narration slot. Retime this beat; never truncate the workflow.`);
}

export async function downloadBytes(download) {
  const stream=await download.createReadStream();
  if(!stream)throw new Error('The browser did not produce the requested download.');
  const chunks=[];for await(const chunk of stream)chunks.push(chunk);
  return Buffer.concat(chunks);
}

export function heroScenes(page,expect,{requireEventBridgeReceipt=false}={}) {
  let initialDigest,reviewedDigest,loadedTake,withdrawnFinding;
  const nav=async name=>page.getByRole('navigation').getByRole('link',{name,exact:true}).click();
  const backToStart=async()=>{
    await page.locator('a.brand').click();
    await expect(page.getByRole('heading',{name:'Know what still blocks wrap.'})).toBeVisible();
  };
  const waitForServiceWorker=async()=>page.evaluate(async()=>{
    if(navigator.serviceWorker.controller)return;
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('service worker did not control the page')),10_000);
      navigator.serviceWorker.addEventListener('controllerchange',()=>{clearTimeout(timer);resolve();},{once:true});
    });
  });
  const postOutsideBrowser=async(path,body)=>{
    const response=await fetch(new URL(path,page.url()),{
      method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),
    });
    if(!response.ok)throw new Error(`External demo client received HTTP ${response.status} from ${path}`);
    return response.json();
  };
  async function showSubscriberReceipt() {
    await nav('Handoff');
    await expect(page.getByRole('heading',{name:'Handoff'})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Recorded events'})).toBeVisible();
    if(!requireEventBridgeReceipt)return;
    const consumed=page.getByText(/EventBridge subscriber consumed/).first();
    const refresh=page.getByRole('button',{name:'Refresh saved state'});
    const deadline=Date.now()+20_000;
    while(Date.now()<deadline && !await consumed.isVisible().catch(()=>false)){
      await page.waitForTimeout(750);
      const events=page.waitForResponse(response=>response.url().endsWith('/api/events') && response.ok());
      await refresh.click();
      await events;
      await expect(refresh).toBeEnabled();
    }
    await expect(consumed).toBeVisible();
    await consumed.scrollIntoViewIfNeeded();
    await expect(consumed).toBeInViewport();
  }
  async function review(name,role) {
    await page.getByLabel('Demo role').selectOption(role);
    await page.locator('.finding-picker a').filter({hasText:name.replace(' ',' · ')}).click();
    const card=page.getByRole('article',{name,exact:true});
    await card.getByLabel('Your name in this demo').fill('Synthetic reviewer');
    await card.getByLabel('Decision',{exact:true}).selectOption('accept_exception');
    await card.getByLabel('Reason for this exact evidence').fill('Reviewed the supplied sources. Intentional exception for this fictional scene.');
    await card.getByRole('button',{name:'Record decision'}).click();
    await expect(card.getByText(/Recorded: accept exception/)).toBeVisible();
  }
  return {
    hook:async()=>{
      await expect(page.getByRole('heading',{name:'Know what still blocks wrap.'})).toBeVisible();
      await expect(page.getByRole('region',{name:'Start a shoot-day review'})).toContainText('script supervisor and 1st AD');
      await expect(page.getByRole('region',{name:'Start a shoot-day review'})).toContainText('saved editorial turnover');
      await expect(page.getByTestId('execution-mode')).toContainText('Synthetic demo');
    },
    surface:async()=>{
      await nav('Architecture');
      await expect(page.getByRole('heading',{name:'Architecture'})).toBeVisible();
      await expect(page.getByRole('img',{name:/LastTake architecture/})).toBeVisible();
      await expect(page.getByText(/Strands Agents SDK/).first()).toBeVisible();
    },
    trigger:async()=>{
      await backToStart();
      await page.getByRole('button',{name:'Start this fictional shoot day'}).click();
      await expect(page.getByRole('button',{name:'Run wrap checkpoint'})).toBeEnabled();
      await expect(page.getByTestId('workflow-next')).toContainText('Start with the wrap checkpoint');
      await expect(page.locator('.beat .badge').first()).toHaveText('Not assessed');
      await page.getByRole('button',{name:'Run wrap checkpoint'}).click();
      await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
      await expect(page.getByTestId('workflow-next')).toContainText('Review the saved pickup request');
      await expect(page.getByRole('button',{name:'Approve pickup'})).toHaveCount(0);
      await page.getByText('Current package fingerprint · SHA-256',{exact:true}).click();
      initialDigest=await page.locator('.approval-proof code').textContent();
      await showSubscriberReceipt();
    },
    live:async()=>{
      // Record a real decision before changing the source, so withdrawal is visible.
      await nav('Scene review');
      await review('continuity CR-01','script_supervisor');
      withdrawnFinding=await page.getByRole('article',{name:'continuity CR-01',exact:true}).locator('.fine').first().textContent();
      await page.getByLabel('Demo role').selectOption('first_ad');
      await page.reload();
      await expect(page.getByRole('button',{name:'Approve pickup'})).toBeEnabled();
      await page.getByRole('button',{name:'Approve pickup'}).click();
      await expect(page.getByRole('button',{name:'Approve pickup'})).toHaveCount(0);
      await expect(page.getByTestId('wrap-status')).toContainText('Not approved');
    },
    sponsor:async()=>{
      await page.getByRole('button',{name:'Open guided demo'}).click();
      await page.getByRole('button',{name:'Add take or release'}).click();
      await page.getByRole('button',{name:'Try valid take'}).click();
      loadedTake={take_id:await page.getByLabel('Take identifier').inputValue()};
      await expect(page.getByText(/Unsent draft kept in this tab/)).toBeVisible();
      await waitForServiceWorker();
      const body=await page.evaluate(()=>({
        session_id:localStorage.getItem('lasttake.session'),
        run_id:new URLSearchParams(location.hash.split('?')[1]).get('run'),
      }));
      if(!body.session_id || !body.run_id)throw new Error('The video journey lost its owned run identity.');
      let browserIngests=0;
      const observe=request=>{if(new URL(request.url()).pathname==='/api/ingest')browserIngests++;};
      page.on('request',observe);
      await page.context().setOffline(true);
      try {
        await page.reload({waitUntil:'domcontentloaded'});
        await expect(page.getByTestId('connectivity-status')).toContainText('Offline');
        await expect(page.getByTestId('connectivity-status')).toContainText('Saved snapshot · read-only');
        await page.getByRole('button',{name:'Add take or release'}).click();
        await expect(page.getByLabel('Take identifier')).toHaveValue(loadedTake.take_id);
        await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeDisabled();
        await postOutsideBrowser('/api/ingest',{...body,kind:'rights_record',document:{
          record_id:'REL-VIDEO-EXTERNAL',subject_id:'BG-07',subject_kind:'person',
          document_type:'background release',scope:'all media',territory:'worldwide',status:'executed',
        }});
        await page.context().setOffline(false);
        await expect(page.getByRole('heading',{name:'Saved evidence changed since your last confirmed view'})).toBeVisible();
        await expect(page.getByTestId('connectivity-status')).toContainText('Connected');
        await expect(page.getByLabel('Take identifier')).toHaveValue(loadedTake.take_id);
        await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeDisabled();
        await page.getByRole('button',{name:'I reviewed the current saved revision'}).click();
        await expect(page.getByRole('button',{name:'Save evidence & rerun checks'})).toBeEnabled();
        await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
        await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
      } finally {
        await page.context().setOffline(false).catch(()=>{});
        page.off('request',observe);
      }
      if(browserIngests!==1)throw new Error(`Offline recovery sent ${browserIngests} browser ingests; expected exactly one explicit save.`);
      await expect(page.getByText('Slate 42L/1',{exact:true})).toBeVisible();
      await expect(page.getByText(/Earlier decision no longer applies/)).toBeVisible();
      await review('continuity CR-01','script_supervisor');
      await review('metadata T-013','dit');
    },
    evidence:async()=>{
      await page.getByLabel('Demo role').selectOption('first_ad');
      await page.getByRole('button',{name:'Review wrap readiness'}).click();
      await page.getByRole('button',{name:'Request wrap approval'}).click();
      await expect(page.getByRole('button',{name:'Approve wrap'})).toBeEnabled();
      await expect(page.getByText('Wrap decision saved by the server',{exact:true})).toHaveCount(0);
      await page.reload();
      await page.getByText('Current package fingerprint · SHA-256',{exact:true}).click();
      reviewedDigest=await page.locator('.approval-proof code').textContent();
      expect(reviewedDigest).toMatch(/^[a-f0-9]{64}$/);
      expect(reviewedDigest).not.toBe(initialDigest);
      await page.getByRole('button',{name:'Approve wrap'}).click();
      await expect(page.getByText('Wrap decision saved by the server',{exact:true})).toBeVisible();
      await expect(page.getByTestId('workflow-next')).toContainText('Prepare the editorial handoff');
    },
    close:async()=>{
      await nav('Handoff');
      await page.getByRole('button',{name:'Publish approved turnover'}).click();
      await expect(page.getByRole('button',{name:'Download turnover',exact:true})).toBeVisible();
      await page.reload();
      await page.getByText('Inspect saved manifest',{exact:true}).click();
      const manifest=JSON.parse(await page.locator('details').filter({has:page.getByText('Inspect saved manifest',{exact:true})}).locator('pre').textContent());
      expect(manifest.package_revision_digest).toBe(reviewedDigest);
      expect(manifest.wrap_approved_by.role).toBe('first_ad');
      expect(manifest.source_manifest.length).toBeGreaterThan(0);
      expect(manifest.human_decisions.filter(d=>d.finding_id===withdrawnFinding).length).toBeGreaterThanOrEqual(2);
      const downloading=page.waitForEvent('download');
      await page.getByRole('button',{name:'Download turnover',exact:true}).click();
      expect(JSON.parse((await downloadBytes(await downloading)).toString('utf8'))).toEqual(manifest);
      const summaryDownloading=page.waitForEvent('download');
      await page.getByRole('button',{name:'Download handoff summary'}).click();
      const summary=(await downloadBytes(await summaryDownloading)).toString('utf8');
      const recommendations=manifest.outstanding_and_accepted_exceptions.filter(f=>typeof f.recommended_action==='string' && f.recommended_action.length>0);
      expect(recommendations.length).toBeGreaterThan(0);
      for(const finding of recommendations)expect(summary).toContain(`Next: ${finding.recommended_action}`);
      expect(summary).toContain(manifest.record_sha256);
      await page.getByLabel('Receipt purpose').selectOption('wrap');
      await page.getByRole('button',{name:'Prepare receipt'}).click();
      await expect(page.getByRole('heading',{name:'Receipt ready for review'})).toBeVisible();
      const receiptDownload=page.waitForEvent('download');
      await page.getByRole('button',{name:'Download receipt',exact:true}).click();
      const receipt=JSON.parse((await downloadBytes(await receiptDownload)).toString('utf8'));
      expect(receipt.package_revision_digest).toBe(reviewedDigest);
      expect(receipt.approved_by.role).toBe('first_ad');
      expect(receipt.still_open_count).toBeGreaterThan(0);
      expect(receipt.record_sha256).toMatch(/^[a-f0-9]{64}$/);
      await page.getByText('Read editorial handoff summary',{exact:true}).click();
      await expect(page.getByRole('region',{name:'Turnover for this run'})).toContainText(loadedTake.take_id);
      return {run_id:manifest.run_id,package_revision_digest:reviewedDigest,turnover_sha256:manifest.record_sha256,receipt_sha256:receipt.record_sha256};
    },
  };
}
