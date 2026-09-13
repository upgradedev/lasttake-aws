import {it,expect,vi} from 'vitest';
import {act,render,renderHook,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {Dashboard} from '../src/Dashboard';
import {History} from '../src/History';
import {Landing} from '../src/Landing';
import {useWorkspace} from '../src/useWorkspace';
import {scene,session,state} from './fixtures';

const first={...session,next_cursor:'first-cursor',has_more:true};
const older={...session,runs:[{...session.runs[0],run_id:'demo-old-saved'}],next_cursor:null,has_more:false};
function server(history:(body:Record<string,unknown>)=>Promise<unknown>) {
  const fetcher=vi.fn(async(url:string,init:RequestInit)=>{
    const body=JSON.parse(init.body as string);
    const data=url==='/api/session'?await history(body):url==='/api/scene'?scene:url==='/api/events'?{events:[]}:state;
    return data instanceof Response?data:new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
  });
  vi.stubGlobal('fetch',fetcher);return fetcher;
}

it('history controls retain page context, bound loading and label errors without deleting old runs',async()=>{
  const user=userEvent.setup(),load=vi.fn().mockResolvedValue(undefined),refresh=vi.fn().mockResolvedValue(undefined);
  const props={state,session:first,events:[],role:'dit' as const,busy:false,act:vi.fn(),handle:vi.fn(),olderRuns:load,newestRuns:refresh};
  const {rerender}=render(<History {...props}/>);
  expect(screen.getByText(/one page, not the whole history/)).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Load older runs'}));
  expect(load).toHaveBeenCalledOnce();
  rerender(<History {...props} historyLoading/>);
  expect(screen.getByRole('button',{name:'Load older runs'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Refresh newest runs'})).toBeDisabled();
  rerender(<History {...props} historyError="History changed."/>);
  expect(screen.getByRole('alert')).toHaveTextContent('Your current page is retained');
  expect(screen.getByText(state.run_id,{selector:'.run-list small'})).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Refresh newest runs'}));
  expect(refresh).toHaveBeenCalledOnce();
  rerender(<History {...props} session={older}/>);
  expect(screen.getByRole('button',{name:'Load older runs'})).toBeDisabled();
});

it('names each saved run by its scene, counts a single run in the singular and marks the receipt toolbar',()=>{
  const props={state,session,events:[],role:'dit' as const,busy:false,act:vi.fn(),handle:vi.fn()};
  const {rerender}=render(<History {...props}/>);
  expect(screen.getByText('1 run on this page',{exact:true})).toBeVisible();
  expect(screen.getByText(/^SC-042 · /,{selector:'.run-list a'})).toHaveAttribute('href',`#history?run=${state.run_id}`);
  expect(screen.queryByText(/Scene 42/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Receipt purpose').closest('.toolbar')).toHaveClass('receipt-toolbar');
  rerender(<History {...props} session={{...session,runs:[...session.runs,{...session.runs[0],run_id:'demo-second'}],has_more:true}}/>);
  expect(screen.getByText('2 runs on this page · older runs available',{exact:true})).toBeVisible();
  expect(screen.getAllByText(/^SC-042 · /,{selector:'.run-list a'})).toHaveLength(2);
});

it('groups consecutive events of one type on the current page and keeps every event reachable',async()=>{
  // Oldest first: 7 findings, a take, 13 findings, wrap ready, turnover. Newest
  // first that pages as 20 events (a burst of 13 and a tail of 4) and then 3.
  const kinds=[...Array.from({length:7},()=>'finding.recorded'),'take.captured',...Array.from({length:13},()=>'finding.recorded'),'wrap.ready','turnover.generated'];
  const events=kinds.map((event_type,i)=>({event_id:`event-${i}`,event_type,occurred_at:new Date(Date.UTC(2026,8,13,16,26,i)).toISOString(),payload:{index:i}}));
  const user=userEvent.setup();
  render(<History state={state} session={session} events={events} role="dit" busy={false} act={vi.fn()} handle={vi.fn()}/>);
  const region=screen.getByRole('region',{name:'Recorded events'});
  const record=within(region);
  expect(record.getByRole('status')).toHaveTextContent('Events 1–20 of 23');
  const rows=record.getAllByRole('listitem');
  expect(rows.map(row=>row.querySelector('strong')?.textContent)).toEqual(['turnover generated','wrap ready','finding recorded ×13','take captured','finding recorded ×4']);
  expect(region.querySelectorAll('#event-timeline [data-event-id]')).toHaveLength(20);
  const burst=rows[2];
  expect(burst.querySelector('time')).toHaveAttribute('datetime',events[20].occurred_at);
  expect(Array.from(burst.querySelectorAll('[data-event-id]'),entry=>entry.getAttribute('data-event-id'))).toEqual(Array.from({length:13},(_,i)=>`event-${20-i}`));
  const list=within(burst).getByText('List the 13 events',{exact:true});
  expect(list.closest('details')).not.toHaveAttribute('open');
  expect(within(burst).getAllByText('Event details')[0]).not.toBeVisible();
  await user.click(list);
  expect(list.closest('details')).toHaveAttribute('open');
  expect(within(burst).getAllByText('Event details')).toHaveLength(13);
  expect(within(burst).getAllByText('Event details')[12]).toBeVisible();
  expect(within(rows[0]).getByText('Event details')).toBeVisible();
  await user.click(record.getByRole('button',{name:'Older events'}));
  expect(record.getByRole('status')).toHaveTextContent('Events 21–23 of 23');
  expect(record.getAllByRole('listitem')).toHaveLength(1);
  expect(record.getAllByRole('listitem')[0].querySelector('strong')).toHaveTextContent('finding recorded ×3');
  expect(region.querySelectorAll('#event-timeline [data-event-id]')).toHaveLength(3);
  await user.click(record.getByRole('button',{name:'Newer events'}));
  expect(record.getAllByRole('listitem')).toHaveLength(5);
});

it('overview names the Handoff page where saved runs load, in the singular for one run',()=>{
  const {rerender}=render(<Dashboard scene={scene} state={state} session={session} events={[]} busy={false} checkpoint={vi.fn()}/>);
  expect(screen.getByText(/^1 saved run on the loaded Handoff page; 1 with findings;/)).toBeInTheDocument();
  expect(screen.getByText(/Open Handoff to load older runs\./)).toBeInTheDocument();
  expect(screen.queryByText(/history page|Open History/)).not.toBeInTheDocument();
  rerender(<Dashboard scene={scene} state={state} session={null} events={[]} busy={false} checkpoint={vi.fn()}/>);
  expect(screen.getByText(/^0 saved runs on the loaded Handoff page;/)).toBeInTheDocument();
});

it('landing keeps the script revision as one identifier and states the public deployment in a full sentence',async()=>{
  const preview={schema:'lasttake/scene-preview/v1',production_id:scene.production_id,scene_id:scene.scene_id,scene_heading:scene.scene_heading,revision:scene.revision,required_beats:34,optional_beats:2,supplied_takes:40,opening_beats:[{beat_id:'B-01',page:'41',line:3,slug:'Mara at the window'}],synthetic_notice:'Fictional production.'};
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(preview),{status:200,headers:{'Content-Type':'application/json'}})));
  render(<Landing session={session} busy={false} page="overview" start={vi.fn()}/>);
  expect(await screen.findByText('Blue-2026-08-19',{exact:true})).toHaveClass('fact-id');
  expect(screen.getByText(/This public deployment uses a scripted planner and an offline lexical interpreter; no footage or audio is analysed and nothing is cleared in law\./)).toBeVisible();
  expect(document.body.textContent).not.toContain('A scripted planner and an offline lexical interpreter on this public deployment');
});

it('loads one page only on request, replaces rather than accumulates it, and preserves selected run',async()=>{
  location.hash=`#history?run=${state.run_id}`;
  const fetcher=server(async body=>body.cursor?older:first);
  const {result}=renderHook(()=>useWorkspace());
  await waitFor(()=>expect(result.current.busy).toBe(false));
  expect(fetcher.mock.calls.filter(([url])=>url==='/api/session')).toHaveLength(1);
  await act(async()=>{await result.current.olderRuns();});
  expect(result.current.session?.runs).toEqual(older.runs);
  expect(result.current.state?.run_id).toBe(state.run_id);
  expect(JSON.parse(fetcher.mock.calls.filter(([url])=>url==='/api/session')[1][1].body as string)).toEqual({session_id:session.session_id,cursor:'first-cursor'});
  await act(async()=>{await result.current.olderRuns();});
  expect(fetcher.mock.calls.filter(([url])=>url==='/api/session')).toHaveLength(2);
  await act(async()=>{await result.current.newestRuns();});
  expect(result.current.session?.runs).toEqual(first.runs);
});

it('failed page keeps saved state and page, with an explicit read retry instead of a write retry',async()=>{
  const fetcher=server(async body=>body.cursor?new Response(JSON.stringify({error:'Saved history changed.'}),{status:409,headers:{'Content-Type':'application/json'}}):first);
  const {result}=renderHook(()=>useWorkspace());
  await waitFor(()=>expect(result.current.busy).toBe(false));
  await act(async()=>{await result.current.olderRuns();});
  expect(result.current.session).toEqual(first);
  expect(result.current.historyError).toBe('Saved history changed.');
  expect(result.current.error).toBe('');
  expect(fetcher.mock.calls.filter(([url])=>url==='/api/reset')).toHaveLength(0);
  await act(async()=>{await result.current.newestRuns();});
  expect(result.current.historyError).toBe('');
});

it('late older-page response cannot replace a recovered session and duplicate clicks share the page lock',async()=>{
  let release!:(value:unknown)=>void;
  let fresh=false;
  server(async body=>body.cursor?new Promise(resolve=>{release=resolve;}):fresh?{...session,session_id:'b'.repeat(64),runs:[]}:first);
  const {result}=renderHook(()=>useWorkspace());
  await waitFor(()=>expect(result.current.busy).toBe(false));
  let pending!:Promise<void>;
  await act(async()=>{pending=result.current.olderRuns();await result.current.olderRuns();});
  expect(result.current.historyLoading).toBe(true);
  fresh=true;
  await act(async()=>{await result.current.recover();});
  await act(async()=>{release(older);await pending;});
  expect(result.current.session?.session_id).toBe('b'.repeat(64));
  expect(result.current.session?.runs).toEqual([]);
  expect(result.current.historyLoading).toBe(false);
});
