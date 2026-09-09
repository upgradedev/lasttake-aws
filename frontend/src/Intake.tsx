import {useState} from 'react';
import {makeDocument} from './model';
import type {Document,Scene} from './types';
const takeFields=[['take_id','Take identifier'],['slate','Slate'],['shot_id','Shot identifier'],['camera_roll','Camera roll'],['media_id','Media identifier'],['sound_roll','Sound roll'],['timecode_in','Timecode in'],['timecode_out','Timecode out'],['lens_mm','Lens (mm)'],['report_media_id','Reported media identifier'],['report_lens_mm','Reported lens (mm)'],['report_camera_roll','Reported camera roll']];
const sample:Record<string,string>={take_id:'T-900',slate:'42L/1',shot_id:'S-42-PICKUP',camera_roll:'A007',media_id:'A007R2G01',sound_roll:'SR07',timecode_in:'23:04:00:00',timecode_out:'23:04:41:00',lens_mm:'50',report_media_id:'A007R2G01',report_lens_mm:'50',report_camera_roll:'A007',visible_people:'DELPHINE',note:'Pickup on the reaction. Clean single.'};
export function Intake({scene,busy,writeBlocked=false,onSubmit,onClose,guided}:{scene:Scene;busy:boolean;writeBlocked?:boolean;onSubmit:(kind:string,document:Document)=>Promise<boolean>;onClose:()=>void;guided:boolean}) {
  const [kind,setKind]=useState<'take'|'rights_record'>('take');
  const [example,setExample]=useState(false);
  const [advanced,setAdvanced]=useState(false);
  const [json,setJson]=useState('');
  const [error,setError]=useState('');
  const [missingReport,setMissingReport]=useState(false);
  function exampleFlow(flow:'success'|'refusal'|'correction') {
    setError('');setMissingReport(false);setExample(true);
    if(flow==='success'){setKind('take');setAdvanced(false);return;}
    setKind('rights_record');setAdvanced(true);
    setJson(JSON.stringify({record_id:'REL-EDITABLE',subject_id:'BG-07',subject_kind:'person',
      document_type:'background release',scope:'all media',territory:'worldwide',status:'executed',
      expires_on:flow==='refusal'?'2026-02-30':'2030-02-28'},null,2));
  }
  async function submit(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();setError('');
    let doc:Document;
    try {doc=advanced ? JSON.parse(json) as Document : makeDocument(kind,new FormData(event.currentTarget));}
    catch {setError('Enter valid JSON. Your document has been kept.');return;}
    if(await onSubmit(kind,doc))onClose();
  }
  return <section className="panel intake" aria-labelledby="intake-title">
    <div className="section-heading"><div><p className="eyebrow">Supplied records</p><h2 id="intake-title">Add evidence to this shoot day</h2></div><button onClick={onClose} disabled={busy}>Close form</button></div>
    <p>Use fictional records only. Saving reruns the checks affected by the supplied evidence.</p>
    {guided && <div className="guide"><h3>Three editable API flows</h3><p>Load a document, inspect or edit it, then submit. The invalid date must be refused without saving; the corrected document reuses its identifier. Nothing submits automatically.</p><div className="toolbar"><button onClick={()=>exampleFlow('success')}>Try valid take</button><button onClick={()=>exampleFlow('refusal')}>Try refused date</button><button onClick={()=>exampleFlow('correction')}>Try corrected date</button></div></div>}
    <div className="toolbar"><label>Record type<select value={kind} onChange={e=>{setKind(e.target.value as typeof kind);setExample(false);setError('');}}><option value="take">Captured take</option><option value="rights_record">Release / licence record</option></select></label>{guided && <button onClick={()=>setExample(true)}>Fill synthetic example</button>}<label className="check"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>Advanced JSON entry</label></div>
    <form onSubmit={submit} key={`${kind}-${example}`}>
      <fieldset disabled={busy}><legend className="sr-only">{kind==='take'?'Take details':'Release details'}</legend>
      {advanced ? <label>Document JSON<textarea required rows={10} value={json} onChange={e=>setJson(e.target.value)}/></label> : kind==='take' ? <>
        <div className="form-grid"><label>Script beat<select name="beat_id" defaultValue={example?'B-17':scene.beats[0].beat_id}>{scene.beats.filter(b=>b.required).map(b=><option key={b.beat_id} value={b.beat_id}>{b.beat_id} · {b.slug}</option>)}</select></label>
        {takeFields.map(([name,label])=><label key={name}>{label}<input name={name} required={!missingReport || !name.startsWith('report_')} disabled={missingReport && name.startsWith('report_')} type={name.includes('lens')?'number':'text'} min={name.includes('lens')?1:undefined} maxLength={128} defaultValue={example?sample[name]:''}/></label>)}</div>
        <div className="form-grid"><label>Visible people (comma separated)<input name="visible_people" defaultValue={example?sample.visible_people:''}/></label><label>Visible assets (comma separated)<input name="visible_assets"/></label><label>Capture date and time (ISO)<input name="captured_at" placeholder="2026-08-19T23:04:00Z"/></label></div>
        <label>Supervisor note<textarea name="note" maxLength={2000} defaultValue={example?sample.note:''}/></label>
        <div className="toolbar"><label className="check"><input type="checkbox" name="preferred" defaultChecked/>Marked preferred in supplied record</label><label className="check"><input type="checkbox" name="usable" defaultChecked/>Marked usable in supplied record</label></div>
        <p className="fine">Camera report fields are a separate record. Enter the values as reported; disagreements remain evidence.</p>
        <label className="check"><input type="checkbox" name="camera_report_missing" checked={missingReport} onChange={e=>setMissingReport(e.target.checked)}/>No independent camera report supplied</label><p className="fine">A missing report stays missing. Take metadata is never copied into corroborating evidence.</p>
      </> : <div className="form-grid">
        <label>Record identifier<input name="record_id" required defaultValue={example?'REL-900':''}/></label>
        <label>Person or asset<select name="subject_id" defaultValue={example?'BG-07':scene.subjects[0]?.subject_id}>{scene.subjects.map(s=><option key={s.subject_id}>{s.subject_id}</option>)}</select></label>
        <label>Subject kind<select name="subject_kind"><option value="person">Person</option><option value="asset">Asset</option></select></label>
        <label>Document type<input required name="document_type" defaultValue={example?'background release':''}/></label>
        <label>Scope as recorded<input required name="scope" defaultValue={example?'all media':''}/></label>
        <label>Territory as recorded<input required name="territory" defaultValue={example?'worldwide':''}/></label>
        <label>Document status<select name="status" defaultValue={example?'executed':'pending'}><option value="pending">Pending signature</option><option value="executed">Executed</option><option value="expired">Expired</option><option value="withdrawn">Withdrawn</option></select></label>
        <label>Expiry date, if any<input name="expires_on" type="date"/></label>
      </div>}
      {error && <p role="alert" className="error">{error}</p>}
      <button className="primary" type="submit" disabled={writeBlocked}>Save evidence & rerun checks</button>
      {writeBlocked && <p className="warning">Refresh saved state before saving more evidence. You can keep editing or close this form.</p>}
      </fieldset>
    </form>
  </section>;
}
