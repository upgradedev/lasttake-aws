import {useEffect,useRef,useState} from 'react';
import {makeDocument} from './model';
import {saveJson} from './api';
import {clearEvidenceDraft,readEvidenceDraft,writeEvidenceDraft} from './connectivity';
import type {EvidenceKind} from './connectivity';
import {parseEvidenceDocument,readEvidenceFile} from './evidenceFile';
import type {Document,Scene} from './types';
const takeFields=[['take_id','Take identifier'],['slate','Slate'],['shot_id','Shot identifier'],['camera_roll','Camera roll'],['media_id','Media identifier'],['sound_roll','Sound roll'],['timecode_in','Timecode in'],['timecode_out','Timecode out'],['lens_mm','Lens (mm)'],['report_media_id','Reported media identifier'],['report_lens_mm','Reported lens (mm)'],['report_camera_roll','Reported camera roll']];
const sample:Record<string,string>={beat_id:'B-17',take_id:'T-900',slate:'42L/1',shot_id:'S-42-PICKUP',camera_roll:'A007',media_id:'A007R2G01',sound_roll:'SR07',timecode_in:'23:04:00:00',timecode_out:'23:04:41:00',lens_mm:'50',report_media_id:'A007R2G01',report_lens_mm:'50',report_camera_roll:'A007',visible_people:'DELPHINE',note:'Pickup on the reaction. Clean single.',record_id:'REL-900',subject_id:'BG-07',subject_kind:'person',document_type:'background release',scope:'all media',territory:'worldwide',status:'executed'};
export function Intake({scene,busy,writeBlocked=false,sessionId='component-session',runId='component-run',revisionDigest='component-revision',revisionReviewRequired=false,onSubmit,onClose,guided}:{scene:Scene;busy:boolean;writeBlocked?:boolean;sessionId?:string;runId?:string;revisionDigest?:string;revisionReviewRequired?:boolean;onSubmit:(kind:string,document:Document)=>Promise<boolean>;onClose:()=>void;guided:boolean}) {
  const restored=useRef(readEvidenceDraft(sessionId,runId)).current;
  const formRef=useRef<HTMLFormElement>(null);
  const jsonRef=useRef<HTMLTextAreaElement>(null);
  const [kind,setKind]=useState<EvidenceKind>(restored?.kind ?? 'take');
  const [example,setExample]=useState(false);
  const [advanced,setAdvanced]=useState(restored?.advanced ?? false);
  const [json,setJson]=useState(restored?.json ?? '');
  const [draftFields,setDraftFields]=useState<Record<string,string>>(restored?.fields ?? {});
  const [draftChecks,setDraftChecks]=useState<Record<string,boolean>>(restored?.checks ?? {});
  const [baseDigest,setBaseDigest]=useState(restored?.base_revision_digest ?? revisionDigest);
  const [draftSaved,setDraftSaved]=useState(Boolean(restored));
  const [draftWarning,setDraftWarning]=useState('');
  const [error,setError]=useState('');
  const [fileName,setFileName]=useState('');
  const [reading,setReading]=useState(false);
  const [missingReport,setMissingReport]=useState(restored?.checks.camera_report_missing ?? false);
  useEffect(()=>{
    if(!revisionReviewRequired && baseDigest!==revisionDigest){setBaseDigest(revisionDigest);}
  },[baseDigest,revisionDigest,revisionReviewRequired]);
  const initial=(name:string,fallback='')=>example?(sample[name] ?? fallback):(draftFields[name] ?? fallback);
  const initiallyChecked=(name:string,fallback=false)=>example?(name==='preferred'||name==='usable'?true:fallback):(draftChecks[name] ?? fallback);
  function persistDraft(overrides:Partial<Pick<ReturnType<typeof draftValue>,'kind'|'advanced'|'json'|'fields'|'checks'>>={}) {
    const fields:Record<string,string>={};const checks:Record<string,boolean>={};
    for(const control of Array.from(formRef.current?.elements ?? [])){
      if(!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement) || !control.name)continue;
      if(control instanceof HTMLInputElement && control.type==='checkbox')checks[control.name]=control.checked;
      else fields[control.name]=control.value;
    }
    const value=draftValue({kind,advanced,json:(jsonRef.current?.value ?? json),fields,checks,...overrides});
    setDraftFields(value.fields);setDraftChecks(value.checks);
    if(writeEvidenceDraft(value)){setDraftSaved(true);setDraftWarning('');}
    else setDraftWarning('This draft is too large or tab storage is unavailable. Download the input before leaving this page.');
  }
  function draftValue(value:{kind:EvidenceKind;advanced:boolean;json:string;fields:Record<string,string>;checks:Record<string,boolean>}) {
    return {schema:'lasttake/evidence-draft/v1' as const,session_id:sessionId,run_id:runId,base_revision_digest:baseDigest,...value,updated_at:new Date().toISOString()};
  }
  function exampleFlow(flow:'success'|'refusal'|'correction') {
    setError('');setMissingReport(false);setExample(true);
    if(flow==='success'){
      const fields={...sample,beat_id:'B-17'};const checks={preferred:true,usable:true,camera_report_missing:false};
      setKind('take');setAdvanced(false);setJson('');setDraftFields(fields);setDraftChecks(checks);
      const saved=writeEvidenceDraft(draftValue({kind:'take',advanced:false,json:'',fields,checks}));setDraftSaved(saved);setDraftWarning(saved?'':'Tab storage is unavailable. Download the input before leaving this page.');return;
    }
    setKind('rights_record');setAdvanced(true);
    const next=JSON.stringify({record_id:'REL-EDITABLE',subject_id:'BG-07',subject_kind:'person',
      document_type:'background release',scope:'all media',territory:'worldwide',status:'executed',
      expires_on:flow==='refusal'?'2026-02-30':'2030-02-28'},null,2);
    setJson(next);setDraftFields({});setDraftChecks({});
    const saved=writeEvidenceDraft(draftValue({kind:'rights_record',advanced:true,json:next,fields:{},checks:{}}));setDraftSaved(saved);setDraftWarning(saved?'':'Tab storage is unavailable. Download the input before leaving this page.');
  }
  function fillExample() {
    if(kind==='take'){exampleFlow('success');return;}
    const fields=Object.fromEntries(['record_id','subject_id','subject_kind','document_type','scope','territory','status'].map(name=>[name,sample[name]]));
    setError('');setExample(true);setDraftFields(fields);setDraftChecks({});
    const saved=writeEvidenceDraft(draftValue({kind:'rights_record',advanced,json,fields,checks:{}}));setDraftSaved(saved);setDraftWarning(saved?'':'Tab storage is unavailable. Download the input before leaving this page.');
  }
  async function submit(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();setError('');
    let doc:Document;
    try {doc=advanced ? parseEvidenceDocument(json) : makeDocument(kind,new FormData(event.currentTarget));}
    catch {setError('Enter valid JSON. Your document has been kept.');return;}
    if(await onSubmit(kind,doc)){clearEvidenceDraft(sessionId,runId);setDraftSaved(false);onClose();}
  }
  return <section className="panel intake" aria-labelledby="intake-title">
    <div className="section-heading"><div><p className="eyebrow">Supplied records</p><h2 id="intake-title">Add evidence to this shoot day</h2></div><button onClick={onClose} disabled={busy}>Close form</button></div>
    <p>Use fictional records only. Saving reruns the checks affected by the supplied evidence. Fill the form below; a JSON file or pasted JSON is the advanced path further down.</p>
    <p className="fine">An unsent draft stays only in this browser tab and only for this saved run. It is never queued or sent automatically. A confirmed save, Discard draft or closing the tab clears it.</p>
    {draftSaved && <p className="draft-status" role="status">Unsent draft kept in this tab for run {runId}.</p>}
    {draftWarning && <p className="warning" role="alert">{draftWarning}</p>}
    <div className="intake-advanced"><p className="eyebrow">Advanced: a record as a file or as JSON</p>
    <label>Load a JSON record file<input type="file" accept=".json,application/json" disabled={busy || reading} onChange={async e=>{
      const file=e.target.files?.[0];e.target.value='';if(!file)return;
      setReading(true);setError('');
      try {const text=await readEvidenceFile(file);setJson(text);setAdvanced(true);setFileName(file.name);persistDraft({advanced:true,json:text});}
      catch(error){setError(error instanceof Error?error.message:'The file could not be read. Nothing was uploaded.');}
      finally{setReading(false);}
    }}/></label><p className="fine">One take with its independent camera_report_row, or one release record, up to 64 KiB. Choose the record type below. Loading only fills the editable preview; Save sends it to this session's selected run. No PDFs, images, CSV or footage parsing.</p>
    {reading && <p role="status">Reading the local record…</p>}
    {fileName && <p className="fine">Loaded for review: {fileName}. The preview may be edited before saving.</p>}</div>
    {guided && <div className="guide"><h3>Three editable API flows</h3><p>Load a document, inspect or edit it, then submit. The invalid date must be refused without saving; the corrected document reuses its identifier. Nothing submits automatically.</p><div className="toolbar"><button onClick={()=>exampleFlow('success')}>Try valid take</button><button onClick={()=>exampleFlow('refusal')}>Try refused date</button><button onClick={()=>exampleFlow('correction')}>Try corrected date</button></div></div>}
    <div className="toolbar"><label>Record type<select value={kind} onChange={e=>{const next=e.target.value as EvidenceKind;setKind(next);setExample(false);setError('');persistDraft({kind:next});}}><option value="take">Captured take</option><option value="rights_record">Release / licence record</option></select></label>{guided && <button onClick={fillExample}>Fill synthetic example</button>}<label className="check"><input type="checkbox" checked={advanced} onChange={e=>{setAdvanced(e.target.checked);persistDraft({advanced:e.target.checked});}}/>Advanced JSON entry</label></div>
    <form ref={formRef} onSubmit={submit} onChange={()=>persistDraft()} key={`${kind}-${example}`}>
      <fieldset disabled={busy || reading}><legend className="sr-only">{kind==='take'?'Take details':'Release details'}</legend>
      {advanced ? <label>Document JSON<textarea ref={jsonRef} required rows={10} value={json} onChange={e=>{setJson(e.target.value);persistDraft({json:e.target.value});}}/></label> : kind==='take' ? <>
        <fieldset className="intake-group"><legend>The take, as slated</legend><div className="form-grid"><label>Script beat<select name="beat_id" defaultValue={initial('beat_id',scene.beats[0].beat_id)}>{scene.beats.filter(b=>b.required).map(b=><option key={b.beat_id} value={b.beat_id}>{b.beat_id} · {b.slug}</option>)}</select></label>
        {takeFields.filter(([name])=>!name.startsWith('report_')).map(([name,label])=><label key={name}>{label}<input name={name} required type={name.includes('lens')?'number':'text'} min={name.includes('lens')?1:undefined} maxLength={128} defaultValue={initial(name)}/></label>)}</div></fieldset>
        <fieldset className="intake-group"><legend>The camera report, an independent record</legend><p className="fine">Enter the values exactly as the report states them. If they disagree with the take, that disagreement is evidence and stays visible.</p><div className="form-grid">
        {takeFields.filter(([name])=>name.startsWith('report_')).map(([name,label])=><label key={name}>{label}<input name={name} required={!missingReport} disabled={missingReport} type={name.includes('lens')?'number':'text'} min={name.includes('lens')?1:undefined} maxLength={128} defaultValue={initial(name)}/></label>)}</div>
        <label className="check"><input type="checkbox" name="camera_report_missing" checked={missingReport} onChange={e=>setMissingReport(e.target.checked)}/>No independent camera report supplied</label><p className="fine">A missing report stays missing. Take metadata is never copied into corroborating evidence.</p></fieldset>
        <div className="form-grid"><label>Visible people (comma separated)<input name="visible_people" defaultValue={initial('visible_people')}/></label><label>Visible assets (comma separated)<input name="visible_assets" defaultValue={initial('visible_assets')}/></label><label>Capture date and time (ISO)<input name="captured_at" placeholder="2026-08-19T23:04:00Z" defaultValue={initial('captured_at')}/></label></div>
        <label>Supervisor note<textarea name="note" maxLength={2000} defaultValue={initial('note')}/></label>
        <div className="toolbar"><label className="check"><input type="checkbox" name="preferred" defaultChecked={initiallyChecked('preferred',true)}/>Marked preferred in supplied record</label><label className="check"><input type="checkbox" name="usable" defaultChecked={initiallyChecked('usable',true)}/>Marked usable in supplied record</label></div>
      </> : <div className="form-grid">
        <label>Record identifier<input name="record_id" required defaultValue={initial('record_id','')}/></label>
        <label>Person or asset<select name="subject_id" defaultValue={initial('subject_id',scene.subjects[0]?.subject_id ?? '')}>{scene.subjects.map(s=><option key={s.subject_id}>{s.subject_id}</option>)}</select></label>
        <label>Subject kind<select name="subject_kind" defaultValue={initial('subject_kind','person')}><option value="person">Person</option><option value="asset">Asset</option></select></label>
        <label>Document type<input required name="document_type" defaultValue={initial('document_type','')}/></label>
        <label>Scope as recorded<input required name="scope" defaultValue={initial('scope','')}/></label>
        <label>Territory as recorded<input required name="territory" defaultValue={initial('territory','')}/></label>
        <label>Document status<select name="status" defaultValue={initial('status','pending')}><option value="pending">Pending signature</option><option value="executed">Executed</option><option value="expired">Expired</option><option value="withdrawn">Withdrawn</option></select></label>
        <label>Expiry date, if any<input name="expires_on" type="date" defaultValue={initial('expires_on','')}/></label>
      </div>}
      {error && <p role="alert" className="error">{error}</p>}
      <button className="primary" type="submit" disabled={writeBlocked}>Save evidence & rerun checks</button>
      <button type="button" onClick={e=>{try {saveJson(`${kind}-input.json`,advanced?parseEvidenceDocument(json):makeDocument(kind,new FormData(e.currentTarget.form!)));setError('');}catch{setError('Enter valid JSON before downloading this input.');}}}>Download input JSON</button>
      {draftSaved && <button type="button" onClick={()=>{clearEvidenceDraft(sessionId,runId);setDraftSaved(false);onClose();}}>Discard draft</button>}
      {writeBlocked && <p className="warning">Refresh saved state before saving more evidence. You can keep editing or close this form.</p>}
      </fieldset>
    </form>
  </section>;
}
