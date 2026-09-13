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
    await user.click(screen.getByRole('link',{name:'02 Evidence'}));expect(document.getElementById('evidence-pane')).toHaveFocus();expect(location.hash).toContain('beat=B-01');
    expect(document.getElementById('evidence-pane')!.scrollIntoView).toHaveBeenCalledWith({block:'start'});
    await user.selectOptions(screen.getByLabelText('Show'),'missing-releases');
    expect(location.hash).toContain('filter=missing-releases');
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
