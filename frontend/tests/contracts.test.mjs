import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {checkAudit} from '../scripts/check-audit.mjs';
import {validateReceipt, assess} from '../public/acceptance.js';
import {assertSceneBudget,heroSceneIds} from '../../web/video/hero-journey.mjs';

test('capture uses the complete CI-exercised journey and refuses a truncated or unmeasured beat',async()=>{
  const spec=JSON.parse(await readFile('../video/narration.json','utf8'));
  assert.deepEqual(spec.segments.map(segment=>segment.id),heroSceneIds);
  assert.equal(spec.recording_status,'NOT_CONFIGURED');
  for(const segment of spec.segments){
    assert.ok(segment.captionText.length>=20);
    assert.ok(segment.speechText.length>=20);
  }
  const trigger=spec.segments.find(segment=>segment.id==='trigger');
  assert.match(trigger.captionText,/scene\.wrap-checkpoint\.requested/);
  assert.match(trigger.captionText,/34 required beats: 31 covered with evidence, 2 exceptions.+1 missing release/);
  assert.match(trigger.speechText,/scene dot wrap checkpoint dot requested/);
  assert.match(trigger.speechText,/thirty-four required beats: thirty-one covered with evidence/);
  assert.notEqual(trigger.captionText,trigger.speechText);
  const sponsor=spec.segments.find(segment=>segment.id==='sponsor');
  assert.match(sponsor.captionText,/JSON/);
  assert.match(sponsor.speechText,/J S O N/);
  assert.doesNotThrow(()=>assertSceneBudget('evidence',900,1000));
  for(const hold of [undefined,NaN,Infinity,0,-1,899])assert.throws(()=>assertSceneBudget('evidence',900,hold),/never truncate/);
  assert.throws(()=>assertSceneBudget('evidence',NaN,1000));
  const capture=await readFile('../web/video/capture-production.mjs','utf8');
  assert.match(capture,/heroScenes\(page,/);
  assert.match(capture,/assertSceneBudget\(id,elapsed,holds\[id\]\)/);
});

test('public proof refuses malformed, missing, stale, mismatched and broadened results', async () => {
  const fixture = JSON.parse(await readFile('proof-tests/receipt.fixture.json', 'utf8'));
  const now = Date.parse('2026-09-10T06:00:00Z');
  const release = {commit: fixture.frontend_commit};
  const health = {commit: fixture.backend_commit, ok: true, run_state_store: 'aurora-dsql'};
  assert.equal(assess(release, health, fixture, structuredClone(fixture), now, release.commit).status, 'CURRENT_AUTOMATED_PASS');
  assert.equal(assess(release, health, fixture, fixture, now, 'd'.repeat(40)).status, 'UNKNOWN');
  assert.equal(assess(release, health, fixture, fixture, now).status, 'UNKNOWN');
  assert.equal(assess(release, health, null, null, now, release.commit).status, 'PENDING');
  assert.equal(assess({}, health, fixture, fixture, now, release.commit).status, 'UNKNOWN');
  assert.equal(assess(release, health, fixture, fixture, now + 25 * 3600000, release.commit).status, 'HISTORICAL');
  assert.equal(assess(release, health, fixture, fixture, now - 6 * 60000, release.commit).status, 'UNKNOWN');
  assert.equal(assess({commit: 'd'.repeat(40)}, health, fixture, fixture, now, 'd'.repeat(40)).status, 'HISTORICAL');
  assert.equal(assess(release, {...health, commit: 'd'.repeat(40)}, fixture, fixture, now, release.commit).status, 'HISTORICAL');
  for (const patch of [{human_uat: 'PASS'}, {workflow_status: 'success'}, {run_url: 'javascript:alert(1)'},
    {schema_version: 2}, {raw_data: 'private'}, {postflight: 'failure'}, {receipt_path: '/../secret'}, {retry_count: 1},
    {backend_commit: null}, {preflight_at: 'tomorrow'}, {preflight_at: '2026-02-30T06:00:00Z', observed_at: '2026-02-30T06:01:00Z'}, {totals: {tests: 0, passed: 0, failed: 0, skipped: 0}},
    {totals: {tests: 19, passed: 19, failed: 0, skipped: 0}}, {totals: {tests: 24, passed: 24, failed: 0, skipped: 1}}]) {
    assert.throws(() => validateReceipt({...fixture, ...patch}));
    assert.equal(assess(release, health, {...fixture, ...patch}, fixture, now, release.commit).status, 'UNKNOWN');
  }
  assert.equal(assess(release, health, fixture, null, now, release.commit).status, 'UNKNOWN');
  assert.equal(assess(release, health, fixture, {...fixture, totals: {tests: 22, passed: 22, failed: 0, skipped: 0}}, now, release.commit).status, 'UNKNOWN');
});

test('public proof assets ship under existing CSP without a built-in success receipt', async () => {
  const html = await readFile('dist/acceptance.html', 'utf8');
  assert.match(html, /src="\/acceptance.js"/);
  assert.match(html, /href="\/acceptance.css"/);
  assert.match(html, /data-testid="acceptance-status">PENDING/);
  assert.doesNotMatch(html, /<script(?![^>]*src=)[^>]*>/);
  assert.equal(await readFile('dist/acceptance.js', 'utf8'), await readFile('public/acceptance.js', 'utf8'));
  assert.ok(!(await readdir('dist')).includes('acceptance.json'));
  const book = JSON.parse(await readFile('UAT.testbook.json', 'utf8'));
  assert.equal(book.current_public_proof.url, 'https://d3kf6hquzlli8g.cloudfront.net/acceptance.html');
  assert.match(await readFile('UAT.testbook.html', 'utf8'), /href="\/acceptance.html"/);
});

test('product wave retains exact-release freshness and independent human gates in both testbooks',async()=>{
  const book=JSON.parse(await readFile('UAT.testbook.json','utf8'));
  const html=await readFile('UAT.testbook.html','utf8');
  for(const id of ['UX-LT-10S','QA-LT-FRESH']){
    assert.equal(book.cases.filter(row=>row.id===id).length,1);
    assert.ok(html.includes(`id="${id}"`));
    assert.equal(book.cases.find(row=>row.id===id).human_signoff,'NOT_RUN');
  }
  assert.match(book.product_wave_20260912.human_requirement,/independent first-time user/);
  assert.match(book.product_wave_20260912.human_requirement,/C3/);
  const fixture=JSON.parse(await readFile('proof-tests/receipt.fixture.json','utf8'));
  const release={commit:fixture.frontend_commit};
  const health={commit:fixture.backend_commit,ok:true,run_state_store:'aurora-dsql'};
  const observed=Date.parse(fixture.observed_at);
  assert.equal(assess(release,health,fixture,structuredClone(fixture),observed+23*3600000,release.commit).status,'CURRENT_AUTOMATED_PASS');
  assert.equal(assess(release,health,fixture,structuredClone(fixture),observed+24*3600000+1,release.commit).status,'HISTORICAL');
  assert.equal(assess({...release,commit:'e'.repeat(40)},health,fixture,fixture,observed,'e'.repeat(40)).status,'HISTORICAL');
});

function assertWorkspaceEvidence(book) {
  const revision=book.current_workspace_revision;
  assert.ok(['PENDING_CI','AUTOMATION_PASS'].includes(revision.status));
  assert.equal(revision.human_signoff,'NOT_RUN');
  if(revision.status==='AUTOMATION_PASS'){
    assert.equal(revision.scope,'CI_REAL_HTTP_ONLY');
    assert.equal(revision.live_aws_acceptance,'NOT_RUN');
    assert.match(revision.implementation_sha,/^[0-9a-f]{40}$/);
    assert.match(revision.ci_run_url,/^https:\/\/github\.com\/upgradedev\/lasttake-aws\/actions\/runs\/[1-9][0-9]*$/);
    assert.equal(revision.evidence_artifact,'frontend-evidence-'+revision.implementation_sha);
    assert.equal(revision.screenshots_artifact,'ui-screenshots-'+revision.implementation_sha);
  }
  for(const id of ['LT-DASH','LT-SELECT','LT-OFFLINE','LT-COCKPIT']){
    const row=book.cases.find(item=>item.id===id);
    assert.ok(row,id);assert.ok(row.observed_result_evidence.startsWith(revision.status));
    if(revision.status==='AUTOMATION_PASS'){
      assert.ok(row.observed_result_evidence.includes(revision.implementation_sha));
      assert.ok(row.observed_result_evidence.includes(revision.ci_run_url));
    }
  }
}

test('audit gate fails closed on runtime findings and unavailable reports',()=>{
  const clean={auditReportVersion:2,vulnerabilities:{},metadata:{vulnerabilities:{info:0,low:0,moderate:0,high:0,critical:0,total:0}}};
  assert.doesNotThrow(()=>checkAudit(clean,clean));
  const low={...clean,vulnerabilities:{example:{severity:'low'}},metadata:{vulnerabilities:{...clean.metadata.vulnerabilities,low:1,total:1}}};
  assert.throws(()=>checkAudit(clean,low),/zero vulnerabilities/);
  assert.throws(()=>checkAudit({...clean,error:{code:'EAUDITNOLOCK'}},clean),/unavailable/);
  assert.throws(()=>checkAudit(clean,{}),/malformed/);
  assert.throws(()=>checkAudit(clean,{...clean,vulnerabilities:low.vulnerabilities}),/zero vulnerabilities/);
});
test('the landing scene preview is generated from the corpus bytes, states no assessment, and says it is fictional',async()=>{
  const preview=JSON.parse(await readFile('dist/scene-preview.json','utf8'));
  const script=JSON.parse(await readFile('../corpus/script_revision.json','utf8'));
  const takes=JSON.parse(await readFile('../corpus/takes.json','utf8'));
  assert.equal(preview.schema,'lasttake/scene-preview/v1');
  assert.equal(preview.required_beats,script.beats.filter(b=>b.required).length);
  assert.equal(preview.optional_beats,script.beats.filter(b=>!b.required).length);
  assert.equal(preview.supplied_takes,takes.takes.length);
  assert.equal(preview.scene_id,script.scene_id);
  assert.equal(preview.opening_beats.length,5);
  assert.equal(preview.opening_beats[0].beat_id,script.beats.find(b=>b.required).beat_id);
  assert.match(preview.synthetic_notice,/fictional/i);
  // A preview is facts about supplied records. It must not carry anything that
  // reads as a result: no covered count, no eligibility, no exception count.
  for(const key of ['covered_with_evidence','raising_exceptions','without_release_record','eligible','counts','headline'])assert.ok(!Object.hasOwn(preview,key),key);
});
test('static build is real React with same-origin API and no HTML proxy',async()=>{
  const index=await readFile('dist/index.html','utf8');
  assert.match(index,/\/assets\/.*\.js/);
  const files=await readdir('src');
  for(const name of files.filter(n=>n.endsWith('.tsx'))){const source=await readFile(`src/${name}`,'utf8');assert.doesNotMatch(source,/<iframe|dangerouslySetInnerHTML/);}
});
test('UAT testbook keeps required evidence and human signoff fields',async()=>{
  const book=JSON.parse(await readFile('UAT.testbook.json','utf8'));
  for(const row of book.cases){for(const key of ['id','persona','requirement','preconditions','steps','expected_outcome','negative_recovery_case','automation_mapping','observed_result_evidence','human_signoff'])assert.ok(Object.hasOwn(row,key),`${row.id}: ${key}`);assert.equal(row.human_signoff,'NOT_RUN');}
  assert.match(await readFile('UAT.testbook.html','utf8'),/NOT_RUN/);
  assertWorkspaceEvidence(book);
  assert.match(book.aws_release.scope,/HISTORICAL_RELEASE_ONLY/);
  const html=await readFile('UAT.testbook.html','utf8');
  assert.ok(html.includes(book.current_workspace_revision.status));
  if(book.current_workspace_revision.status==='AUTOMATION_PASS'){
    assert.ok(html.includes(book.current_workspace_revision.implementation_sha));
    assert.ok(html.includes(book.current_workspace_revision.ci_run_url));
  }
});
test('workspace evidence accepts pending work but refuses incomplete or broadened pass claims',async()=>{
  const book=JSON.parse(await readFile('UAT.testbook.json','utf8'));
  const pending=structuredClone(book);
  pending.current_workspace_revision={status:'PENDING_CI',human_signoff:'NOT_RUN'};
  for(const row of pending.cases.filter(row=>['LT-DASH','LT-SELECT','LT-OFFLINE','LT-COCKPIT'].includes(row.id)))row.observed_result_evidence='PENDING_CI';
  assert.doesNotThrow(()=>assertWorkspaceEvidence(pending));
  for(const patch of [{status:'PASS_AUTOMATED_AWS'},{implementation_sha:'future-head'},{ci_run_url:''},{scope:'LIVE_AWS'},{live_aws_acceptance:'PASS'},{human_signoff:'PASS'},{evidence_artifact:'unrelated'}]){
    assert.throws(()=>assertWorkspaceEvidence({...book,current_workspace_revision:{...book.current_workspace_revision,status:'AUTOMATION_PASS',...patch}}));
  }
});
