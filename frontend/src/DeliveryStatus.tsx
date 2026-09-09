import type {Document,Role,RunState} from './types';

export function DeliveryStatus({state,role,busy,act}:{state:RunState;role:Role;busy:boolean;act:(path:string,extra?:Document)=>Promise<boolean>}) {
  const outcomes=(state.delivery_outcomes ?? []).filter(row=>row.retry_supported || row.status!=='accepted');
  return <section className="panel"><h2>Delivery status</h2><p>Bus acceptance records an API response, not matched-target delivery or completion. An event in storage is an attempted publication, not an acceptance receipt.</p>
    {outcomes.length ? <ul className="action-list">{outcomes.map(row=><li key={row.idempotency_key}><strong>{row.event_type}: {row.status==='accepted'?'Bus accepted':row.status}</strong><p>{row.detail}</p><code>{row.reference}</code>
      {row.status==='rejected' && row.retry_supported ? <><p>The bus definitely rejected this attempt. An explicit retry rechecks the current approval.</p><button disabled={busy || role!=='first_ad'} onClick={()=>void act('retry-delivery',{idempotency_key:row.idempotency_key,role})}>Retry rejected delivery</button>{role!=='first_ad' && <p className="fine">Select the 1st AD demo role to retry.</p>}</> : row.status==='pending' || row.status==='unknown' ? <p className="warning">Do not resend. Refresh saved state, then give the run and receipt identifiers to the operator to reconcile the external outcome. No success is established.</p> : null}
    </li>)}</ul> : <p>No consequential delivery or failed notification is recorded for this run.</p>}
  </section>;
}
