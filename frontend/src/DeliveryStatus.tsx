import {words} from './model';
import type {Delivery,Document,Role,RunState} from './types';

// Row titles say what was sent and what the bus answered, in plain words. The
// raw event type, the recorded response and the reference stay one click away
// in each row, for whoever reconciles an attempt with the operator.
const eventNames=new Map([['pickup.requested','Pickup request'],['wrap.ready','Wrap ready'],['finding.recorded','Finding notification']]);
const statusWords=new Map([['accepted','accepted by the event bus'],['rejected','rejected by the event bus'],['pending','no response recorded yet'],['unknown','outcome unknown']]);

function rowTitle(row:Delivery) {
  const plain=words(row.event_type.replaceAll('.',' '));
  const name=eventNames.get(row.event_type) ?? plain.charAt(0).toUpperCase()+plain.slice(1);
  return `${name}: ${statusWords.get(row.status) ?? `status ${words(row.status)}`}`;
}

export function DeliveryStatus({state,role,busy,act}:{state:RunState;role:Role;busy:boolean;act:(path:string,extra?:Document)=>Promise<boolean>}) {
  const outcomes=(state.delivery_outcomes ?? []).filter(row=>row.retry_supported || row.status!=='accepted');
  const caveat=<p>Bus acceptance records an API response, not matched-target delivery or completion. An event in storage is an attempted publication, not an acceptance receipt.</p>;
  if(!outcomes.length)return <section className="panel"><h2>Delivery status</h2>{caveat}<p>No consequential delivery or failed notification is recorded for this run.</p></section>;
  // Open while any attempt still needs someone. A list of accepted attempts
  // waits behind its title.
  const needsAttention=outcomes.some(row=>row.status!=='accepted');
  return <details className="panel delivery-status" open={needsAttention}><summary>Delivery status</summary>{caveat}
    <ul className="action-list">{outcomes.map(row=><li key={row.idempotency_key}><strong>{rowTitle(row)}</strong>
      {row.status==='rejected' && row.retry_supported ? <><p>The bus definitely rejected this attempt. An explicit retry rechecks the current approval.</p><button disabled={busy || role!=='first_ad'} onClick={()=>void act('retry-delivery',{idempotency_key:row.idempotency_key,role})}>Retry rejected delivery</button>{role!=='first_ad' && <p className="fine">Select the 1st AD demo role to retry.</p>}</> : row.status==='pending' || row.status==='unknown' ? <p className="warning">Do not resend. Refresh saved state, then give the run and receipt identifiers to the operator to reconcile the external outcome. No success is established.</p> : null}
      <details><summary>Event type and reference</summary><dl className="metadata"><dt>Event type</dt><dd><code>{row.event_type}</code></dd><dt>Recorded response</dt><dd>{row.detail}</dd><dt>Reference</dt><dd><code>{row.reference}</code></dd></dl></details>
    </li>)}</ul>
  </details>;
}
