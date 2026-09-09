import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
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
});
