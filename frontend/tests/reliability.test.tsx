import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within} from '@testing-library/react';
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
  expect(screen.getByText('Wrap ready: accepted by the event bus')).toBeVisible();
  rerender(<DeliveryStatus state={current} role="first_ad" busy={false} act={act}/>);
  await user.click(screen.getByRole('button',{name:'Retry rejected delivery'}));
  expect(act).toHaveBeenCalledOnce();
  expect(act).toHaveBeenCalledWith('retry-delivery',{role:'first_ad',idempotency_key:'rejected'});
});

it('delivery status waits closed when every attempt was accepted and keeps raw identifiers in each row detail',()=>{
  const accepted={event_type:'pickup.requested',status:'accepted',accepted:true,reference:'d0d933cf-1159-4284-a601-a3cb3ed05846',detail:'appended to events.jsonl',retry_supported:true,idempotency_key:'pickup'};
  render(<DeliveryStatus state={{...state,delivery_outcomes:[accepted,{...accepted,event_type:'turnover.generated',reference:'turnover-reference',idempotency_key:'turnover'}]}} role="first_ad" busy={false} act={vi.fn()}/>);
  const title=screen.getByText('Delivery status',{exact:true});
  expect(title.tagName).toBe('SUMMARY');
  expect(title.closest('details')).not.toHaveAttribute('open');
  expect(screen.getByText(/Bus acceptance records an API response, not matched-target delivery or completion\./)).not.toBeVisible();
  expect(screen.getByText('Pickup request: accepted by the event bus',{exact:true})).not.toBeVisible();
  expect(screen.getByText('Turnover generated: accepted by the event bus',{exact:true})).toBeInTheDocument();
  expect(screen.queryByText(/Bus accepted|pickup\.requested:/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Retry rejected delivery'})).not.toBeInTheDocument();
  const row=within(screen.getByText('Pickup request: accepted by the event bus',{exact:true}).closest('li')!);
  const detail=row.getByText('Event type and reference',{exact:true}).closest('details')!;
  expect(detail).not.toHaveAttribute('open');
  expect(within(detail).getByText('pickup.requested',{exact:true})).toBeInTheDocument();
  expect(within(detail).getByText('appended to events.jsonl',{exact:true})).toBeInTheDocument();
  expect(within(detail).getByText('d0d933cf-1159-4284-a601-a3cb3ed05846',{exact:true})).toBeInTheDocument();
});

it('delivery status words every attempt outcome plainly and keeps a heading when nothing was sent',()=>{
  const base={accepted:false,reference:'ref',detail:'Saved bus response',retry_supported:false};
  const rows=[{...base,event_type:'turnover.generated',status:'rejected',idempotency_key:'a'},{...base,event_type:'pickup.requested',status:'pending',idempotency_key:'b'},{...base,event_type:'finding.recorded',status:'unknown',idempotency_key:'c'},{...base,event_type:'rights.record.updated',status:'timed_out',idempotency_key:'d'},{...base,event_type:'wrap.ready',status:'accepted',accepted:true,idempotency_key:'e'}];
  const {rerender}=render(<DeliveryStatus state={{...state,delivery_outcomes:rows}} role="first_ad" busy={false} act={vi.fn()}/>);
  expect(screen.getByText('Delivery status',{exact:true}).closest('details')).toHaveAttribute('open');
  for(const title of ['Turnover generated: rejected by the event bus','Pickup request: no response recorded yet','Finding notification: outcome unknown','Rights record updated: status timed out'])expect(screen.getByText(title,{exact:true})).toBeVisible();
  expect(screen.queryByText('Wrap ready: accepted by the event bus')).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Retry rejected delivery'})).not.toBeInTheDocument();
  rerender(<DeliveryStatus state={state} role="first_ad" busy={false} act={vi.fn()}/>);
  expect(screen.getByRole('heading',{name:'Delivery status'})).toBeVisible();
  expect(screen.getByText(/No consequential delivery or failed notification is recorded/)).toBeVisible();
  expect(document.querySelector('details')).toBeNull();
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
  expect(screen.getByText(/The wrap approval this turnover relied on is no longer current/)).toBeVisible();
  expect(screen.getByRole("button",{name:"Download turnover"})).toBeEnabled();
});
