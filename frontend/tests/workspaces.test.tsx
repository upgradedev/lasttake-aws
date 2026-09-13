import {describe,it,expect,vi} from 'vitest';
import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {App} from '../src/App';
import {Dashboard} from '../src/Dashboard';
import {SceneView} from '../src/SceneView';
import {Records} from '../src/Records';
import {Evidence} from '../src/Inspector';
import {ApprovalConsole} from '../src/Actions';
import {link} from '../src/model';
import {finding,scene,state,session,take} from './fixtures';
import type {Delivery,Finding} from '../src/types';

const save=()=>vi.fn().mockResolvedValue(true);
function api(current=state){
  const fetcher=vi.fn(async(url:string)=>({ok:true,json:async()=>url==='/api/session'?session:url==='/api/scene'?scene:url==='/api/events'?{events:[]}:current}));
  vi.stubGlobal('fetch',fetcher);return fetcher;
}
describe('dashboard scope and actions',()=>{
  it('displays six truthful metrics, current run date and deduplicated recent activity',()=>{
    const events=[{event_id:'e1',event_type:'take.captured',occurred_at:'2026-09-09T02:00:00Z',payload:{}}];
    render(<Dashboard scene={scene} state={state} session={session} events={[...events,...events]} busy={false} checkpoint={save()}/>);
    expect(screen.getByRole('region',{name:'Current run metrics'}).querySelectorAll('a')).toHaveLength(6);
    expect(screen.getByTestId('metric-coverage')).toHaveTextContent('1');
    expect(screen.getByTestId('metric-exceptions')).toHaveTextContent('Retained exceptions');
    expect(screen.getByTestId('metric-approval')).toHaveTextContent('Not approved');
    expect(screen.getByRole('region',{name:'Recent activity'}).querySelectorAll('li')).toHaveLength(1);
    expect(screen.getByText(/Saved runs repeat/)).toBeVisible();
    expect(screen.getByRole('link',{name:/Pickup request waiting/})).toHaveAttribute('href',link('scene',state.run_id,undefined,{filter:'approval'}));
  });
  it('shows unchecked and date-unavailable states and enables the actual checkpoint',()=>{
    const checkpoint=save();
    const {rerender}=render(<Dashboard scene={scene} state={{...state,counts:null,headline:null,pending_approval:null}} session={null} events={[]} busy={false} checkpoint={checkpoint}/>);
    expect(screen.getByText(/Run date unavailable/)).toBeVisible();expect(screen.getByText(/No events recorded/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'Run wrap checkpoint'}));expect(checkpoint).toHaveBeenCalledOnce();
    rerender(<Dashboard scene={scene} state={{...state,counts:null}} session={session} events={[]} busy checkpoint={checkpoint}/>);
    expect(screen.getByRole('button',{name:'Run wrap checkpoint'})).toBeDisabled();
  });
  it('distinguishes blockers, absent findings and stale saved wrap requests',()=>{
    const causes=Array.from({length:7},(_,i)=>({finding_id:i===0?null:'f-'+i,requirement_id:'B-'+i,reason:'Reason '+i,required_role:'dit' as const}));
    const pending={id:'w',evidence_changed:true,reason:{kind:'wrap' as const,required_role:'first_ad' as const,note:'review'}};
    const {rerender}=render(<Dashboard scene={scene} state={{...state,causes,pending_approval:pending}} session={session} events={[]} busy={false} checkpoint={save()}/>);
    expect(screen.getByText('Review all 7 eligibility causes')).toBeVisible();
    expect(screen.getByText(/Evidence changed; review again/)).toBeVisible();
    expect(screen.getByRole('region',{name:'Priority work'}).querySelectorAll('li')).toHaveLength(6);
    rerender(<Dashboard scene={scene} state={{...state,causes:[],pending_approval:null}} session={session} events={[]} busy={false} checkpoint={save()}/>);
    expect(screen.getByText(/returned no causes/)).toBeVisible();
    expect(screen.queryByText(/No current eligibility blockers/)).toBeNull();
    rerender(<Dashboard scene={scene} state={{...state,causes:[],pending_approval:null,eligible:true}} session={session} events={[]} busy={false} checkpoint={save()}/>);
    expect(screen.getByText(/No current eligibility blockers/)).toBeVisible();
  });
});
describe('source inspector and scene mapping',()=>{
  it('inspects take records with all linked beat identities and searches only visible fields',async()=>{
    const user=userEvent.setup();
    const {rerender}=render(<Records scene={scene} state={state} selection={{filter:'takes',record:'T-1'}}/>);
    expect(screen.getByRole('table')).toHaveTextContent('OTHER');
    expect(screen.getByText(/No audio-drop or waveform/)).toBeVisible();
    expect(screen.getByRole('link',{name:'B-01 · Page 41, line 3'})).toHaveAttribute('href',link('scene',state.run_id,'B-01'));
    rerender(<Records scene={scene} state={state} selection={{filter:'takes',q:'no-match'}}/>);
    expect(screen.getByText('No records match this search.')).toBeVisible();
    await user.selectOptions(screen.getByLabelText('Record type'),'script');
    expect(location.hash).toContain('filter=script');
  });
  it('inspects required and optional script records without inventing assessments',()=>{
    const {rerender}=render(<Records scene={scene} state={state} selection={{filter:'script',record:'B-01'}}/>);
    expect(screen.getByText('Continuity reference: CR-01')).toBeVisible();expect(screen.getByRole('link',{name:'Review beat & findings'})).toHaveAttribute('href',link('scene',state.run_id,'B-01'));
    rerender(<Records scene={scene} state={{...state,counts:null}} selection={{filter:'script',record:'B-36'}}/>);
    expect(screen.getByText('Findings not assessed.')).toBeVisible();expect(screen.getByText('Planned shot: Not supplied')).toBeVisible();expect(screen.getByText('Continuity reference: Not supplied')).toBeVisible();
  });
  it('inspects retained findings, missing sources and empty locator states',()=>{
    const {rerender}=render(<Records scene={scene} state={state} selection={{filter:'findings',record:finding.finding_id}}/>);
    expect(screen.getByText(finding.observation)).toBeVisible();
    expect(screen.getByRole('link',{name:'Review this finding'})).toHaveAttribute('href',link('scene',state.run_id,undefined,{finding:finding.finding_id}));
    rerender(<Evidence scene={scene} finding={{...finding,sources:[],locators:[],requirement_id:'UNMATCHED'}}/>);
    fireEvent.click(screen.getByText('Source records & digests'));expect(screen.getByText(/No source artifact/)).toBeVisible();expect(screen.getByText(/No source locator/)).toBeVisible();
    rerender(<Evidence scene={scene} finding={{...finding,locators:[{kind:'take',value:take.take_id},{kind:'page',value:'44'}]}}/>);
    expect(screen.getByText(take.take_id)).toBeInTheDocument();
  });
  it('shows a standing decision in the Records finding and release inspectors',()=>{
    const decision={decision_id:'d',finding_id:finding.finding_id,action:'accept_exception',actor:'Sue',role:'script_supervisor' as const,reason:'Intent',finding_sha256:finding.record_sha256,at:'date'};
    const inspector=()=>within(screen.getByRole('region',{name:'Record inspector'}));
    const {rerender}=render(<Records scene={scene} state={{...state,decisions:[decision]}} selection={{filter:'findings',record:finding.finding_id}}/>);
    expect(inspector().getByText(/accept exception by Sue \(Script supervisor\)\. The finding stays on the turnover\./)).toBeVisible();
    expect(inspector().queryByText('Next action:')).toBeNull();
    // A confirmation leaves the rights finding blocking wrap, so its next action stays beside the decision.
    const rights=state.exceptions[1];
    const confirmed={...decision,decision_id:'r',finding_id:rights.finding_id,action:'confirm',role:'production_coordinator' as const,finding_sha256:rights.record_sha256};
    rerender(<Records scene={scene} state={{...state,decisions:[confirmed]}} selection={{filter:'releases',record:'BG-07'}}/>);
    expect(inspector().getByText(/confirm by Sue \(Production coordinator\)/)).toBeVisible();
    expect(inspector().getByText('Get the signature.')).toBeVisible();
  });
  it('distinguishes ledger execution flags from current rights findings and expired records',()=>{
    const rights={...state.exceptions[1],observation:'REL-1 expired on 2026-08-01'};
    const {rerender}=render(<Records scene={scene} state={{...state,exceptions:[rights]}} selection={{filter:'releases',record:'BG-07'}}/>);
    expect(screen.getByText(/No executed status is present/)).toBeVisible();expect(screen.getByText('REL-1 expired on 2026-08-01')).toBeVisible();
    expect(screen.getByRole('link',{name:'Review rights finding'})).toBeVisible();
    rerender(<Records scene={{...scene,subjects:[{subject_id:'BG-07',released:true}]}} state={{...state,counts:null}} selection={{filter:'releases',record:'BG-07'}}/>);
    expect(screen.getByText(/An executed status is present/)).toBeVisible();expect(screen.getByText('Not assessed. No clearance can be inferred.')).toBeVisible();
  });
  it('renders unknown routes and deleted records with no inferred selection',()=>{
    const {rerender}=render(<Records scene={scene} state={state} selection={{filter:'invalid',record:'gone'}}/>);
    expect(screen.getByText(/This source is unavailable/)).toBeVisible();
    rerender(<Records scene={scene} state={{...state,counts:null}} selection={{filter:'findings'}}/>);
    expect(screen.getByText(/Run a checkpoint to obtain findings/)).toBeVisible();expect(screen.getByText(/Select a record to inspect/)).toBeVisible();
  });
  it('puts only the selected finding in the decision pane and preserves unmatched source evidence',()=>{
    const {rerender}=render(<SceneView scene={scene} state={state} selected={null} selection={{finding:'f-orphan'}} role="script_supervisor" busy={false} act={save()}/>);
    expect(screen.getByText(/Unmatched source:/)).toBeVisible();expect(screen.getByRole('article',{name:'coverage advisory'})).toBeVisible();expect(screen.queryByRole('article',{name:'continuity CR-01'})).toBeNull();
    rerender(<SceneView scene={scene} state={state} selected="B-01" selection={{finding:'f-con'}} role="dit" busy={false} act={save()}/>);
    expect(screen.getByText(/Decision belongs to Script supervisor/)).toBeVisible();expect(screen.queryByRole('button',{name:'Record decision'})).toBeNull();
    rerender(<SceneView scene={scene} state={state} selected="gone" selection={{finding:'f-con'}} act={save()}/>);
    expect(screen.getByText(/This selection is unavailable/)).toBeVisible();expect(screen.queryByRole('button',{name:'Record decision'})).toBeNull();
  });
  it('allows pane focus jumps without replacing selection and routes metric filters',async()=>{
    location.hash=link('scene',state.run_id,'B-01');
    const user=userEvent.setup();
    render(<SceneView scene={scene} state={state} selected="B-01" selection={{filter:'covered'}} act={save()}/>);
    // Only the workflow stage rail is numbered; the pane jumps and pane headings are plain names.
    expect(Array.from(document.querySelectorAll('.workspace-jumps a'),a=>a.textContent)).toEqual(['Script & takes','Evidence','Decision']);
    expect(Array.from(document.querySelectorAll('.pane-heading'),heading=>heading.textContent)).toEqual(['Scene & script beats','Discrepancy & sources','Human decision']);
    expect(screen.getByRole('searchbox')).toHaveAttribute('placeholder','Beat, text or page');
    await user.click(screen.getByRole('link',{name:'Evidence'}));expect(document.getElementById('evidence-pane')).toHaveFocus();expect(location.hash).toContain('beat=B-01');
    expect(document.getElementById('evidence-pane')!.scrollIntoView).toHaveBeenCalledWith({block:'start'});
    await user.selectOptions(screen.getByLabelText('Show'),'missing-releases');
    expect(location.hash).toContain('filter=missing-releases');
  });
  it('asks for the checkpoint before any finding exists and colours the wrap status by state',()=>{
    const status=()=>within(screen.getByTestId('wrap-status'));
    const {rerender}=render(<SceneView scene={scene} state={{...state,counts:null,pending_approval:null}} selected={null} act={save()}/>);
    expect(screen.getByText('Run the wrap checkpoint first. Findings to review will appear here.')).toBeVisible();
    expect(screen.queryByText(/Select a current finding/)).toBeNull();
    expect(status().getByText('Not assessed')).toHaveClass('state-warn');
    expect(status().getByText('Not approved')).toHaveClass('state-warn');
    rerender(<SceneView scene={scene} state={state} selected="B-17" act={save()}/>);
    expect(screen.getByText('Select a current finding to review its decision. Approval controls remain separate below.')).toBeVisible();
    expect(screen.queryByText(/Run the wrap checkpoint first/)).toBeNull();
    expect(status().getByText('Blocked')).toHaveClass('state-warn');
    expect(status().getByText('Blocked')).not.toHaveClass('state-good');
    rerender(<SceneView scene={scene} state={{...state,eligible:true,wrap_approved:true,pending_approval:null}} selected="B-17" act={save()}/>);
    expect(status().getByText('Eligible')).toHaveClass('state-good');
    expect(status().getByText('Approved')).toHaveClass('state-good');
    expect(status().queryByText('Recorded')).toBeNull();
    expect(screen.getByText('Select a current finding to review its decision.')).toBeVisible();
  });
  it('leads with the approved wrap result, folds the record id and replaces a decided next action',()=>{
    const decision={decision_id:'d',finding_id:finding.finding_id,action:'accept_exception',actor:'Sue',role:'script_supervisor' as const,reason:'Intent',finding_sha256:finding.record_sha256,at:'date'};
    const approvals=()=>screen.getByRole('region',{name:'Pickup & wrap approvals'});
    const card=()=>screen.getByRole('article',{name:'continuity CR-01'});
    const {rerender}=render(<SceneView scene={scene} state={state} selected={null} selection={{finding:'f-con'}} role="first_ad" act={save()}/>);
    expect(card().compareDocumentPosition(approvals()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const id=within(card()).getByText(finding.finding_id);
    expect(id.closest('details')).not.toHaveAttribute('open');
    expect(id.closest('details')?.querySelector('summary')).toHaveTextContent('Record id');
    expect(screen.getByText('Write the intent down.')).toBeVisible();
    rerender(<SceneView scene={scene} state={{...state,eligible:true,wrap_approved:true,pending_approval:null,decisions:[decision]}} selected={null} selection={{finding:'f-con'}} role="first_ad" act={save()}/>);
    expect(approvals().compareDocumentPosition(card()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole('region',{name:'Pickup & wrap approvals'})).toHaveLength(1);
    // Rendered by the evidence pane's Evidence; the compact decision card has no Evidence.
    expect(screen.getByText(/accept exception by Sue \(Script supervisor\)\. The finding stays on the turnover\./)).toBeVisible();
    expect(screen.queryByText('Write the intent down.')).toBeNull();
  });
  it('replaces the next action only with a decision that still applies to the exact finding',()=>{
    const decision={decision_id:'d',finding_id:finding.finding_id,action:'reject_false_positive',actor:'Sue',role:'script_supervisor' as const,reason:'Intent',finding_sha256:finding.record_sha256,at:'date'};
    const {rerender}=render(<Evidence scene={scene} finding={finding} decisions={[decision]}/>);
    expect(screen.getByText('Decision on record:')).toBeVisible();
    expect(screen.getByText(/reject false positive by Sue \(Script supervisor\)/)).toBeVisible();
    expect(screen.queryByText('Next action:')).toBeNull();
    rerender(<Evidence scene={scene} finding={finding} decisions={[{...decision,finding_sha256:'old'}]}/>);
    expect(screen.getByText('Write the intent down.')).toBeVisible();
    expect(screen.queryByText('Decision on record:')).toBeNull();
    rerender(<Evidence scene={scene} finding={finding} decisions={[{...decision,role:'dit'}]}/>);
    expect(screen.getByText('Write the intent down.')).toBeVisible();
    rerender(<Evidence scene={scene} finding={finding}/>);
    expect(screen.getByText('Next action:')).toBeVisible();
    expect(screen.queryByText('Decision on record:')).toBeNull();
    // policy.py keeps a confirmed finding blocking wrap, so its next action stays beside the decision.
    rerender(<Evidence scene={scene} finding={finding} decisions={[{...decision,action:'confirm'}]}/>);
    expect(screen.getByText('Decision on record:')).toBeVisible();
    expect(screen.getByText(/confirm by Sue \(Script supervisor\)/)).toBeVisible();
    expect(screen.getByText('Next action:')).toBeVisible();
    expect(screen.getByText('Write the intent down.')).toBeVisible();
    // An acceptance closes the finding only for a role allowed to accept that check.
    const rights={...finding,check_type:'rights' as const,required_role:'production_coordinator' as const};
    rerender(<Evidence scene={scene} finding={rights} decisions={[{...decision,action:'accept_exception',role:'production_coordinator'}]}/>);
    expect(screen.getByText(/accept exception by Sue \(Production coordinator\)/)).toBeVisible();
    expect(screen.getByText('Write the intent down.')).toBeVisible();
    rerender(<Evidence scene={scene} finding={finding} decisions={[{...decision,action:'accept_exception'}]}/>);
    expect(screen.getByText(/accept exception by Sue \(Script supervisor\)/)).toBeVisible();
    expect(screen.queryByText('Next action:')).toBeNull();
  });
  it('carries an accepted pickup onto its gap row and marks the advisory as outside the gate',()=>{
    const gap:Finding={...finding,finding_id:'f-b17',check_type:'coverage',requirement_id:'B-17',truth_state:'missing',next_action:'Shoot the pickup.'};
    const base:Delivery={idempotency_key:'pickup-1',event_type:'pickup.requested',status:'accepted',accepted:true,reference:'receipt-1',detail:'Bus accepted',retry_supported:true};
    const pickup:Delivery=Object.assign({},base,{payload:{beat_id:'B-17'}});
    const {rerender}=render(<SceneView scene={scene} state={{...state,exceptions:[...state.exceptions,gap],delivery_outcomes:[pickup],pending_approval:null}} selected={null}/>);
    const row=screen.getByRole('link',{name:/coverage · B-17/});
    expect(row).toHaveTextContent('missing · Needs review');
    expect(row).toHaveTextContent('Pickup approved · stays an exception until a take arrives');
    expect(screen.getAllByText('Pickup approved · stays an exception until a take arrives')).toHaveLength(1);
    expect(screen.getByRole('link',{name:/coverage · Shot plan advisory/})).toHaveTextContent('unknown · Advisory, not a wrap blocker');
    expect(screen.getByRole('link',{name:/continuity · CR-01/})).toHaveTextContent('conflicting · Needs review');
    rerender(<SceneView scene={scene} state={{...state,exceptions:[...state.exceptions,gap],delivery_outcomes:[{...pickup,status:'pending',accepted:false}],pending_approval:null}} selected={null}/>);
    expect(screen.queryByText(/Pickup approved/)).toBeNull();
  });
  it('points an approved wrap at the handoff and keeps readiness review in every other state',()=>{
    const stages=()=>screen.getByRole('list',{name:'Wrap decision stages'});
    const {rerender}=render(<ApprovalConsole state={{...state,eligible:true,wrap_approved:true,pending_approval:null}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('link',{name:'Publish the approved turnover next'})).toHaveAttribute('href',link('history',state.run_id));
    expect(screen.queryByRole('button',{name:'Review wrap readiness'})).toBeNull();
    expect(screen.queryByText(/Only the 1st AD can approve wrap/)).toBeNull();
    expect(stages().tagName).toBe('UL');
    expect(stages()).toHaveTextContent('Wrap approved');
    expect(stages()).not.toHaveTextContent(/0[123]/);
    rerender(<ApprovalConsole state={{...state,eligible:true,wrap_approved:true,pending_approval:null,turnover:{}}} role="editorial" busy={false} act={save()}/>);
    expect(screen.getByRole('link',{name:'Read the saved turnover'})).toHaveAttribute('href',link('history',state.run_id));
    expect(screen.queryByRole('link',{name:'Publish the approved turnover next'})).toBeNull();
    rerender(<ApprovalConsole state={{...state,eligible:true,wrap_approved:true,pending_approval:{id:'renewed',reason:{kind:'wrap',required_role:'first_ad',note:'Renewed request'}}}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeEnabled();
    expect(screen.queryByRole('link',{name:/turnover/})).toBeNull();
    rerender(<ApprovalConsole state={{...state,eligible:true,pending_approval:null}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeEnabled();
    expect(screen.getByText('The evidence gate reports eligible. Only the 1st AD can approve wrap.')).toBeVisible();
    expect(stages()).toHaveTextContent('Wrap not approved');
    expect(screen.queryByRole('link',{name:/turnover/})).toBeNull();
    rerender(<ApprovalConsole state={{...state,counts:null,pending_approval:null}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeDisabled();
    expect(screen.getByText('Run a checkpoint first to assess readiness.')).toBeVisible();
    // Turnover.tsx refuses to publish without current eligibility, so an approval
    // with a blocked or missing assessment gets no handoff link.
    rerender(<ApprovalConsole state={{...state,wrap_approved:true,pending_approval:null}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeEnabled();
    expect(screen.getByText(/prevent wrap eligibility/)).toHaveClass('warning');
    expect(screen.queryByRole('link',{name:/turnover/})).toBeNull();
    rerender(<ApprovalConsole state={{...state,exceptions:[],counts:null,pending_approval:null,wrap_approved:true}} role="editorial" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Review wrap readiness'})).toBeDisabled();
    expect(screen.getByText('Run a checkpoint first to assess readiness.')).toBeVisible();
    expect(screen.queryByRole('link',{name:/turnover/})).toBeNull();
  });
});
describe('route focus and snapshot integrity',()=>{
  it('types multiple search characters without moving focus, restores query context, and keeps selection across navigation',async()=>{
    api();location.hash=link('records',state.run_id,'B-01',{filter:'takes',record:'T-1'});
    const user=userEvent.setup();render(<App/>);
    const search=await screen.findByRole('searchbox',{name:'Search records'});
    await user.type(search,'MEDIA');
    await waitFor(()=>expect(search).toHaveValue('MEDIA'));expect(search).toHaveFocus();expect(location.hash).toContain('q=MEDIA');
    await user.click(within(screen.getByRole('navigation')).getByRole('link',{name:'Scene review'}));
    expect(await screen.findByRole('heading',{level:1,name:'Scene review'})).toHaveFocus();expect(location.hash).toContain('beat=B-01');
    expect(screen.getByLabelText('Show')).toHaveValue('all');
    expect(document.querySelectorAll('.beat')).toHaveLength(scene.beats.length);
    await act(async()=>{location.hash=link('records',state.run_id,'B-01',{filter:'takes',record:'T-1',q:'MEDIA'});});
    expect(await screen.findByRole('searchbox',{name:'Search records'})).toHaveValue('MEDIA');
    expect(screen.getByRole('region',{name:'Record inspector'})).toHaveTextContent('MEDIA-1');
  });
  it('locks writing after a failed refresh and re-enables it only after recovery',async()=>{
    const fetcher=api();location.hash=link('scene',state.run_id,undefined,{finding:'f-con'});
    const user=userEvent.setup();render(<App/>);await screen.findByRole('button',{name:'Record decision'});
    fetcher.mockRejectedValueOnce(new Error('Offline'));
    await user.click(screen.getByRole('button',{name:'Refresh saved state'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Displayed evidence may be out of date');
    expect(screen.getByRole('button',{name:'Record decision'})).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'Retry loading saved state'}));
    await waitFor(()=>expect(screen.getByRole('button',{name:'Record decision'})).toBeEnabled());
  });
  it('keeps intake editing and close available after a server rejection',async()=>{
    const fetcher=api();location.hash=link('scene',state.run_id);
    const user=userEvent.setup();render(<App/>);await screen.findByText(scene.scene_heading);
    await user.click(screen.getByRole('button',{name:'Add take or release'}));
    await user.click(screen.getByLabelText('Advanced JSON entry'));
    fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{"take_id":"bad"}'}});
    fetcher.mockRejectedValueOnce(new Error('Missing fields'));
    await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Document JSON')).toBeEnabled();
    expect(screen.getByRole('button',{name:'Save evidence & rerun checks'})).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'Close form'}));
    expect(screen.queryByLabelText('Document JSON')).toBeNull();
  });
  it('permits immediate correction and resubmission after a known 400 validation refusal',async()=>{
    const fetcher=api();location.hash=link('scene',state.run_id);
    const user=userEvent.setup();render(<App/>);await screen.findByText(scene.scene_heading);
    await user.click(screen.getByRole('button',{name:'Add take or release'}));
    await user.click(screen.getByLabelText('Advanced JSON entry'));
    fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{"take_id":"bad"}'}});
    fetcher.mockImplementationOnce(async()=>({ok:false,status:400,json:async()=>({...state,error:'Missing fields'})}));
    await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Correct the supplied fields');
    expect(screen.getByRole('button',{name:'Save evidence & rerun checks'})).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{"take_id":"corrected"}'}});
    await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
    await waitFor(()=>expect(screen.queryByLabelText('Document JSON')).toBeNull());
    expect(fetcher.mock.calls.filter(([url])=>url==='/api/ingest')).toHaveLength(2);
  });
  it('refuses wrap approval with missing request identity, wrong required role or lost eligibility',()=>{
    const pending={id:'wrap',reason:{kind:'wrap' as const,required_role:'first_ad' as const,note:'snapshot'}};
    const {rerender}=render(<ApprovalConsole state={{...state,pending_approval:pending}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Approve wrap'})).toBeDisabled();
    rerender(<ApprovalConsole state={{...state,eligible:true,pending_approval:{...pending,id:''}}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.getByRole('button',{name:'Decline wrap'})).toBeDisabled();
    rerender(<ApprovalConsole state={{...state,eligible:true,pending_approval:{...pending,reason:{...pending.reason,required_role:'dit'}}}} role="first_ad" busy={false} act={save()}/>);
    expect(screen.queryByRole('button',{name:'Approve wrap'})).toBeNull();
  });
});
