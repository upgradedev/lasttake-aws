import {it,expect,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {nextStep,WorkflowNext} from '../src/WorkflowNext';
import {CopyText,turnoverIsCurrent,turnoverSummary,Turnover} from '../src/Turnover';
import {parseEvidenceDocument,readEvidenceFile,EVIDENCE_FILE_LIMIT} from '../src/evidenceFile';
import {Intake} from '../src/Intake';
import {History} from '../src/History';
import {scene,state,session,receipt} from './fixtures';

it('next step follows server state through checkpoint, changed evidence, approval and turnover',()=>{
  const clear={...state,pending_approval:null};
  expect(nextStep({...clear,counts:null}).title).toContain('checkpoint');
  expect(nextStep({...clear,needs_checkpoint:true}).title).toContain('checkpoint');
  expect(nextStep(clear).title).toContain('evidence gaps');
  expect(nextStep({...clear,eligible:true}).title).toContain('separate wrap decision');
  expect(nextStep({...clear,eligible:true,wrap_approved:true}).page).toBe('history');
  expect(nextStep({...clear,turnover:{}}).title).toContain('Read the turnover');
  expect(nextStep({...state,pending_approval:{...state.pending_approval!,evidence_changed:true}}).detail).toContain('must be declined');
  const {rerender}=render(<WorkflowNext state={state}/>);
  expect(screen.getByRole('link')).toHaveAttribute('href',expect.stringContaining('filter=approval'));
  rerender(<WorkflowNext state={{...clear,turnover:{}}}/>);
  expect(screen.getByRole('link')).toHaveTextContent('Open turnover & receipts');
});

it('file intake accepts one editable object and refuses unsupported or oversized files',async()=>{
  expect(parseEvidenceDocument('{"take_id":"fictional"}')).toEqual({take_id:'fictional'});
  for(const text of ['null','[]','42','"text"','{'])expect(()=>parseEvidenceDocument(text)).toThrow();
  const file={name:'TAKE.JSON',size:30,text:async()=>'{"take_id":"fictional"}'} as File;
  expect(await readEvidenceFile(file)).toContain('fictional');
  await expect(readEvidenceFile({...file,name:'report.pdf'} as File)).rejects.toThrow('.json');
  await expect(readEvidenceFile({...file,size:EVIDENCE_FILE_LIMIT+1} as File)).rejects.toThrow('64 KiB');
});

it('file loading does not submit, rejected input remains editable and the user explicitly saves',async()=>{
  const submit=vi.fn().mockResolvedValue(false),user=userEvent.setup();
  render(<Intake scene={scene} busy={false} guided={false} onSubmit={submit} onClose={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText('Load a JSON record file'),{target:{files:[{name:'take.json',size:20,text:async()=>'{"take_id":"file"}'}]}});
  expect(await screen.findByLabelText('Document JSON')).toHaveValue('{"take_id":"file"}');
  expect(submit).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
  expect(submit).toHaveBeenCalledWith('take',{take_id:'file'});
  expect(screen.getByLabelText('Document JSON')).toHaveValue('{"take_id":"file"}');
  fireEvent.change(screen.getByLabelText('Load a JSON record file'),{target:{files:[{name:'scan.pdf',size:20}]}});
  expect(await screen.findByRole('alert')).toHaveTextContent('.json');
  expect(screen.getByLabelText('Document JSON')).toHaveValue('{"take_id":"file"}');
});

it('input download preserves independent camera disagreement and refuses invalid JSON',async()=>{
  const blobs:Blob[]=[];
  vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn((b:Blob)=>{blobs.push(b);return 'blob:test';}),revokeObjectURL:vi.fn()}));
  vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  const user=userEvent.setup();render(<Intake scene={scene} busy={false} guided onSubmit={vi.fn()} onClose={vi.fn()}/>);
  await user.click(screen.getByRole('button',{name:'Try valid take'}));
  fireEvent.change(screen.getByLabelText('Reported lens (mm)'),{target:{value:'85'}});
  await user.click(screen.getByRole('button',{name:'Download input JSON'}));
  expect(blobs).toHaveLength(1);
  const downloaded=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsText(blobs[0]);});
  expect(JSON.parse(downloaded)).toMatchObject({lens_mm:50,camera_report_row:{lens_mm:85}});
  await user.click(screen.getByLabelText('Advanced JSON entry'));
  fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{'}});
  await user.click(screen.getByRole('button',{name:'Download input JSON'}));
  expect(screen.getByRole('alert')).toHaveTextContent('valid JSON');
  expect(blobs).toHaveLength(1);
});

