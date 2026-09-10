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

export function heroScenes(page,expect) {
  let initialDigest,reviewedDigest,loadedTake,withdrawnFinding;
  const nav=async name=>page.getByRole('navigation').getByRole('link',{name,exact:true}).click();
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
      await expect(page.getByTestId('workflow-next')).toContainText('Start with the wrap checkpoint');
      await expect(page.getByTestId('execution-mode')).toContainText('Synthetic demo');
      await expect(page.locator('.beat .badge').first()).toHaveText('Not assessed');
    },
    surface:async()=>{
      await page.locator('.take summary').first().click();
      await expect(page.getByRole('table').first()).toBeVisible();
    },
    trigger:async()=>{
      await page.getByRole('button',{name:'Run wrap checkpoint'}).click();
      await expect(page.getByRole('button',{name:'Refresh saved state'})).toBeEnabled();
      await expect(page.getByTestId('workflow-next')).toContainText('Review the saved pickup request');
      await expect(page.getByRole('button',{name:'Approve pickup'})).toHaveCount(0);
      await page.getByText('Current package fingerprint · SHA-256',{exact:true}).click();
      initialDigest=await page.locator('.approval-proof code').textContent();
    },
    live:async()=>{
      // Record a real decision before changing the source, so withdrawal is visible.
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
      await nav('Workspace');
      await page.getByRole('button',{name:'Open guided demo'}).click();
      await page.getByRole('button',{name:'Add take or release'}).click();
      await page.getByRole('button',{name:'Try valid take'}).click();
      // Reuse the editable product example as an ordinary local file, without
      // supplying any session/run authority inside the document.
      const downloading=page.waitForEvent('download');
      await page.getByRole('button',{name:'Download input JSON'}).click();
      const bytes=await downloadBytes(await downloading);
      loadedTake=JSON.parse(bytes.toString('utf8'));
      await page.getByLabel('Load a JSON record file').setInputFiles({name:'fictional-take.json',mimeType:'application/json',buffer:bytes});
      await expect(page.getByLabel('Document JSON')).toHaveValue(/camera_report_row/);
      await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
      await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
      await expect(page.getByText('Slate 42L/1',{exact:true})).toBeVisible();
      await expect(page.getByText(/Earlier decision no longer applies/)).toBeVisible();
      await page.getByRole('button',{name:'Add take or release'}).click();
      await page.getByLabel('Record type').selectOption('rights_record');
      await page.getByRole('button',{name:'Fill synthetic example'}).click();
      await page.getByRole('button',{name:'Save evidence & rerun checks'}).click();
      await expect(page.getByRole('heading',{name:'Add evidence to this shoot day'})).toBeHidden();
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
      await nav('History');
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
