import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {DeliveryStatus} from '../src/DeliveryStatus';
import {Intake} from '../src/Intake';
import {History} from '../src/History';
import {decisionFor,makeDocument} from '../src/model';
import {finding,state,scene,session,receipt} from './fixtures';

it('latest authorized decision wins even when stale, reversed or revoked',()=>{
  const old={decision_id:'a',finding_id:finding.finding_id,action:'accept_exception',actor:'Sue',role:'script_supervisor' as const,reason:'Intent',finding_sha256:finding.record_sha256,at:'2026-09-01'};
  const latest={...old,decision_id:'b',action:'confirm',finding_sha256:'changed',at:'2026-09-02'};
  expect(decisionFor(finding,[latest,old])).toEqual({decision:latest,stale:true});
  expect(decisionFor(finding,[old,{...latest,role:'editorial'}]).decision).toEqual(old);
  expect(decisionFor(finding,[old,{...latest,finding_sha256:finding.record_sha256}]).decision?.action).toBe('confirm');
});

it('missing report never becomes an invented second source',async()=>{
  const submit=vi.fn().mockResolvedValue(false),user=userEvent.setup();
  render(<Intake scene={scene} busy={false} guided onSubmit={submit} onClose={vi.fn()}/>);
  await user.click(screen.getByRole('button',{name:'Try valid take'}));
  await user.click(screen.getByLabelText('No independent camera report supplied'));
  expect(screen.getByLabelText('Reported media identifier')).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
  expect(submit).toHaveBeenCalledWith('take',expect.objectContaining({take_id:'T-900',camera_report_row:null}));
  const form=new FormData();form.set('camera_report_missing','on');
  expect(makeDocument('take',form).camera_report_row).toBeNull();
});

it('three editable examples keep refusal and correction on the real submit path',async()=>{
  const submit=vi.fn().mockResolvedValue(false),user=userEvent.setup();
  render(<Intake scene={scene} busy={false} guided onSubmit={submit} onClose={vi.fn()}/>);
  await user.click(screen.getByRole('button',{name:'Try refused date'}));
  expect(submit).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
  expect(submit).toHaveBeenLastCalledWith('rights_record',expect.objectContaining({record_id:'REL-EDITABLE',expires_on:'2026-02-30'}));
  expect((screen.getByLabelText('Document JSON') as HTMLTextAreaElement).value).toContain('2026-02-30');
  await user.click(screen.getByRole('button',{name:'Try corrected date'}));
  await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
  expect(submit).toHaveBeenLastCalledWith('rights_record',expect.objectContaining({record_id:'REL-EDITABLE',expires_on:'2030-02-28'}));
});

it('delivery never treats pending or unknown as success and only offers definite rejection retry',async()=>{
  const act=vi.fn().mockResolvedValue(false),user=userEvent.setup();
  const base={event_type:'wrap.ready',accepted:false,reference:'attempt',detail:'Saved bus response',retry_supported:true};
  const current={...state,delivery_outcomes:['pending','unknown','rejected','accepted'].map(status=>({...base,status,accepted:status==='accepted',idempotency_key:status}))};
  const {rerender}=render(<DeliveryStatus state={current} role="editorial" busy={false} act={act}/>);
  expect(screen.getByRole('button',{name:'Retry rejected delivery'})).toBeDisabled();
  expect(screen.getAllByText(/Do not resend/)).toHaveLength(2);
  expect(screen.getByText('wrap.ready: Bus accepted')).toBeVisible();
  rerender(<DeliveryStatus state={current} role="first_ad" busy={false} act={act}/>);
  await user.click(screen.getByRole('button',{name:'Retry rejected delivery'}));
  expect(act).toHaveBeenCalledOnce();
  expect(act).toHaveBeenCalledWith('retry-delivery',{role:'first_ad',idempotency_key:'rejected'});
});

it('portable human-readable summary can be downloaded without manufacturing new evidence',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({receipt:{...receipt,human_readable:'Saved sources. Human time unknown. Hash is not truth.'}})}));
  vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:evidence'),revokeObjectURL:vi.fn()}));
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  render(<History state={state} session={session} events={[]} role="dit" busy={false} act={vi.fn()} handle={async work=>{await work();return true;}}/>);
  fireEvent.click(screen.getByRole('button',{name:'Prepare receipt'}));
  const download=await screen.findByRole('button',{name:'Download evidence summary'});
  fireEvent.click(download);expect(click).toHaveBeenCalledOnce();
  expect(screen.getByText('Saved sources. Human time unknown. Hash is not truth.')).toBeVisible();
});

it("saved turnover warns when only its review authority changes",()=>{
  const current={...state,turnover:{package_revision_digest:state.package_revision_digest},turnover_current:false};
  render(<History state={current} session={session} events={[]} role="first_ad" busy={false} act={vi.fn()} handle={async work=>{await work();return true;}}/>);
  expect(screen.getByText(/approval\/review is no longer current/)).toBeVisible();
  expect(screen.getByRole("button",{name:"Download turnover"})).toBeEnabled();
});
