import {it,expect,vi} from 'vitest';
import {act,render,renderHook,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {History} from '../src/History';
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
