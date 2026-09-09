import {describe,it,expect,vi} from 'vitest';
import {render,screen,within,fireEvent,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {Actions} from '../src/Actions';
import {History} from '../src/History';
import {Intake} from '../src/Intake';
import {SceneView} from '../src/SceneView';
import {scene,state,receipt,session,take,finding} from './fixtures';
const act=()=>vi.fn().mockResolvedValue(true);
describe('scene workspace',()=>{
  it('does not present preliminary beat classifications as assessed evidence',()=>{
    render(<SceneView scene={scene} state={{...state,counts:null,beats:[...state.beats,{beat_id:'B-17',status:'media_identity_exception',reason:'preliminary',basis:'unknown'}]}} selected={null}/>);
    expect(screen.getAllByText('Not assessed',{exact:true})).toHaveLength(scene.beats.length);
    expect(screen.queryByText('covered with evidence',{exact:true})).not.toBeInTheDocument();
    expect(screen.queryByText('media identity exception',{exact:true})).not.toBeInTheDocument();
  });
  it('filters script, opens evidence, inspects conflicting camera metadata',async()=>{const user=userEvent.setup();render(<SceneView scene={scene} state={state} selected={null}/>);expect(screen.getByText('Shot plan advisory')).toBeVisible();await user.click(screen.getByText('Slate 42A/1'));expect(screen.getByRole('table')).toContainHTML('OTHER');await user.selectOptions(screen.getByLabelText('Show'),'exceptions');expect(screen.queryByText('Delphine reacts')).not.toBeInTheDocument();await user.type(screen.getByRole('searchbox'),'missing');expect(screen.getByText(/No beats match/)).toBeVisible();});
  it('keeps unassessed, optional, empty and supplied flags honest',()=>{render(<SceneView scene={{...scene,beats:[{...scene.beats[0],takes:[{...take,preferred:false,usable:false,note:'',camera_report:null}]}]}} state={{...state,counts:null,beats:[]}} selected={'B-01'}/>);expect(screen.getByText(/Run a checkpoint to reconcile/)).toBeVisible();fireEvent.click(screen.getByText('Slate 42A/1'));expect(screen.getByText(/No supervisor note/)).toBeVisible();expect(screen.getAllByText('Missing')).toHaveLength(3);});
  it('shows selected beat context without claiming scene clearance',()=>{render(<SceneView scene={scene} state={state} selected="B-17"/>);expect(screen.getByText(/No exception is associated/)).toBeVisible();expect(screen.getByRole('link',{name:'Show all'})).toHaveAttribute('href',`#scene?run=${state.run_id}`);});
});
describe('human authority',()=>{
  it('renders a saved wrap confirmation only from returned server state, never from a click',async()=>{
    const save=vi.fn().mockResolvedValue(false),user=userEvent.setup();
    const pending={...state,eligible:true,pending_approval:{id:'wrap-1',reason:{kind:'wrap' as const,required_role:'first_ad' as const,note:'Exact package'}}};
    const {rerender}=render(<Actions scene={scene} state={pending} role="first_ad" busy={false} act={save}/>);
    await user.click(screen.getByText('Current package fingerprint · SHA-256'));
    expect(screen.getByText(state.package_revision_digest,{exact:true})).toBeVisible();
    expect(screen.getByText(/not a Merkle proof or an independent browser verification/)).toBeVisible();
    await user.click(screen.getByRole('button',{name:'Approve wrap'}));
    expect(save).toHaveBeenCalledWith('wrap',{interrupt_id:'wrap-1',approve:true,role:'first_ad'});
    expect(screen.queryByText('Wrap decision saved by the server')).not.toBeInTheDocument();
    save.mockResolvedValue(true);
    await user.click(screen.getByRole('button',{name:'Approve wrap'}));
    expect(screen.queryByText('Wrap decision saved by the server')).not.toBeInTheDocument();
    rerender(<Actions scene={scene} state={{...pending,pending_approval:null,wrap_approved:true}} role="first_ad" busy={false} act={save}/>);
    expect(screen.getByRole('status')).toHaveTextContent('Wrap decision saved by the server');
    rerender(<Actions scene={scene} state={pending} role="first_ad" busy={false} act={save}/>);
    expect(screen.queryByText('Wrap decision saved by the server')).not.toBeInTheDocument();
  });
  it('keeps status accents tied to check type and current recorded decisions',()=>{
    const {rerender}=render(<Actions scene={scene} state={state} role="script_supervisor" busy={false} act={act()}/>);
    expect(screen.getByRole('article',{name:'continuity CR-01'})).toHaveAttribute('data-check','continuity');
    expect(screen.getByRole('article',{name:'coverage advisory'})).toHaveAttribute('data-review','open');
    rerender(<Actions scene={scene} state={{...state,decisions:[{decision_id:'d1',finding_id:'f-con',action:'accept_exception',actor:'Sue',role:'script_supervisor',reason:'Intentional',finding_sha256:finding.record_sha256,at:'date'}]}} role="script_supervisor" busy={false} act={act()}/>);
    expect(screen.getByRole('article',{name:'continuity CR-01'})).toHaveAttribute('data-review','recorded');
  });
  it('binds a reasoned decision to the displayed finding digest',async()=>{const save=act();const user=userEvent.setup();render(<Actions scene={scene} state={state} role="script_supervisor" busy={false} act={save}/>);const card=within(screen.getByRole('article',{name:'continuity CR-01'}));await user.type(card.getByLabelText('Your name in this demo'),'Sue');await user.selectOptions(card.getByLabelText('Decision'),'accept_exception');await user.type(card.getByLabelText('Reason for this exact evidence'),'Reviewed intent');await user.click(card.getByRole('button',{name:'Record decision'}));expect(save).toHaveBeenCalledWith('decide',expect.objectContaining({finding_sha256:finding.record_sha256,reason:'Reviewed intent',role:'script_supervisor'}));});
  it('withholds pickup controls from other roles and rights acceptance from everyone',async()=>{render(<Actions scene={scene} state={state} role="production_coordinator" busy={false} act={act()}/>);expect(screen.queryByRole('button',{name:'Approve pickup'})).not.toBeInTheDocument();expect(screen.queryByRole('option',{name:'Accept the documented exception'})).not.toBeInTheDocument();expect(screen.getByText(/cannot accept away/)).toBeVisible();});
  it('lets only the first AD answer a saved pickup or request wrap',async()=>{const save=act();const user=userEvent.setup();const {rerender}=render(<Actions scene={scene} state={state} role="first_ad" busy={false} act={save}/>);await user.click(screen.getByRole('button',{name:'Approve pickup'}));await user.click(screen.getByRole('button',{name:'Decline pickup'}));await user.click(screen.getByRole('button',{name:'Review wrap readiness'}));expect(save).toHaveBeenCalledWith('approve',expect.objectContaining({approve:false,role:'first_ad'}));rerender(<Actions scene={scene} state={{...state,pending_approval:null,eligible:true}} role="first_ad" busy={false} act={save}/>);await user.click(screen.getByRole('button',{name:'Request wrap approval'}));expect(save).toHaveBeenCalledWith('wrap',{role:'first_ad'});});
  it('disables stale wrap approval but allows decline',async()=>{const save=act();render(<Actions scene={scene} state={{...state,pending_approval:{id:'wrap',evidence_changed:true,reason:{kind:'wrap',required_role:'first_ad',note:'Review wrap'}}}} role="first_ad" busy={false} act={save}/>);expect(screen.getByRole('button',{name:'Approve wrap'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Decline wrap'}));expect(save).toHaveBeenCalledWith('wrap',{interrupt_id:'wrap',approve:false,role:'first_ad'});});
  it('keeps withdrawn and accepted exceptions visible, including empty role states',()=>{const decision={decision_id:'d',finding_id:'f-con',action:'accept_exception',actor:'Sue',role:'script_supervisor' as const,reason:'Intent',finding_sha256:'old',at:'date'};const {rerender}=render(<Actions scene={scene} state={{...state,decisions:[decision]}} role="script_supervisor" busy={false} act={act()}/>);expect(screen.getByText(/Earlier decision no longer applies/)).toBeVisible();rerender(<Actions scene={scene} state={{...state,decisions:[{...decision,finding_sha256:finding.record_sha256}]}} role="script_supervisor" busy={true} act={act()}/>);expect(screen.getByText(/Recorded: accept exception by Sue/)).toBeVisible();rerender(<Actions scene={scene} state={{...state,exceptions:[],counts:null,pending_approval:null,wrap_approved:true}} role="editorial" busy={false} act={act()}/>);expect(screen.getByText(/No finding is assigned/)).toBeVisible();expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeDisabled();});
});
describe('intake',()=>{
  it('accepts a labelled synthetic example as a real structured take',async()=>{const submit=act(),close=vi.fn();const user=userEvent.setup();render(<Intake scene={scene} busy={false} guided onSubmit={submit} onClose={close}/>);await user.click(screen.getByRole('button',{name:'Fill synthetic example'}));await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));expect(submit).toHaveBeenCalledWith('take',expect.objectContaining({take_id:'T-900',beat_ids:['B-17'],lens_mm:50,usable:true}));expect(close).toHaveBeenCalled();});
  it('collects a release and preserves values if the server rejects it',async()=>{const submit=vi.fn().mockResolvedValue(false);const user=userEvent.setup();render(<Intake scene={scene} busy={false} guided onSubmit={submit} onClose={vi.fn()}/>);await user.selectOptions(screen.getByLabelText('Record type'),'rights_record');await user.click(screen.getByRole('button',{name:'Fill synthetic example'}));await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));expect(submit).toHaveBeenCalledWith('rights_record',expect.objectContaining({record_id:'REL-900',subject_id:'BG-07',status:'executed'}));expect(screen.getByLabelText('Record identifier')).toHaveValue('REL-900');});
  it('rejects malformed advanced JSON locally and submits repaired JSON',async()=>{const submit=act(),close=vi.fn();const user=userEvent.setup();render(<Intake scene={scene} busy={false} guided={false} onSubmit={submit} onClose={close}/>);expect(screen.queryByRole('button',{name:'Fill synthetic example'})).toBeNull();await user.click(screen.getByLabelText('Advanced JSON entry'));fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{'}});await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));expect(screen.getByRole('alert')).toHaveTextContent('valid JSON');expect(submit).not.toHaveBeenCalled();fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{"take_id":"T-3"}'}});await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));expect(submit).toHaveBeenCalled();await user.click(screen.getByRole('button',{name:'Close form'}));expect(close).toHaveBeenCalled();});
});
describe('history',()=>{
  it('pages every event newest first without changing the original records',async()=>{
    const events=Array.from({length:45},(_,i)=>({event_id:`event-${i}`,event_type:`record.${i}`,occurred_at:new Date(Date.UTC(2026,8,9,0,i)).toISOString(),payload:{index:i}}));
    const original=JSON.stringify(events);
    const user=userEvent.setup();
    const {rerender}=render(<History state={state} session={session} events={events} role="dit" busy={false} act={act()} handle={act()}/>);
    const record=within(screen.getByRole('region',{name:'Recorded events'}));
    expect(record.getByRole('status')).toHaveTextContent('Events 1–20 of 45');
    expect(record.getAllByRole('listitem')).toHaveLength(20);
    expect(record.getAllByRole('listitem')[0]).toHaveTextContent('record 44');
    expect(record.getByRole('button',{name:'Newer events'})).toBeDisabled();
    await user.click(record.getByRole('button',{name:'Older events'}));
    expect(record.getByRole('status')).toHaveTextContent('Events 21–40 of 45');
    expect(record.getAllByRole('listitem')[0]).toHaveTextContent('record 24');
    await user.click(record.getByRole('button',{name:'Older events'}));
    expect(record.getAllByRole('listitem')).toHaveLength(5);
    expect(record.getAllByRole('listitem')[4]).toHaveTextContent('record 0');
    expect(record.getByRole('button',{name:'Older events'})).toBeDisabled();
    await user.click(record.getByRole('button',{name:'Newer events'}));
    expect(record.getByRole('status')).toHaveTextContent('Events 21–40 of 45');
    expect(JSON.stringify(events)).toBe(original);
    rerender(<History state={state} session={session} events={events.slice(0,2)} role="dit" busy={false} act={act()} handle={act()}/>);
    expect(record.getByRole('status')).toHaveTextContent('Events 1–2 of 2');
    expect(record.getAllByRole('listitem')).toHaveLength(2);
  });
  it('prepares role receipt and displays original events and all saved runs',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({receipt})}));const handle=async(work:()=>Promise<void>)=>{await work();return true;};const user=userEvent.setup();render(<History state={state} session={session} events={[{event_id:'e',event_type:'take.captured',occurred_at:'2026-08-19T00:00:00Z',payload:{take_id:'T-1'}}]} role="script_supervisor" busy={false} act={act()} handle={handle}/>);expect(screen.getByRole('button',{name:'Publish approved turnover'})).toBeDisabled();await user.click(screen.getByRole('button',{name:'Prepare receipt'}));expect(await screen.findByText('Receipt ready for review')).toBeVisible();expect(screen.getByText('Review mug.')).toBeVisible();await user.selectOptions(screen.getByLabelText('Receipt purpose'),'wrap');expect(screen.queryByText('Receipt ready for review')).not.toBeInTheDocument();});
  it('shows empty states and allows publication only after approval',()=>{const save=act();const {rerender}=render(<History state={{...state,counts:null}} session={{...session,runs:[]}} events={[]} role="editorial" busy={false} act={save} handle={act()}/>);expect(screen.getByRole('button',{name:'Prepare receipt'})).toBeDisabled();expect(screen.getByText(/No events yet/)).toBeVisible();rerender(<History state={{...state,wrap_approved:true,eligible:true}} session={session} events={[]} role="editorial" busy={false} act={save} handle={act()}/>);fireEvent.click(screen.getByRole('button',{name:'Publish approved turnover'}));expect(save).toHaveBeenCalledWith('turnover');});
  it('downloads persisted historical turnovers without presenting changed evidence as approved',()=>{vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:test'),revokeObjectURL:vi.fn()}));render(<History state={{...state,turnover:{package_revision_digest:'old'}}} session={{...session,runs:[{...session.runs[0],turnover_published:true}]}} events={[]} role="dit" busy={false} act={act()} handle={act()}/>);expect(screen.getByText(/Evidence has changed since this turnover/)).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'Download turnover'}));});
});
