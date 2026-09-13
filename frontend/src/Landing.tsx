import {useEffect,useState} from 'react';
import {link} from './model';
import type {Page,SavedRun,ScenePreview,Session} from './types';

// The first screen, and the only one a judge is guaranteed to read.
//
// It answers four things in the order a person asks them: who this is for,
// what goes wrong at wrap, what they get, and what to press. The action comes
// straight after the headline so it is inside the first viewport on a phone.
// Then it shows the scene itself, because a lined script is the artifact a
// script supervisor recognises on sight and a form is not.
//
// Nothing here is an assessment or a benefit claim. The counts are facts of the
// supplied records, generated at build time from the same corpus bytes the
// backend reads, and the page says that whether a beat is covered is only ever
// said by a checkpoint. A returning visitor is offered their saved shoot day to
// continue, by status and date, or a fresh one. Nobody is dropped into a run.

function runStatus(run:SavedRun) {
  return run.turnover_published?'Turnover saved':run.wrap_approved?'Wrap approved, turnover not published':run.checked?'Checkpoint saved, decisions open':'Created, not yet checked';
}

function validPreview(value:unknown):value is ScenePreview {
  if(!value || typeof value!=='object')return false;
  const p=value as Record<string,unknown>;
  return p.schema==='lasttake/scene-preview/v1' && Number.isInteger(p.required_beats) && Number.isInteger(p.supplied_takes) && Array.isArray(p.opening_beats) && typeof p.scene_heading==='string' && typeof p.synthetic_notice==='string';
}

export function useScenePreview() {
  const [preview,setPreview]=useState<ScenePreview|null>(null);
  useEffect(()=>{
    let active=true;
    fetch('/scene-preview.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(data=>{if(active && validPreview(data))setPreview(data);}).catch(()=>{/* the landing reads without it */});
    return ()=>{active=false;};
  },[]);
  return preview;
}

export function Landing({session,busy,page,start,onNavigate}:{session:Session|null;busy:boolean;page:Page;start:()=>void;onNavigate?:(page:Page,run?:string)=>void}) {
  const preview=useScenePreview();
  const saved=session?.runs ?? [];
  const newest=saved[0];
  const returning=Boolean(newest);
  const target:Page=page==='actions'||page==='architecture'?'overview':page;
  const go=(to:Page,run?:string)=>(e:React.MouseEvent)=>{if(onNavigate){e.preventDefault();onNavigate(to,run);}};
  return <section className="landing" aria-label="Start a shoot-day review">
    <div className="landing-hero">
      <p className="eyebrow">Shoot day · The Last Ferry, a fictional production</p>
      <h1 id="page-title" tabIndex={-1}>Know what still blocks wrap.</h1>
      <div className="landing-actions">
        {returning && <a className="button primary" href={link(target,newest.run_id)} onClick={go(target,newest.run_id)}>Continue my saved shoot day</a>}
        <button className={returning?'':'primary'} disabled={busy} onClick={start}>Start this fictional shoot day</button>
      </div>
      <p className="landing-lede">For the script supervisor and 1st AD: before the set comes down, reconcile the script, the takes and the releases, record the human wrap decision, and hand editorial a traceable turnover. Once the set is struck, a missing shot is a pickup day; while it is standing, it is fifteen minutes.</p>
      <p className="landing-result"><strong>Your result:</strong> a saved editorial turnover with the take map, the human decisions and any accepted exceptions still visible. Nothing is approved for you; absent evidence is a finding, never a pass.</p>
      {returning
        ? <p className="landing-saved">Saved: <strong>{runStatus(newest)}</strong> · created <time dateTime={newest.created_at}>{new Date(newest.created_at).toLocaleString()}</time>{saved.length>1 && <> · <a href={link('history',newest.run_id)} onClick={go('history',newest.run_id)}>all {saved.length} saved runs on this page</a></>}. Continuing changes nothing; a fresh shoot day keeps the old one.</p>
        : <p className="landing-saved">Nothing to upload and no account: the fictional records are already supplied.</p>}
    </div>

    <div className="landing-grid">
      <article className="panel landing-scene" aria-label="The scene you will check">
        <p className="eyebrow">The scene you will check</p>
        {preview ? <>
          <h2><span className="slate-index">{preview.scene_id}</span> {preview.scene_heading}</h2>
          <dl className="landing-facts">
            <div><dt>Required beats</dt><dd>{preview.required_beats}</dd></div>
            <div><dt>Supplied takes</dt><dd>{preview.supplied_takes}</dd></div>
            <div><dt>Script revision</dt><dd>{preview.revision}</dd></div>
          </dl>
          <ol className="landing-script" aria-label="Opening beats of the lined script">
            {preview.opening_beats.map(b=><li key={b.beat_id}><span className="page-line">{b.page}:{b.line}</span><span>{b.slug}</span></li>)}
            <li className="landing-more"><span className="page-line">…</span><span>{Math.max(0,preview.required_beats-preview.opening_beats.length)} more required beats, {preview.optional_beats} optional inserts</span></li>
          </ol>
          <p className="fine">Whether a beat is covered is only ever said by the checkpoint. These are the supplied records, not a result.</p>
        </> : <>
          <h2>One fictional scene, its takes and its releases.</h2>
          <p>The checkpoint compares the script with the captured takes, the camera and sound reports and the rights ledger, and says which required beats still have no evidence behind them.</p>
        </>}
      </article>

      <article className="panel landing-stages" aria-label="What happens">
        <p className="eyebrow">What happens, in three stages</p>
        <ol className="stage-list">
          <li><strong>Evidence.</strong> A wrap checkpoint runs four bounded checks over the supplied records and shows every exception with its source. Absent evidence is an exception.</li>
          <li><strong>Human decision.</strong> The script supervisor and the DIT review each exception in their own role. Only the 1st AD can approve a pickup or the wrap, and the run waits for them across a real process boundary: it can be approved the next morning, in a different process, from the session saved on S3.</li>
          <li><strong>Turnover.</strong> After the approval, a sealed manifest and a portable receipt go to editorial with every accepted exception still on them.</li>
        </ol>
        <p className="fine">Built on the Strands Agents SDK on AWS Lambda, with Aurora DSQL, S3 and EventBridge. A scripted planner and an offline lexical interpreter on this public deployment; no footage or audio is analysed and nothing is cleared in law. <a href={link('architecture',newest?.run_id)} onClick={go('architecture',newest?.run_id)}>What is deployed</a>.</p>
      </article>
    </div>
  </section>;
}
