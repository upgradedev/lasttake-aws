import {useCallback,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ApiError,errorMessage,request} from './api';
import {link,readRoute} from './model';
import {readPreference,writePreference} from './storage';
import type {Document,EventRow,RunState,Scene,Session} from './types';
const subscribe=(changed:()=>void)=>{window.addEventListener('hashchange',changed);return ()=>window.removeEventListener('hashchange',changed);};
const snapshot=()=>location.hash;
export function useWorkspace() {
  useSyncExternalStore(subscribe,snapshot);
  const route=readRoute();
  const [session,setSession]=useState<Session|null>(null);
  const [state,setState]=useState<RunState|null>(null);
  const [scene,setScene]=useState<Scene|null>(null);
  const [events,setEvents]=useState<EventRow[]>([]);
  const [working,setWorking]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [requiresRefresh,setRequiresRefresh]=useState(false);
  const [message,setMessage]=useState('');
  useEffect(()=>{setMessage('');},[route.page]);
  const lock=useRef(false);
  const generation=useRef(0);
  const handle=useCallback(async (work:()=>Promise<void>)=>{
    if(lock.current) return false;
    lock.current=true;setWorking(true);setError('');setMessage('');
    try {await work();setRequiresRefresh(false);return true;}catch(e){setError(errorMessage(e));setRequiresRefresh(!(e instanceof ApiError && e.status===400));return false;}
    finally{lock.current=false;setWorking(false);}
  },[]);
  const loadSession=useCallback(async(newSession=false)=>{
    const saved=newSession ? null : readPreference('lasttake.session');
    const data=await request<Session>('session', saved ? {session_id:saved} : {});
    writePreference('lasttake.session',data.session_id);
    setSession(data);return data;
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
    try {const data=await loadSession();const current=readRoute();if(!current.run && data.runs[0])location.hash=link(current.page,data.runs[0].run_id,undefined,{beat:current.beat,finding:current.finding,filter:current.filter,record:current.record,q:current.q});}
    catch(e){setError(errorMessage(e));setRequiresRefresh(true);}
    finally{setLoading(false);}
  },[loadSession]);
  useEffect(()=>{void bootstrap();},[bootstrap]);
  const sessionId=session?.session_id;
  useEffect(()=>{
    if(!sessionId || !route.run)return;
    let active=true;
    setState(null);setScene(null);setEvents([]);setMessage('');setError('');setLoading(true);
    void loadRun(route.run,sessionId).then(()=>{if(active)setRequiresRefresh(false);}).catch(e=>{if(active){setError(errorMessage(e));setRequiresRefresh(true);}}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;generation.current++;};
  },[route.run,sessionId,loadRun]);
  const create=()=>handle(async()=>{
    const data=session ?? await loadSession();
    const result=await request<{run_id:string}>('reset',{session_id:data.session_id});
    await loadSession();
    location.hash=link('scene',result.run_id);
  });
  const act=async(path:string,extra:Document={})=>handle(async()=>{
    if(!state || !session || readRoute().run!==state.run_id)throw new Error('The selected run changed. Wait for its saved state before acting.');
    const run=state.run_id;
    const result=await request<RunState>(path,{session_id:session.session_id,run_id:run,...extra});
    await loadRun(run,session.session_id);
    await loadSession();
    if(readRoute().run===run)setMessage(result.message ?? 'Saved.');
  });
  const recover=()=>handle(async()=>{
    generation.current++;await loadSession(true);setState(null);setScene(null);setEvents([]);location.hash='#overview';
  });
  return {route,session,state,scene,events,busy:loading||working,error,requiresRefresh,message,create,act,handle,
    refresh:()=>route.run && session ? handle(()=>loadRun(route.run!,session.session_id)) : bootstrap(),recover};
}
