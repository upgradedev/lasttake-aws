import {execFileSync,spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {preallocate,finalize,readJSON,sha256,durableJSON} from './hero-measurement.mjs';
export const preregistration='19ef0723a4d240bcb4e79e93dc58c9ca9366a3cb';
const repository=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const git=(...args)=>execFileSync('git',args,{cwd:repository,encoding:'utf8'}).trim();
export function sourceIdentity(){
  const protocolPath='docs/hero-measurement-protocol.json';
  const protocol=readJSON(join(repository,protocolPath));
  const commit=git('rev-parse','HEAD');
  if(process.env.GITHUB_SHA && process.env.GITHUB_SHA!==commit)throw new Error('Candidate checkout identity mismatch');
  if(commit===preregistration)throw new Error('Instrumentation must follow preregistration');
  git('merge-base','--is-ancestor',preregistration,commit);
  if(git('diff',preregistration,commit,'--',protocolPath))throw new Error('Protocol changed after registration');
  if(git('status','--porcelain','--untracked-files=normal'))throw new Error('Dirty source checkout');
  for(const [path,key] of [['frontend/src','frontend_tree'],['src/lasttake','backend_tree'],['corpus','corpus_tree']]){
    if(git('rev-parse',`${commit}:${path}`)!==protocol.baseline[key])throw new Error('Product baseline changed');
  }
  if(sha256(readFileSync(join(repository,protocol.baseline.helper_path)))!==protocol.baseline.helper_sha256||
    sha256(readFileSync(join(repository,'frontend/package-lock.json')))!==protocol.baseline.frontend_lock_sha256)throw new Error('Helper/lock changed');
  if(Date.parse(protocol.declared_at)>Date.parse(git('show','-s','--format=%cI',preregistration)))throw new Error('Future declaration');
  return {scope:'SOURCE_CI_ONLY',commit,preregistration,protocol_sha256:sha256(readFileSync(join(repository,protocolPath))),protocol,
    node:process.version,platform:process.platform,architecture:process.arch,
    run_url:`https://github.com/upgradedev/lasttake-aws/actions/runs/${process.env.GITHUB_RUN_ID}`,run_attempt:process.env.GITHUB_RUN_ATTEMPT};
}
// Exported so CI negative fixtures can prove a hung child retains a preallocated cohort.
export async function supervise(command,args,{cwd,env,root,timeoutMs}){
  let reason='PROCESS_EXIT';
  const child=spawn(command,args,{cwd,env,stdio:'inherit',detached:process.platform!=='win32'});
  const kill=()=>{try{if(process.platform==='win32')child.kill('SIGKILL');else process.kill(-child.pid,'SIGKILL');}catch{}};
  const timer=setTimeout(()=>{reason='PROCESS_TIMEOUT';kill();},timeoutMs);
  const signal=()=>{reason='PROCESS_CANCELLED';kill();};
  process.once('SIGTERM',signal);process.once('SIGINT',signal);
  const exit=await new Promise(resolveExit=>{child.once('error',()=>resolveExit(-1));child.once('close',code=>resolveExit(code??-1));});
  clearTimeout(timer);process.removeListener('SIGTERM',signal);process.removeListener('SIGINT',signal);
  const summary=finalize(root,reason);
  return {exit,reason,summary};
}
async function main(){
  if(process.env.CI!=='true'||process.env.GITHUB_EVENT_NAME!=='workflow_dispatch')throw new Error('Manual source CI only');
  const root=resolve(repository,'frontend/test-results/hero-benchmark');
  preallocate(root,{scope:'SOURCE_CI_ONLY',status:'IDENTITY_PENDING',preregistration});
  const started=performance.now();
  try{
    const identity=sourceIdentity();durableJSON(join(root,'identity.json'),identity);
    const result=await supervise(process.execPath,['node_modules/@playwright/test/cli.js','test','--config','playwright.benchmark.config.ts','--forbid-only'],{
      cwd:join(repository,'frontend'),root,timeoutMs:identity.protocol.sampling.process_timeout_ms-1000-(performance.now()-started),
      env:{...process.env,LASTTAKE_BENCHMARK_ROOT:root,LASTTAKE_COMMIT_SHA:identity.commit,LASTTAKE_UI_URL:''}});
    durableJSON(join(root,'process.json'),{elapsed_ms:performance.now()-started,exit:result.exit,reason:result.reason});
    finalize(root,result.reason);
    if(result.exit!==0||result.summary.counts.PASSED!==20)process.exitCode=1;
  }catch(error){
    durableJSON(join(root,'process.json'),{elapsed_ms:performance.now()-started,reason:'INSTRUMENT_REFUSAL',failure:error instanceof Error?error.name:'UNKNOWN'});
    finalize(root,'INSTRUMENT_REFUSAL');process.exitCode=1;
  }
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))await main();
