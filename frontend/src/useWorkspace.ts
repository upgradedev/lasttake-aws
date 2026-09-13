import {useCallback,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ApiError,errorMessage,request} from './api';
import {link,readRoute} from './model';
import {readPreference,writePreference} from './storage';
import type {Document,EventRow,RunState,Scene,Session} from './types';
const subscribe=(changed:()=>void)=>{
  window.addEventListener('hashchange',changed);
  window.addEventListener('popstate',changed);
  return ()=>{
    window.removeEventListener('hashchange',changed);
    window.removeEventListener('popstate',changed);
  };
};
const snapshot=()=>location.pathname+location.search+location.hash;
export function useWorkspace() {
  useSyncExternalStore(subscribe,snapshot);
  const route=readRoute();
  const [session,setSession]=useState<Session|null>(null);
  const [state,setState]=useState<RunState|null>(null);
  const [scene,setScene]=useState<Scene|null>(null);
  const [events,setEvents]=useState<EventRow[]>([]);
  const [progress,setProgress]=useState('');
  const [working,setWorking]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [requiresRefresh,setRequiresRefresh]=useState(false);
  const [message,setMessage]=useState('');
  const [historyLoading,setHistoryLoading]=useState(false);
  const [historyError,setHistoryError]=useState('');
  const historyGeneration=useRef(0);
  const historyLock=useRef(false);
  useEffect(()=>{setMessage('');},[route.page]);
  const lock=useRef(false);
  const generation=useRef(0);
  const handle=useCallback(async (work:()=>Promise<void>)=>{
    if(lock.current) return false;
    lock.current=true;setWorking(true);setProgress('Sending request…');setError('');setMessage('');
    try {await work();setRequiresRefresh(false);return true;}catch(e){setError(errorMessage(e));setRequiresRefresh(!(e instanceof ApiError && e.status===400));return false;}
    finally{lock.current=false;setWorking(false);setProgress('');}
  },[]);
  const loadSession=useCallback(async(newSession=false)=>{
    const ticket=++historyGeneration.current;
    const saved=newSession ? null : readPreference('lasttake.session');
    const data=await request<Session>('session', saved ? {session_id:saved} : {});
    if(ticket===historyGeneration.current){writePreference('lasttake.session',data.session_id);setSession(data);setHistoryError('');}
    return data;
  },[]);
  const loadRun=useCallback(async(runId:string,sessionId:string)=>{
    const ticket=++generation.current;
    const body={run_id:runId,session_id:sessionId};
    const [current,script,history]=await Promise.all([request<RunState>('state',body),request<Scene>('scene',body),request<{events:EventRow[]}>('events',body)]);
    if(ticket!==generation.current || readRoute().run!==runId)return;
    setState(current);setScene(script);setEvents(history.events);
  },[]);
  const bootstrap=useCallback(async()=>{
    setLoading(true);setError('');
    // Loading the session is enough. Choosing a run is the person's decision:
    // the landing page offers the saved shoot day to continue, or a fresh one.
    // Jumping straight into the newest run on arrival was the silent identity
    // change criterion 1 of UX-LT-10S forbids.
    try {await loadSession();}
    catch(e){setError(errorMessage(e));setRequiresRefresh(true);}
    finally{setLoading(false);}
  },[loadSession]);
  useEffect(()=>{void bootstrap();},[bootstrap]);
  const sessionId=session?.session_id;
  useEffect(()=>{
    if(!sessionId)return;
    const activeRun = route.run || (route.page !== 'overview' && session?.runs?.[0]?.run_id);
    if (!activeRun) {
      if (route.page === 'scene' || route.page === 'records' || route.page === 'history') {
        void create(route.page);
      }
      return;
    }
    let active=true;
    setState(null);setScene(null);setEvents([]);setMessage('');setError('');setLoading(true);
    void loadRun(activeRun,sessionId).then(()=>{if(active)setRequiresRefresh(false);}).catch(e=>{if(active){setError(errorMessage(e));setRequiresRefresh(true);}}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;generation.current++;};
  },[route.run, route.page, sessionId, session?.runs, loadRun]);
  const create=(targetPage: string = 'scene')=>handle(async()=>{
    const data=session ?? await loadSession();
    const result=await request<{run_id:string}>('reset',{session_id:data.session_id});
    await loadSession();
    const cleanUrl = targetPage === 'overview' ? (window.location.pathname || '/') : `?page=${targetPage}&run=${result.run_id}`;
    history.pushState(null, '', cleanUrl);
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  const act=async(path:string,extra:Document={})=>handle(async()=>{
    if(!state || !session || readRoute().run!==state.run_id)throw new Error('The selected run changed. Wait for its saved state before acting.');
    const run=state.run_id;
    const result=await request<RunState>(path,{session_id:session.session_id,run_id:run,...extra});
    setProgress('Reading saved evidence and delivery outcomes…');
    await Promise.all([loadRun(run,session.session_id),loadSession()]);
    if(readRoute().run===run)setMessage(result.message ?? 'Saved.');
  });
  const recover=()=>handle(async()=>{
    generation.current++;await loadSession(true);setState(null);setScene(null);setEvents([]);
    history.pushState(null, '', window.location.pathname || '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  const historyPage=async(older:boolean)=>{
    if(historyLock.current || loading || working || !session || (older && !session.next_cursor))return;
    const ticket=++historyGeneration.current;
    const owner=session.session_id;
    historyLock.current=true;setHistoryLoading(true);setHistoryError('');
    try {
      const data=await request<Session>('session',{session_id:owner,...(older?{cursor:session.next_cursor}:{} )});
      if(ticket!==historyGeneration.current)return;
      if(data.session_id!==owner)throw new Error('The returned session changed. Refresh the run list.');
      setSession(current=>current?.session_id===owner?data:current);
    } catch(e){if(ticket===historyGeneration.current)setHistoryError(errorMessage(e));}
    finally {historyLock.current=false;setHistoryLoading(false);}
  };
  return {route,session,state,scene,events,busy:loading||working,error,requiresRefresh,message,progress,create,act,handle,
    historyLoading,historyError,olderRuns:()=>historyPage(true),newestRuns:()=>historyPage(false),
    refresh:()=>route.run && session ? handle(()=>loadRun(route.run!,session.session_id)) : bootstrap(),recover};
}
