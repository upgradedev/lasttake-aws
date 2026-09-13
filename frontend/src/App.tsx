import {useEffect,useRef,useState} from 'react';
import {Actions} from './Actions';
import {Dashboard} from './Dashboard';
import {History} from './History';
import {Intake} from './Intake';
import {Records} from './Records';
import {SceneView} from './SceneView';
import {WorkflowNext} from './WorkflowNext';
import {UserJourneysView} from './UserJourneysView';
import {ArchitectureView} from './ArchitectureView';
import {GtmProductionView} from './GtmProductionView';
import {link,pages,roles} from './model';
import {useWorkspace} from './useWorkspace';
import {readPreference,writePreference,storageNotice} from './storage';
import type {Page,Role} from './types';

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
  const isDocPage=route.page==='journeys' || route.page==='architecture' || route.page==='roi';
  const writesBlocked=w.busy || w.requiresRefresh;
  const showWelcome=!state && !w.busy && !w.error;

  return <div className="app-shell">
    <a href="#main" className="skip-link" onClick={e=>{e.preventDefault();document.getElementById('main')?.focus();}}>Skip to main content</a>
    <aside className="navigation">
      <a className="brand" href={link('overview',state?.run_id)}><span className="brand-mark" aria-hidden="true">L<span>◢</span></span><span>LASTTAKE<small>BEFORE THE SET COMES DOWN</small></span></a>
      <p className="nav-label">Production cockpit</p>
      <nav aria-label="Main navigation">
        {(['overview','scene','records','history'] as Page[]).map((key,index)=>(
          <a key={key} href={link(key,state?.run_id ?? route.run,undefined,selection)} aria-current={route.page===key || (key==='scene' && route.page==='actions')?'page':undefined}>
            <span aria-hidden="true">{['◫','▤','▦','↗'][index]}</span>{pages[key]}
          </a>
        ))}
        <a href={link('journeys',state?.run_id ?? route.run)} aria-current={route.page==='journeys'?'page':undefined}><span aria-hidden="true">★</span>Journeys</a>
        <a href={link('architecture',state?.run_id ?? route.run)} aria-current={route.page==='architecture'?'page':undefined}><span aria-hidden="true">⚙</span>Architecture</a>
        <a href={link('roi',state?.run_id ?? route.run)} aria-current={route.page==='roi'?'page':undefined}><span aria-hidden="true">◈</span>Production ROI</a>
      </nav>
      <div className="nav-bottom">
        <p className="synthetic">Synthetic demo</p>
        <p>One fictional production.<br/>Evidence before decisions.</p>
        <button className="guide-toggle" aria-pressed={guided} onClick={()=>setGuided(!guided)}>{guided?'Close guided demo':'Open guided demo'}</button>
        <div style={{marginTop:'8px',fontSize:'0.75rem',display:'flex',flexDirection:'column',gap:'4px'}}>
          <a href="/acceptance.html" style={{color:'var(--muted)'}}>Current automated acceptance</a>
          <a href="/UAT.testbook.html" style={{color:'var(--muted)'}}>UAT testbook</a>
        </div>
      </div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="topbar-title"><span className="production-dot" aria-hidden="true"/>The Last Ferry <span className="muted">/ {scene?.scene_id ?? 'Fictional scene'}{scene?.revision?` · ${scene.revision}`:''}</span></div>
        <div className="execution-mode" data-testid="execution-mode">Synthetic demo · No footage/audio analysis or legal clearance. Demo roles are not staff authentication. <details><summary>How this demo checks evidence</summary>Scripted planner · {state?.interpreter ?? 'Offline lexical interpreter'} · Real Strands approvals. The workflow reconciles supplied records and keeps material decisions with people.</details></div>
        <div className="topbar-controls">
          <label>Demo role<select value={role} onChange={e=>{setRole(e.target.value as Role);writePreference('lasttake.role',e.target.value);}}>{Object.entries(roles).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        </div>
      </header>

      <main id="main" tabIndex={-1} aria-busy={w.busy}>
        {isDocPage && route.page==='journeys' && <UserJourneysView runId={state?.run_id ?? route.run ?? undefined}/>}
        {isDocPage && route.page==='architecture' && <ArchitectureView runId={state?.run_id ?? route.run ?? undefined}/>}
        {isDocPage && route.page==='roi' && <GtmProductionView runId={state?.run_id ?? route.run ?? undefined}/>}

        {!isDocPage && <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">Shoot day · {scene?.revision ?? 'Fictional production'}</p>
              <h1 id="page-title" tabIndex={-1}>{!state && !route.run?'Know what still blocks wrap.':pages[route.page]}</h1>
              <p>{!state && !route.run?'For the script supervisor and 1st AD: reconcile the shoot-day evidence, record the human wrap decision and give editorial a traceable handoff.':route.page==='scene'?'Reconcile the scene. Review the sources. Record the human decision.':route.page==='records'?'Inspect the supplied records and trace them back to the scene.':route.page==='actions'?'A decision belongs to a person and the exact evidence they reviewed.':route.page==='history'?'Saved runs, versioned handoffs and the event record.':'Current scene, current run. Evidence before wrap.'}</p>
            </div>
            <div className="toolbar">
              {state && <button disabled={w.busy} onClick={()=>void w.refresh()}>Refresh saved state</button>}
              {showWelcome?<button className="primary" onClick={()=>void w.create()}>Start this fictional shoot day</button>:<button disabled={w.busy} onClick={()=>{setIntake(false);void w.create();}}>New shoot-day run</button>}
            </div>
          </div>

          {guided && <section className="guide panel"><h2>Walk through a fictional shoot day</h2><ol><li>Start the shoot day and run the wrap checkpoint.</li><li>Review the script and sources in Scene review, then answer the pickup request as the 1st AD.</li><li>Add evidence using the labelled synthetic examples.</li><li>Select changed findings and review them as the script supervisor and DIT.</li><li>Request a new wrap approval, answer as the 1st AD, then publish the turnover in Handoff.</li></ol><p>This demo uses a scripted planner and an offline lexical interpreter with real Strands interrupts. No Bedrock inference, footage/audio analysis, email or payment occurs in these demo flows. AWS event-bus requests are real; acceptance does not establish downstream completion.</p></section>}

          {showWelcome && <section className="welcome panel" aria-label="Start a shoot-day review">
            <p className="eyebrow">Find the gap while a pickup is still possible</p>
            <h2>Bring the shoot day into focus.</h2>
            <p>Start with The Last Ferry's script, take reports and releases. Follow each blocking reason to its evidence, resolve it with the responsible role, then request a separate wrap decision.</p>
            <p><strong>Your result:</strong> a saved editorial turnover with the take map, human decisions and any accepted exceptions still visible.</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', margin: '14px 0', padding: '12px', background: 'var(--raised, #1e293b)', borderRadius: '6px', border: '1px solid var(--border)' }}>
              <div><span style={{ fontSize: '0.75rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Prevented Pickup Cost</span><strong style={{ display: 'block', color: 'var(--teal, #14b8a6)', fontSize: '1.1rem' }}>$50,000 – $250,000</strong></div>
              <div><span style={{ fontSize: '0.75rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Time to Verify Wrap</span><strong style={{ display: 'block', color: 'var(--amber, #f59e0b)', fontSize: '1.1rem' }}>&lt; 5 Seconds</strong></div>
              <div><span style={{ fontSize: '0.75rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Audit Integrity</span><strong style={{ display: 'block', color: '#38bdf8', fontSize: '1.1rem' }}>Cryptographic S3 Seal</strong></div>
            </div>
            <p className="fine">Synthetic records are already supplied. No upload or account is required.</p>
            <div className="toolbar" style={{ marginTop: '12px' }}>
              <button className="primary" onClick={()=>void w.create()}>Start this fictional shoot day</button>
              <button onClick={()=>void w.create()}>New shoot-day run</button>
              <a className="button" href={link('journeys', route.run)}>4 User Journeys →</a>
              <a className="button" href={link('architecture', route.run)}>Architecture →</a>
              <a className="button" href={link('roi', route.run)}>Production ROI →</a>
            </div>
          </section>}

          {storageNotice() && <p className="warning" role="status">{storageNotice()}</p>}
          {w.busy && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>{w.progress || 'Reading the saved shoot day…'}</div>}
          {w.error && <div className="error" role="alert"><h2>We couldn't complete that request</h2><p>{w.error}</p><p>{w.requiresRefresh?'Refresh saved state before retrying a write. Your form entries are kept. Displayed evidence may be out of date.':'The server refused the invalid request. Correct the supplied fields and submit again; your entries are kept.'}</p><div className="toolbar"><button disabled={w.busy} onClick={()=>void w.refresh()}>Retry loading saved state</button>{!state && <button disabled={w.busy} onClick={()=>void w.recover()}>Start a separate session</button>}</div></div>}
          {state?.needs_checkpoint && <section className="warning" role="status"><h2>Fresh checkpoint required</h2><p>{state.recovery_reason}</p>{state.pending_approval?<p>Open the pending approval in Workspace and decline it before checking again.</p>:<button disabled={writesBlocked} onClick={()=>void w.act('checkpoint')}>Run fresh checkpoint</button>}</section>}
          {w.message && <p className="saved" role="status">{w.message}</p>}

          {state && scene && <>
            <WorkflowNext state={state} scene={scene} requiresRefresh={w.requiresRefresh} detailed={route.page==='overview'}/>
            {route.page==='overview' && <Dashboard scene={scene} state={state} session={w.session} events={w.events} busy={writesBlocked} checkpoint={()=>void w.act('checkpoint')}/>}
            {(route.page==='scene'||route.page==='records') && <><div className="toolbar scene-actions"><span className="fine">{state.counts?state.headline:'Not assessed yet. Absent evidence is never a pass.'}</span>{!state.counts && <button className="primary" disabled={writesBlocked || !!state.pending_approval} onClick={()=>void w.act('checkpoint')}>Run wrap checkpoint</button>}<button disabled={w.busy} onClick={()=>setIntake(!intake)} aria-expanded={intake}>Add take or release</button></div>{intake && <Intake key={state.run_id} scene={scene} busy={w.busy} writeBlocked={w.requiresRefresh} guided={guided} onClose={()=>setIntake(false)} onSubmit={(kind,document)=>w.act('ingest',{kind,document})}/>}</>}
            {route.page==='scene' && <SceneView key={state.run_id} scene={scene} state={state} selected={route.beat} selection={selection} role={role} busy={writesBlocked} act={w.act}/>}
            {route.page==='records' && <Records key={state.run_id} scene={scene} state={state} selection={selection}/>}
            {route.page==='actions' && <><p className="scope-note">This saved actions link remains available. <a href={link('scene',state.run_id,undefined,selection)}>Open the integrated workspace</a></p><Actions scene={scene} state={state} role={role} busy={writesBlocked} act={w.act}/></>}
            {route.page==='history' && w.session && <History key={state.run_id} state={state} session={w.session} events={w.events} role={role} busy={writesBlocked} act={w.act} handle={w.handle} historyLoading={w.historyLoading} historyError={w.historyError} olderRuns={w.olderRuns} newestRuns={w.newestRuns}/>}
            <footer><details><summary>Run details & execution labels</summary><dl className="metadata"><dt>Saved run</dt><dd>{state.run_id}</dd><dt>Production / scene</dt><dd>{state.production_id} / {state.scene_id}</dd><dt>Framework</dt><dd>Strands Agents SDK</dd><dt>Planner</dt><dd>offline-scripted/1.0.0</dd><dt>Interpreter reported by API</dt><dd>{state.interpreter}</dd><dt>State store reported by API</dt><dd>{state.run_state_store}</dd><dt>Policy</dt><dd>{scene.policy_version}</dd></dl><p>Demo role selection is not staff authentication. The browser holds a session handle and preferences; records and decisions are stored by the backend.</p></details><p>Synthetic records only. This workflow reconciles supplied evidence; it does not determine creative quality or legal sufficiency.</p><p><a href="/acceptance.html">Current automated acceptance</a> · <a href="/UAT.testbook.html">UAT testbook</a></p></footer>
          </>}
        </>}
      </main>
    </div>
  </div>;
}
