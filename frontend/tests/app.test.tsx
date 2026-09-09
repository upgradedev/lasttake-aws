import {it,expect,vi} from 'vitest';
import {act,render,renderHook,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {App} from '../src/App';
import {useWorkspace} from '../src/useWorkspace';
import {state,scene,session} from './fixtures';
function server(options:{empty?:boolean;unchecked?:boolean}={}) {
  let created=!options.empty;
  let checked=!options.unchecked;
  const fetcher=vi.fn(async(url:string,init:RequestInit)=>{
    if(url==='/api/session')return {ok:true,json:async()=>({...session,runs:created?session.runs:[]})};
    if(url==='/api/reset'){created=true;return {ok:true,json:async()=>({run_id:state.run_id})};}
    if(url==='/api/checkpoint')checked=true;
    const body=JSON.parse(init.body as string);
    return {ok:true,json:async()=>url==='/api/scene'?scene:url==='/api/events'?{events:[]}:{...state,run_id:body.run_id,counts:checked?state.counts:null,headline:checked?state.headline:null,message:'Checkpoint saved.'}};
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
it('starts with useful empty state, creates a saved run and checks evidence',async()=>{server({empty:true,unchecked:true});const user=userEvent.setup();render(<App/>);expect(await screen.findByText('Bring the shoot day into focus.')).toBeVisible();await user.click(screen.getByRole('button',{name:'Open guided demo'}));expect(screen.getByText(/Walk through a fictional/)).toBeVisible();await user.click(screen.getByRole('button',{name:'Start this fictional shoot day'}));await user.click(await screen.findByRole('button',{name:'Run wrap checkpoint'}));await screen.findByText('Checkpoint saved.');await user.click(screen.getByRole('button',{name:'Add take or release'}));expect(screen.getByText('Add evidence to this shoot day')).toBeVisible();await user.click(screen.getByRole('button',{name:'Close form'}));await user.click(screen.getByRole('button',{name:'Close guided demo'}));await user.click(screen.getByRole('link',{name:'Overview'}));expect(await screen.findByText('Current saved run')).toBeVisible();expect(localStorage.getItem('lasttake.session')).toBe(session.session_id);expect(localStorage.getItem('lasttake.run')).toBeNull();});
it('restores navigation, changes role preference, refreshes and shows history',async()=>{server();location.hash=`#actions?run=${state.run_id}`;const user=userEvent.setup();render(<App/>);expect(await screen.findByText('Pickup & wrap approvals')).toBeVisible();await user.selectOptions(screen.getByLabelText('Demo role'),'first_ad');expect(localStorage.getItem('lasttake.role')).toBe('first_ad');await user.click(screen.getByRole('button',{name:'Refresh saved state'}));await waitFor(()=>expect(screen.getByRole('button',{name:'Approve pickup'})).toBeEnabled());await user.click(screen.getByRole('link',{name:'Turnovers & history'}));expect(await screen.findByText('Turnover for this run')).toBeVisible();await user.click(screen.getByText('Run details & execution labels'));expect(screen.getByText('offline-lexical/1.0.0')).toBeVisible();await user.click(screen.getByRole('link',{name:'Skip to main content'}));expect(document.getElementById('main')).toHaveFocus();});
it('renders loading failures and permits a separate session recovery',async()=>{const fetcher=vi.fn().mockRejectedValueOnce(new Error('Session unavailable')).mockResolvedValue({ok:true,json:async()=>({...session,runs:[]})});vi.stubGlobal('fetch',fetcher);const user=userEvent.setup();render(<App/>);expect(await screen.findByRole('alert')).toHaveTextContent('Session unavailable');await user.click(screen.getByRole('button',{name:'Start a separate session'}));expect(await screen.findByText('Bring the shoot day into focus.')).toBeVisible();});
it('discards an old-run response after navigation while refresh is pending',async()=>{const fetcher=server();location.hash=`#scene?run=${state.run_id}`;render(<App/>);await screen.findByText(scene.scene_heading);let release!:(value:unknown)=>void;fetcher.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve as typeof release;}));await act(async()=>{screen.getByRole('button',{name:'Refresh saved state'}).click();});await act(async()=>{location.hash='#scene?run=demo-second01';});await waitFor(()=>expect(screen.getByText('Run details & execution labels')).toBeInTheDocument());await act(async()=>{release({ok:true,json:async()=>({...state,headline:'OLD RESPONSE MUST NOT WIN'})});});await waitFor(()=>expect(screen.queryByText('OLD RESPONSE MUST NOT WIN')).not.toBeInTheDocument());const mutationCalls=fetcher.mock.calls.filter(([url])=>url==='/api/decide'||url==='/api/approve');expect(mutationCalls).toHaveLength(0);});
it('does not white-screen when browser storage is denied',async()=>{server({empty:true});vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new DOMException('Denied');});vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('Denied');});render(<App/>);expect(await screen.findByText('Bring the shoot day into focus.')).toBeVisible();expect(screen.getByText(/Browser storage is unavailable/)).toBeVisible();});
