// Reprocess one already-spent artifact as inert JSON/bytes. Never starts a browser/server.
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {readJSON,sha256,sealSnapshot} from './hero-measurement.mjs';
const [input,output]=process.argv.slice(2).map(path=>resolve(path));
assert.ok(input&&output,'Spent input and new output directories required');
const manifest=readJSON(join(input,'manifest.json'));
assert.equal(manifest.schema,'lasttake/source-measurement-files/v1');
const files=readdirSync(input).filter(file=>file!=='manifest.json').sort();
assert.deepEqual(files,Object.keys(manifest.sha256).sort());
for(const file of files){
  assert.match(file,/^[a-zA-Z0-9_.-]+$/);
  assert.equal(sha256(readFileSync(join(input,file))),manifest.sha256[file],`Original hash: ${file}`);
}
const identity=readJSON(join(input,'identity.json'));
assert.equal(identity.commit,'faf7f17128549155cda7144fdd1cd560c0f0a5c5');
assert.equal(identity.preregistration,'19ef0723a4d240bcb4e79e93dc58c9ca9366a3cb');
assert.equal(identity.run_url,'https://github.com/upgradedev/lasttake-aws/actions/runs/34481212393');
assert.equal(String(identity.run_attempt),'1');
const processResult=readJSON(join(input,'process.json'));
assert.equal(processResult.exit,0);assert.equal(processResult.reason,'PROCESS_EXIT');
const original=readJSON(join(input,'summary.json'));
assert.deepEqual(original.counts,{PASSED:20,FAILED:0,INCOMPLETE:0,NOT_RUN:0});
const replay=sealSnapshot(input,output,'ALREADY_SPENT_REPLAY_NOT_A_NEW_COHORT');
const {limits:oldLimits,...oldStatistics}=original;
const {limits:newLimits,...newStatistics}=replay;
assert.deepEqual(newStatistics,oldStatistics,'Replayed statistics and denominators must not change');
assert.match(newLimits,/response-body bytes UNKNOWN/);
for(const file of [...files,'manifest.json'])assert.deepEqual(readFileSync(join(output,'captured',file)),readFileSync(join(input,file)));
const finalManifest=readJSON(join(output,'manifest.json'));
for(const [file,hash] of Object.entries(finalManifest.sha256))assert.equal(sha256(readFileSync(join(output,file))),hash,`Final hash: ${file}`);
console.log(JSON.stringify({scope:'SPENT_DATA_REPLAY_ONLY',original_run:34481212393,original_artifact:10154044857,
  original_files_verified:files.length,final_files_verified:Object.keys(finalManifest.sha256).length,
  counts:replay.counts,overall:replay.overall,unchanged_raw_slots:20,new_measured_attempts:0}));
