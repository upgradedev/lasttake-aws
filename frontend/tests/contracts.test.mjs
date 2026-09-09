import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {checkAudit} from '../scripts/check-audit.mjs';

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
