import {useCallback,useEffect,useRef,useState} from 'react';
import {Actions} from './Actions';
import {ArchitectureView} from './ArchitectureView';
import {Dashboard} from './Dashboard';
import {History} from './History';
import {Intake} from './Intake';
import {Landing} from './Landing';
import {Records} from './Records';
import {SceneView} from './SceneView';
import {WorkflowNext} from './WorkflowNext';
import {WrapBoard} from './WrapBoard';
import {link,pages,pageTasks,roles} from './model';
import {useWorkspace} from './useWorkspace';
import {readPreference,writePreference,storageNotice} from './storage';
import type {Page,Role} from './types';

// The shell. Three rules shape it.
//
// One landing, always, before any run: a returning person chooses to continue
// their saved shoot day or start a fresh one; nobody is dropped into a run.
//
// One demo-mode statement, in the top bar, with the details behind a
// disclosure. It used to appear four times on the cold screen, and a warning
// repeated four times reads as boilerplate rather than as a limit worth knowing.
//
// Navigation named after the task: Wrap status, Scene review, Records, Handoff,
// and one page that says what is deployed. Every route underneath is unchanged,
// so saved links, the testbook and the video capture keep working.

const NAV:Page[]=['overview','scene','records','history','architecture'];

export function App() {
  const w=useWorkspace();
  const [role,setRole]=useState<Role>(()=>{const saved=readPreference('lasttake.role');return saved && Object.hasOwn(roles,saved)?saved as Role:'script_supervisor';});
  const [guided,setGuided]=useState(false);
  const [intake,setIntake]=useState(false);
  const {state,scene,route}=w;
  const previousPage=useRef(route.page);
  useEffect(()=>{if(previousPage.current!==route.page){document.getElementById('page-title')?.focus();previousPage.current=route.page;}},[route.page]);
  useEffect(()=>{setIntake(false);},[route.run]);
  const selection={beat:route.beat,finding:route.finding,filter:route.filter,record:route.record,q:route.q};

  // With a run, navigation is the hash link the rest of the app already uses.
  // Without one, the page travels in the query string so the address stays
  // clean; the hash wins whenever both are present, so a stale ?page= from the
  // cold screen can never pin a run to the wrong page.
  const navigateTo=useCallback((page:Page,run?:string|null)=>{
    const activeRun=run ?? state?.run_id ?? route.run;
    if(activeRun){
      const next=link(page,activeRun,undefined,run?{}:selection);
      if(location.search)history.replaceState(null,'',window.location.pathname);
      location.hash=next;
      return;
    }
    const nextUrl=page==='overview'?window.location.pathname:`?page=${page}`;
    history.pushState(null,'',nextUrl);
    window.dispatchEvent(new PopStateEvent('popstate'));
  },[state?.run_id,route.run,selection]);
  const backToStart=()=>{history.pushState(null,'',window.location.pathname);window.dispatchEvent(new PopStateEvent('popstate'));};

  const writesBlocked=w.busy || w.requiresRefresh;
  const inRun=Boolean(state && scene);
  const isDoc=route.page==='architecture';
  const showLanding=!route.run && !isDoc && !w.busy && !w.error;

  return <div className="app-shell">
    <a href="#main" className="skip-link" onClick={e=>{e.preventDefault();document.getElementById('main')?.focus();}}>Skip to main content</a>
    <aside className="navigation">
      <a className="brand" href={window.location.pathname} onClick={e=>{e.preventDefault();backToStart();}}><span className="brand-mark" aria-hidden="true">L<span>◢</span></span><span>LASTTAKE<small>BEFORE THE SET COMES DOWN</small></span></a>
      <nav aria-label="Main navigation">
        {NAV.map(key=><a key={key} aria-label={pages[key]} href={state?.run_id ?? route.run?link(key,state?.run_id ?? route.run,undefined,selection):(key==='overview'?window.location.pathname:`?page=${key}`)} onClick={e=>{e.preventDefault();navigateTo(key);}} aria-current={route.page===key || (key==='scene' && route.page==='actions')?'page':undefined}><span className="nav-name">{pages[key]}</span><small>{pageTasks[key]}</small></a>)}
      </nav>
      <div className="nav-bottom">
        <p>Proof of this release</p>
        <a href="/acceptance.html">Current automated acceptance</a>
        <a href="/UAT.testbook.html">UAT testbook</a>
      </div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="topbar-title"><span className="production-dot" aria-hidden="true"/>The Last Ferry <span className="muted">/ {scene?.scene_id ?? 'Fictional scene'}{scene?.revision?` · ${scene.revision}`:''}</span></div>
        <div className="execution-mode" data-testid="execution-mode">Synthetic demo · No footage/audio analysis or legal clearance. Demo roles are not staff authentication. <details><summary>How this demo checks evidence</summary>Scripted planner · {state?.interpreter ?? 'Offline lexical interpreter'} · Real Strands approvals. The workflow reconciles supplied records and keeps material decisions with people.</details></div>
        <div className="topbar-controls">
          <label>Demo role<select value={role} onChange={e=>{setRole(e.target.value as Role);writePreference('lasttake.role',e.target.value);}}>{Object.entries(roles).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
          <button className="guide-toggle" aria-pressed={guided} onClick={()=>setGuided(!guided)}>{guided?'Close guided demo':'Open guided demo'}</button>
        </div>
      </header>

      <main id="main" tabIndex={-1} aria-busy={w.busy}>
        {guided && <section className="guide panel"><h2>Walk through a fictional shoot day</h2><ol><li>Start the shoot day and run the wrap checkpoint.</li><li>Review the script and sources in Scene review, then answer the pickup request as the 1st AD.</li><li>Add evidence using the labelled synthetic examples.</li><li>Select changed findings and review them as the script supervisor and DIT.</li><li>Request a new wrap approval, answer as the 1st AD, then publish the turnover in Handoff.</li></ol><p>This demo uses a scripted planner and an offline lexical interpreter with real Strands interrupts. No Bedrock inference, footage/audio analysis, email or payment occurs in these demo flows. AWS event-bus requests are real; acceptance does not establish downstream completion.</p></section>}
        {storageNotice() && <p className="warning" role="status">{storageNotice()}</p>}
        {w.busy && !inRun && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>{w.progress || 'Reading the saved shoot day…'}</div>}
        {w.error && <div className="error" role="alert"><h2>We couldn't complete that request</h2><p>{w.error}</p><p>{w.requiresRefresh?'Refresh saved state before retrying a write. Your form entries are kept. Displayed evidence may be out of date.':'The server refused the invalid request. Correct the supplied fields and submit again; your entries are kept.'}</p><div className="toolbar"><button disabled={w.busy} onClick={()=>void w.refresh()}>Retry loading saved state</button>{!state && <button disabled={w.busy} onClick={()=>void w.recover()}>Start a separate session</button>}{!state && <button type="button" onClick={backToStart}>Back to the start</button>}</div></div>}

        {isDoc && <ArchitectureView runId={state?.run_id ?? route.run ?? undefined}/>}
        {showLanding && <Landing session={w.session} busy={w.busy} page={route.page} start={()=>void w.create()} onNavigate={navigateTo}/>}

        {inRun && !isDoc && state && scene && <>
          <div className="page-heading">
            <div><p className="eyebrow">Shoot day · {scene.revision}</p><h1 id="page-title" tabIndex={-1}>{pages[route.page]}</h1><p>{pageTasks[route.page]}</p></div>
            <div className="toolbar"><button disabled={w.busy} onClick={()=>void w.refresh()}>Refresh saved state</button><button disabled={w.busy} onClick={()=>{setIntake(false);void w.create();}}>New shoot-day run</button></div>
          </div>
          {w.busy && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>{w.progress || 'Reading the saved shoot day…'}</div>}
          {state.needs_checkpoint && <section className="warning" role="status"><h2>Fresh checkpoint required</h2><p>{state.recovery_reason}</p>{state.pending_approval?<p>Open the pending approval in Scene review and decline it before checking again.</p>:<button disabled={writesBlocked} onClick={()=>void w.act('checkpoint')}>Run fresh checkpoint</button>}</section>}
          {w.message && <p className="saved" role="status">{w.message}</p>}
          <WorkflowNext state={state} scene={scene} requiresRefresh={w.requiresRefresh} detailed={route.page==='overview'}/>
          {route.page==='overview' && <Dashboard scene={scene} state={state} session={w.session} events={w.events} busy={writesBlocked} checkpoint={()=>void w.act('checkpoint')}/>}
          {(route.page==='scene'||route.page==='records') && <>
            <WrapBoard state={state} scene={scene}/>
            <div className="toolbar scene-actions">
              <span className="fine">{state.counts?state.headline:'Not assessed yet. Absent evidence is never a pass.'}</span>
              {!state.counts && <button className="primary" disabled={writesBlocked || !!state.pending_approval} onClick={()=>void w.act('checkpoint')}>Run wrap checkpoint</button>}
              <button disabled={w.busy} onClick={()=>setIntake(!intake)} aria-expanded={intake}>Add take or release</button>
            </div>
            {intake && <Intake key={state.run_id} scene={scene} busy={w.busy} writeBlocked={w.requiresRefresh} guided={guided} onClose={()=>setIntake(false)} onSubmit={(kind,document)=>w.act('ingest',{kind,document})}/>}
          </>}
          {route.page==='scene' && <SceneView key={state.run_id} scene={scene} state={state} selected={route.beat} selection={selection} role={role} busy={writesBlocked} act={w.act}/>}
          {route.page==='records' && <Records key={state.run_id} scene={scene} state={state} selection={selection}/>}
          {route.page==='actions' && <><p className="scope-note">This saved actions link remains available. <a href={link('scene',state.run_id,undefined,selection)}>Open the integrated workspace</a></p><Actions scene={scene} state={state} role={role} busy={writesBlocked} act={w.act}/></>}
          {route.page==='history' && w.session && <History key={state.run_id} state={state} session={w.session} events={w.events} role={role} busy={writesBlocked} act={w.act} handle={w.handle} historyLoading={w.historyLoading} historyError={w.historyError} olderRuns={w.olderRuns} newestRuns={w.newestRuns}/>}
          <footer>
            <details><summary>Run details & execution labels</summary><dl className="metadata"><dt>Saved run</dt><dd>{state.run_id}</dd><dt>Production / scene</dt><dd>{state.production_id} / {state.scene_id}</dd><dt>Framework</dt><dd>Strands Agents SDK</dd><dt>Planner</dt><dd>offline-scripted/1.0.0</dd><dt>Interpreter reported by API</dt><dd>{state.interpreter}</dd><dt>State store reported by API</dt><dd>{state.run_state_store}</dd><dt>Policy</dt><dd>{scene.policy_version}</dd></dl><p>Demo role selection is not staff authentication. The browser holds a session handle and preferences; records and decisions are stored by the backend.</p></details>
            <p>Synthetic records only. This workflow reconciles supplied evidence; it does not determine creative quality or legal sufficiency.</p>
          </footer>
        </>}
      </main>
    </div>
  </div>;
}
