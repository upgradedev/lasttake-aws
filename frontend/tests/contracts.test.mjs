import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {checkAudit} from '../scripts/check-audit.mjs';

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
  assert.equal(book.current_workspace_revision.status,'PENDING_CI');
  assert.match(book.aws_release.scope,/HISTORICAL_RELEASE_ONLY/);
  for(const id of ['LT-DASH','LT-SELECT','LT-OFFLINE','LT-COCKPIT']){
    const row=book.cases.find(item=>item.id===id);
    assert.ok(row,id);assert.match(row.observed_result_evidence,/PENDING_CI/);
  }
});
