import {it,expect,vi} from 'vitest';
import {act,render,renderHook,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {App,ServerMessage} from '../src/App';
import {useWorkspace} from '../src/useWorkspace';
import {state,scene,session} from './fixtures';
function server(options:{empty?:boolean;unchecked?:boolean;turnover?:Record<string,unknown>;message?:string;noPending?:boolean;sceneRevision?:string}={}) {
  let created=!options.empty;
  let checked=!options.unchecked;
  const fetcher=vi.fn(async(url:string,init:RequestInit)=>{
    if(url==='/api/session')return {ok:true,json:async()=>({...session,runs:created?session.runs:[]})};
    if(url==='/api/reset'){created=true;return {ok:true,json:async()=>({run_id:state.run_id})};}
    if(url==='/api/checkpoint')checked=true;
    const body=JSON.parse(init.body as string);
    return {ok:true,json:async()=>url==='/api/scene'?{...scene,revision:options.sceneRevision ?? scene.revision}:url==='/api/events'?{events:[]}:{...state,run_id:body.run_id,pending_approval:checked && !options.noPending?state.pending_approval:null,counts:checked?state.counts:null,headline:checked?state.headline:null,turnover:options.turnover ?? null,message:options.message ?? 'Checkpoint saved.'}};
  });vi.stubGlobal('fetch',fetcher);return fetcher;
}

it('rejects a stale action callback after the selected run changes',async()=>{
  const fetcher=server();location.hash=`#actions?run=${state.run_id}`;
  const {result}=renderHook(()=>useWorkspace());
  await waitFor(()=>expect(result.current.state?.run_id).toBe(state.run_id));
  const staleAction=result.current.act;
  await act(async()=>{
    location.hash='#actions?run=demo-second01';
    expect(await staleAction('approve',{interrupt_id:'pending-1',approve:true,role:'first_ad'})).toBe(false);
  });
  expect(fetcher.mock.calls.some(([url])=>url==='/api/approve')).toBe(false);
  await waitFor(()=>expect(result.current.state?.run_id).toBe('demo-second01'));
});
it('starts with useful empty state, creates a saved run and checks evidence',async()=>{server({empty:true,unchecked:true});const user=userEvent.setup();render(<App/>);expect(await screen.findByText('Know what still blocks wrap.')).toBeVisible();await user.click(screen.getByRole('button',{name:'Open guided demo'}));expect(screen.getByText(/Walk through a fictional/)).toBeVisible();expect(screen.getByText(/no EventBridge rule or subscriber triggers it/)).toBeVisible();await user.click(screen.getByRole('button',{name:'Start this fictional shoot day'}));await user.click(await screen.findByRole('button',{name:'Run wrap checkpoint'}));await screen.findByText('Checkpoint saved.');await user.click(screen.getByRole('button',{name:'Add take or release'}));expect(screen.getByText('Add evidence to this shoot day')).toBeVisible();await user.click(screen.getByRole('button',{name:'Close form'}));await user.click(screen.getByRole('button',{name:'Close guided demo'}));await user.click(screen.getByRole('link',{name:'Wrap status'}));expect(await screen.findByText('Current saved run')).toBeVisible();expect(localStorage.getItem('lasttake.session')).toBe(session.session_id);expect(localStorage.getItem('lasttake.run')).toBeNull();});
it('restores navigation, changes role preference, refreshes and shows history',async()=>{server();location.hash=`#actions?run=${state.run_id}`;const user=userEvent.setup();render(<App/>);expect(await screen.findByText('Pickup & wrap approvals')).toBeVisible();expect(screen.getByRole('link',{name:'Current automated acceptance'})).toHaveAttribute('href','/acceptance.html');expect(screen.getByRole('link',{name:'UAT testbook'})).toHaveAttribute('href','/UAT.testbook.html');await user.selectOptions(screen.getByLabelText('Demo role'),'first_ad');expect(localStorage.getItem('lasttake.role')).toBe('first_ad');await user.click(screen.getByRole('button',{name:'Refresh saved state'}));await waitFor(()=>expect(screen.getByRole('button',{name:'Approve pickup'})).toBeEnabled());await user.click(screen.getByRole('link',{name:'Handoff'}));expect(await screen.findByText('Turnover for this run')).toBeVisible();await user.click(screen.getByText('Run details & execution labels'));expect(screen.getByText('offline-lexical/1.0.0')).toBeVisible();await user.click(screen.getByRole('link',{name:'Skip to main content'}));expect(document.getElementById('main')).toHaveFocus();});
it('renders loading failures and permits a separate session recovery',async()=>{const fetcher=vi.fn().mockRejectedValueOnce(new Error('Session unavailable')).mockResolvedValue({ok:true,json:async()=>({...session,runs:[]})});vi.stubGlobal('fetch',fetcher);const user=userEvent.setup();render(<App/>);expect(await screen.findByRole('alert')).toHaveTextContent('Session unavailable');await user.click(screen.getByRole('button',{name:'Start a separate session'}));expect(await screen.findByText('Know what still blocks wrap.')).toBeVisible();});
it('discards an old-run response after navigation while refresh is pending',async()=>{const fetcher=server();location.hash=`#scene?run=${state.run_id}`;render(<App/>);await screen.findByText(scene.scene_heading);let release!:(value:unknown)=>void;fetcher.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve as typeof release;}));await act(async()=>{screen.getByRole('button',{name:'Refresh saved state'}).click();});await act(async()=>{location.hash='#scene?run=demo-second01';});await waitFor(()=>expect(screen.getByText('Run details & execution labels')).toBeInTheDocument());await act(async()=>{release({ok:true,json:async()=>({...state,headline:'OLD RESPONSE MUST NOT WIN'})});});await waitFor(()=>expect(screen.queryByText('OLD RESPONSE MUST NOT WIN')).not.toBeInTheDocument());const mutationCalls=fetcher.mock.calls.filter(([url])=>url==='/api/decide'||url==='/api/approve');expect(mutationCalls).toHaveLength(0);});
it('prints a server message exactly, with receipt ids shortened, and a waiting run in the waiting style',()=>{
  const id='d0d933cf-1159-4284-a601-a3cb3ed05846';
  const {rerender}=render(<ServerMessage text={`Pickup approved for B-17 by the 1st AD. Bus accepted. Receipt ${id}. Downstream completion is not established.`} waiting/>);
  const banner=screen.getByRole('status');
  expect(banner).toHaveClass('message-waiting');expect(banner).not.toHaveClass('saved');
  expect(banner.textContent).toBe('Pickup approved for B-17 by the 1st AD. Bus accepted. Receipt d0d933cf. Downstream completion is not established.');
  expect(screen.getByTitle(id).tagName).toBe('CODE');
  expect(screen.getByTitle(id).textContent).toBe('d0d933cf');
  rerender(<ServerMessage text={`Saved ${id.toUpperCase()} and ${id}`} waiting={false}/>);
  expect(screen.getByRole('status')).toHaveClass('saved');expect(screen.getByRole('status')).not.toHaveClass('message-waiting');
  expect(screen.getByRole('status').textContent).toBe('Saved D0D933CF and d0d933cf');
  expect(screen.getByRole('status').querySelectorAll('code')).toHaveLength(2);
  rerender(<ServerMessage text="Checkpoint saved." waiting={false}/>);
  expect(screen.getByRole('status').textContent).toBe('Checkpoint saved.');
  expect(screen.getByRole('status').querySelector('code')).toBeNull();
});
it('shows the saved approval message in the waiting style while a request still waits',async()=>{
  const id='d0d933cf-1159-4284-a601-a3cb3ed05846';
  server({message:`Pickup approved for B-17 by the 1st AD. Bus accepted. Receipt ${id}. Downstream completion is not established.`});
  location.hash=`#actions?run=${state.run_id}`;const user=userEvent.setup();render(<App/>);
  await user.selectOptions(await screen.findByLabelText('Demo role'),'first_ad');
  const approve=await screen.findByRole('button',{name:'Approve pickup'});
  await waitFor(()=>expect(approve).toBeEnabled());
  await user.click(approve);
  const receipt=await screen.findByTitle(id);
  const banner=receipt.closest('p')!;
  expect(banner).toHaveAttribute('role','status');expect(banner).toHaveClass('message-waiting');
  expect(banner.textContent).toBe('Pickup approved for B-17 by the 1st AD. Bus accepted. Receipt d0d933cf. Downstream completion is not established.');
});
it('leads a historical turnover to a fresh run and names the scene and revision in words',async()=>{
  // No request is waiting, so the historical turnover is the card's next step.
  const fetcher=server({noPending:true,sceneRevision:`${scene.revision}+late+rights+rights`,turnover:{package_revision_digest:'old',scene_id:scene.scene_id,script_revision:`${scene.revision}+late+rights+rights`,generated_at:'2026-09-13T16:27:56Z'}});
  location.hash=`#history?run=${state.run_id}`;const user=userEvent.setup();render(<App/>);
  const fresh=await screen.findByRole('button',{name:'Start a fresh shoot-day run'});
  await waitFor(()=>expect(fresh).toBeEnabled());
  expect(fresh).toHaveClass('primary');
  expect(screen.getByRole('button',{name:'Download turnover'})).not.toHaveClass('primary');
  expect(screen.getByTestId('decision-headline')).toHaveTextContent('Evidence changed after this turnover');
  expect(screen.queryByText('Eligible for a human wrap decision')).toBeNull();
  expect(screen.getByText('Shoot day · SC-042')).toBeVisible();
  expect(screen.queryByText(`Shoot day · ${scene.revision}`)).toBeNull();
  expect(screen.getByTestId('editorial-decision')).toHaveTextContent('SC-042 / Blue-2026-08-19 · late take added · 2 rights records added');
  // The top bar keeps the base revision on one line; what was added is in its title.
  const crumb=document.querySelector('.topbar-title .muted')!;
  expect(crumb.textContent).toBe('/ SC-042 · Blue-2026-08-19');
  expect(crumb).toHaveAttribute('title','Blue-2026-08-19 · late take added · 2 rights records added');
  expect(screen.getByText(/^Evidence has changed since this turnover was sealed\./)).toBeVisible();
  await user.click(fresh);
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url==='/api/reset')).toBe(true));
});
it('does not white-screen when browser storage is denied',async()=>{server({empty:true});vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new DOMException('Denied');});vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('Denied');});render(<App/>);expect(await screen.findByText('Know what still blocks wrap.')).toBeVisible();expect(screen.getByText(/Browser storage is unavailable/)).toBeVisible();});