const manifest={run_id:state.run_id,scene_id:scene.scene_id,script_revision:scene.revision,generated_at:'2026-09-10',schema:'lasttake/turnover/v2',policy_version:'1',package_revision_digest:state.package_revision_digest,record_sha256:'seal',wrap_approved_by:{actor:'Synthetic AD',role:'first_ad'},outstanding_and_accepted_exceptions:[{requirement_id:'B-17',required_role:'dit',observation:'Mismatch',recommended_action:'Review original camera report'}],source_manifest:[{artifact_id:'camera-report',sha256:'source-digest'}],beat_to_take_map:[{beat_id:'B-17',slug:'Reaction',takes:[{take_id:'T-file',slate:'42L/1',media_id:'MEDIA',timecode_in:'00:00'}]},{beat_id:'B-18',takes:[]}],synthetic_corpus_notice:'Fictional production',rights_disclaimer:'Counsel determines legal sufficiency.'};
it('handoff includes source provenance and retained exceptions, without modifying the saved manifest',()=>{
  const current={...state,eligible:true,wrap_approved:true,turnover:manifest};
  const before=JSON.stringify(manifest),text=turnoverSummary(current);
  expect(text).toContain('T-file / slate 42L/1');expect(text).toContain('camera-report | source-digest');
  expect(text).toContain('Review original camera report');expect(text).toContain('not separately sealed');
  expect(turnoverIsCurrent(current)).toBe(true);
  for(const patch of [{wrap_approved:false},{eligible:false},{turnover_current:false},{package_revision_digest:'changed'}]){
    expect(turnoverSummary({...current,...patch})).toContain('HISTORICAL');
  }
  expect(turnoverSummary({...current,turnover:{}})).toContain('Unknown');
  expect(turnoverSummary({...current,turnover:{...manifest,outstanding_and_accepted_exceptions:[{...manifest.outstanding_and_accepted_exceptions[0],recommended_action:null}]}})).toContain('Next: Unknown');
  expect(JSON.stringify(manifest)).toBe(before);
});

it('copy succeeds or offers selectable plain text when clipboard permission is unavailable',async()=>{
  const user=userEvent.setup();const write=vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:write}});
  render(<CopyText text={'<script>inert text</script>\nSource digest'} label="Copy summary"/>);
  await user.click(screen.getByRole('button',{name:'Copy summary'}));
  expect(write).toHaveBeenCalledWith('<script>inert text</script>\nSource digest');
  expect(screen.getByRole('status')).toHaveTextContent('Copied.');
  write.mockRejectedValue(new DOMException('Denied'));
  await user.click(screen.getByRole('button',{name:'Copy summary'}));
  expect(screen.getByRole('status')).toHaveTextContent('Clipboard unavailable');
  fireEvent.focus(screen.getByLabelText('Selectable copy text'));
  expect(screen.getByLabelText('Selectable copy text')).toHaveValue('<script>inert text</script>\nSource digest');
  expect(document.querySelector('script')).toBeNull();
});

it('turnover controls preserve the approval guard and download the saved summary',()=>{
  const publish=vi.fn();vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:test'),revokeObjectURL:vi.fn()}));
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  const {rerender}=render(<Turnover state={state} busy={false} publish={publish}/>);
  expect(screen.getByRole('button',{name:'Publish approved turnover'})).toBeDisabled();
  rerender(<Turnover state={{...state,wrap_approved:true,eligible:true}} busy={false} publish={publish}/>);
  fireEvent.click(screen.getByRole('button',{name:'Publish approved turnover'}));expect(publish).toHaveBeenCalledOnce();
  rerender(<Turnover state={{...state,turnover:manifest,wrap_approved:true,eligible:true}} busy={false} publish={publish}/>);
  fireEvent.click(screen.getByRole('button',{name:'Download handoff summary'}));expect(click).toHaveBeenCalledOnce();
  expect(screen.getByText('Current for observed evidence and approval')).toBeVisible();
});

it('a refreshed decision labels an already prepared receipt historical without overwriting it',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({receipt})}));
  const props={session,events:[],role:'dit' as const,busy:false,act:vi.fn(),handle:async(work:()=>Promise<void>)=>{await work();return true;}};
  const {rerender}=render(<History {...props} state={state}/>);
  fireEvent.click(screen.getByRole('button',{name:'Prepare receipt'}));
  await screen.findByRole('heading',{name:'Receipt ready for review'});
  rerender(<History {...props} state={{...state,package_revision_digest:'changed'}}/>);
  await waitFor(()=>expect(screen.getByText(/prepared receipt is historical/)).toBeVisible());
  expect(screen.getByRole('button',{name:'Download receipt'})).toBeEnabled();
});
