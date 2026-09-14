import {useCallback,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ApiError,errorMessage,request} from './api';
import {
  clearOfflineScope,prepareOfflineShell,readEvidenceDraft,readWorkspaceSnapshot,
  rebaseEvidenceDraft,writeWorkspaceSnapshot,
} from './connectivity';
import type {Connectivity,WorkspaceSnapshot} from './connectivity';
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
const networkAvailable=()=>typeof navigator==='undefined' || navigator.onLine!==false;
type RevisionChange={from:string;to:string};
type LoadMode='authoritative'|'mutation';

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
  const [connectivity,setConnectivity]=useState<Connectivity>(()=>networkAvailable()?'checking':'offline');
  const [lastConfirmedAt,setLastConfirmedAt]=useState<string|null>(null);
  const [usingCachedState,setUsingCachedState]=useState(false);
  const [unknownOutcome,setUnknownOutcome]=useState<string|null>(null);
  const [revisionChanged,setRevisionChanged]=useState<RevisionChange|null>(null);
  const [offlineShellReady,setOfflineShellReady]=useState(false);
  const historyGeneration=useRef(0);
  const historyLock=useRef(false);
  const lock=useRef(false);
  const generation=useRef(0);
  const sessionRef=useRef<Session|null>(null);
  const stateRef=useRef<RunState|null>(null);
  const unknownOutcomeRef=useRef<string|null>(null);
  const refreshRef=useRef<()=>Promise<boolean>>(async()=>false);

  const needRefresh=useCallback((value:boolean)=>setRequiresRefresh(value),[]);
  const connection=useCallback((value:Connectivity)=>setConnectivity(value),[]);
  useEffect(()=>{setMessage('');},[route.page]);
  useEffect(()=>{void prepareOfflineShell().then(setOfflineShellReady);},[]);

  const applyCached=useCallback((cached:WorkspaceSnapshot)=>{
    sessionRef.current=cached.session;stateRef.current=cached.state;
    setSession(cached.session);setState(cached.state);setScene(cached.scene);setEvents(cached.events);
    setLastConfirmedAt(cached.confirmed_at);setUsingCachedState(true);needRefresh(true);
    connection(networkAvailable()?'uncertain':'offline');
  },[connection,needRefresh]);

  const restoreCached=useCallback((sessionId:string,runId:string)=>{
    const cached=readWorkspaceSnapshot(sessionId,runId);
    if(!cached)return false;
    applyCached(cached);return true;
  },[applyCached]);

  const handle=useCallback(async (work:()=>Promise<void>,mutation?:string)=>{
    if(lock.current)return false;
    lock.current=true;setWorking(true);setProgress(mutation?'Sending request…':'Reading saved state…');setError('');setMessage('');
    try {
      await work();needRefresh(false);return true;
    } catch(e) {
      const knownRefusal=e instanceof ApiError && e.status<500;
      setError(errorMessage(e));needRefresh(!(e instanceof ApiError && e.status===400));
      if(knownRefusal)connection('online');
      else {
        connection(networkAvailable()?'uncertain':'offline');
        if(stateRef.current)setUsingCachedState(true);
        if(mutation){unknownOutcomeRef.current=mutation;setUnknownOutcome(mutation);}
      }
      return false;
    } finally {
      lock.current=false;setWorking(false);setProgress('');
    }
  },[connection,needRefresh]);

  const loadSession=useCallback(async(newSession=false)=>{
    const ticket=++historyGeneration.current;
    const saved=newSession ? null : readPreference('lasttake.session');
    const data=await request<Session>('session',saved?{session_id:saved}:{});
    if(ticket===historyGeneration.current){
      writePreference('lasttake.session',data.session_id);sessionRef.current=data;setSession(data);setHistoryError('');
    }
    return data;
  },[]);

  const loadRun=useCallback(async(runId:string,sessionId:string,mode:LoadMode='authoritative')=>{
    const ticket=++generation.current;
    const previous=readWorkspaceSnapshot(sessionId,runId);
    const draft=readEvidenceDraft(sessionId,runId);
    const body={run_id:runId,session_id:sessionId};
    const [current,script,history]=await Promise.all([
      request<RunState>('state',body),request<Scene>('scene',body),request<{events:EventRow[]}>('events',body),
    ]);
    if(ticket!==generation.current || readRoute().run!==runId)return;
    const owner=sessionRef.current;
    if(!owner || owner.session_id!==sessionId)throw new Error('The saved session changed while reading this run. Refresh the workspace.');
    const confirmedAt=new Date().toISOString();
    stateRef.current=current;setState(current);setScene(script);setEvents(history.events);
    setLastConfirmedAt(confirmedAt);setUsingCachedState(false);connection('online');
    const base=draft?.base_revision_digest ?? previous?.state.package_revision_digest;
    setRevisionChanged(mode==='authoritative' && base && base!==current.package_revision_digest?{from:base,to:current.package_revision_digest}:null);
    writeWorkspaceSnapshot({schema:'lasttake/offline-snapshot/v1',session_id:sessionId,run_id:runId,
      confirmed_at:confirmedAt,session:owner,state:current,scene:script,events:history.events});
  },[connection]);

  const bootstrap=useCallback(async()=>{
    setLoading(true);setError('');
    const currentRoute=readRoute();
    const saved=readPreference('lasttake.session');
    if(!networkAvailable() && saved && currentRoute.run && restoreCached(saved,currentRoute.run)){
      setLoading(false);return;
    }
    // Loading the session is enough. Choosing a run is the person's decision:
    // the landing page offers the saved shoot day to continue, or a fresh one.
    try {await loadSession();connection('online');}
    catch(e){
      const restored=Boolean(saved && currentRoute.run && restoreCached(saved,currentRoute.run));
      setError(restored?'The service is unreachable. The last confirmed snapshot is shown read-only.':errorMessage(e));
      needRefresh(true);connection(networkAvailable()?'uncertain':'offline');
    } finally {setLoading(false);}
  },[connection,loadSession,needRefresh,restoreCached]);

  useEffect(()=>{void bootstrap();},[bootstrap]);
  const sessionId=session?.session_id;
  useEffect(()=>{
    if(!sessionId || !route.run)return;
    const runId=route.run;
    let active=true;
    if(!networkAvailable()){
      if(!restoreCached(sessionId,runId)){
        setError('No confirmed snapshot is available for this run. Reconnect to read it.');needRefresh(true);connection('offline');
      }
      setLoading(false);return;
    }
    setState(null);stateRef.current=null;setScene(null);setEvents([]);setMessage('');setError('');setLoading(true);
    void loadRun(runId,sessionId).then(()=>{if(active)needRefresh(false);}).catch(e=>{
      if(active){restoreCached(sessionId,runId);setError(errorMessage(e));needRefresh(true);connection(networkAvailable()?'uncertain':'offline');}
    }).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;generation.current++;};
  },[route.run,sessionId,connection,loadRun,needRefresh,restoreCached]);

  const refresh=useCallback(()=>handle(async()=>{
    connection('checking');needRefresh(true);
    const selected=readRoute().run;
    const data=await loadSession();
    if(selected)await loadRun(selected,data.session_id,'authoritative');
    const uncertain=unknownOutcomeRef.current;
    unknownOutcomeRef.current=null;setUnknownOutcome(null);
    if(uncertain)setMessage(`Saved state re-read from the server. The ${uncertain} request was not replayed.`);
  }),[connection,handle,loadRun,loadSession,needRefresh]);
  refreshRef.current=refresh;

  useEffect(()=>{
    const offline=()=>{
      connection('offline');needRefresh(Boolean(stateRef.current));setUsingCachedState(Boolean(stateRef.current));setMessage('');
    };
    const online=()=>{connection('checking');needRefresh(Boolean(stateRef.current));void refreshRef.current();};
    window.addEventListener('offline',offline);window.addEventListener('online',online);
    return ()=>{window.removeEventListener('offline',offline);window.removeEventListener('online',online);};
  },[connection,needRefresh]);

  const create=async()=>{
    if(!networkAvailable() || connectivity!=='online'){
      setError('Reconnect before starting a new shoot-day run. Nothing was sent.');needRefresh(true);return false;
    }
    return handle(async()=>{
      const data=session ?? await loadSession();
      const result=await request<{run_id:string}>('reset',{session_id:data.session_id});
      await loadSession();
      if(location.search)history.replaceState(null,'',location.pathname);
      location.hash=link('scene',result.run_id);
    },'new-run');
  };

  const act=async(path:string,extra:Document={})=>{
    if(!networkAvailable() || connectivity!=='online' || requiresRefresh || revisionChanged){
      setError('This workspace is read-only until the current saved revision is confirmed. Nothing was sent.');needRefresh(true);return false;
    }
    return handle(async()=>{
      if(!state || !session || readRoute().run!==state.run_id)throw new Error('The selected run changed. Wait for its saved state before acting.');
      const run=state.run_id;
      const result=await request<RunState>(path,{session_id:session.session_id,run_id:run,...extra});
      setProgress('Reading saved evidence and delivery outcomes…');
      await Promise.all([loadRun(run,session.session_id,'mutation'),loadSession()]);
      if(readRoute().run===run)setMessage(result.message ?? 'Saved.');
    },path);
  };

  const recover=()=>handle(async()=>{
    const oldSession=sessionRef.current;const oldRun=readRoute().run;
    if(oldSession && oldRun)clearOfflineScope(oldSession.session_id,oldRun);
    generation.current++;await loadSession(true);stateRef.current=null;setState(null);setScene(null);setEvents([]);setRevisionChanged(null);location.hash='#overview';
  });

  const historyPage=async(older:boolean)=>{
    if(historyLock.current || loading || working || connectivity!=='online' || !session || (older && !session.next_cursor))return;
    const ticket=++historyGeneration.current;
    const owner=session.session_id;
    historyLock.current=true;setHistoryLoading(true);setHistoryError('');
    try {
      const data=await request<Session>('session',{session_id:owner,...(older?{cursor:session.next_cursor}:{} )});
      if(ticket!==historyGeneration.current)return;
      if(data.session_id!==owner)throw new Error('The returned session changed. Refresh the run list.');
      sessionRef.current=data;setSession(current=>current?.session_id===owner?data:current);
    } catch(e){if(ticket===historyGeneration.current)setHistoryError(errorMessage(e));}
    finally {historyLock.current=false;setHistoryLoading(false);}
  };

  const acknowledgeRevision=()=>{
    if(session && state)rebaseEvidenceDraft(session.session_id,state.run_id,state.package_revision_digest);
    setRevisionChanged(null);setError('');
  };

  return {route,session,state,scene,events,busy:loading||working,error,requiresRefresh,message,progress,create,act,handle,
    connectivity,lastConfirmedAt,usingCachedState,unknownOutcome,revisionChanged,offlineShellReady,acknowledgeRevision,
    historyLoading,historyError,olderRuns:()=>historyPage(true),newestRuns:()=>historyPage(false),refresh,recover};
}
