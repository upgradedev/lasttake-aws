import {describe,it,expect} from 'vitest';
import {aboutBeat,link,readRoute} from '../src/model';
import {beatMatches,beatsFor,count,exceptions,metrics,recentEvents,reviewLabel,selectEvidence,uniqueBy} from '../src/projection';
import {finding,scene,state,take} from './fixtures';
import type {Decision,Finding} from '../src/types';

describe('current-scene projections',()=>{
  it('rejects absent, non-finite and invalid counts while preserving observed zero',()=>{
    for(const n of [null,undefined,NaN,Infinity,-1,1.5,'0'])expect(count(n)).toBeNull();
    expect(count(0)).toBe(0);expect(count(34)).toBe(34);
    const unchecked={...state,counts:null,eligible:true};
    const result=metrics(scene,unchecked);
    for(const id of ['coverage','exceptions','releases','eligibility'])expect(result.find(m=>m.id===id)?.value).toBe('Not assessed');
    expect(exceptions(unchecked)).toEqual([]);
    expect(metrics(scene,{...state,counts:{...state.counts!,covered_with_evidence:null}})[0].value).toBe('Not assessed');
    expect(metrics({...scene,take_count:NaN},state).find(m=>m.id==='takes')?.value).toBe('Unavailable');
    expect(metrics(scene,state).find(m=>m.id==='releases')?.value).toBe('0');
  });
  it('deduplicates retained exceptions and does not subtract reviewed exceptions',()=>{
    const current={...state,exceptions:[...state.exceptions,finding]};
    expect(exceptions(current)).toHaveLength(3);
    expect(metrics(scene,current).find(m=>m.id==='exceptions')).toMatchObject({label:'Retained exceptions',value:'3'});
    expect(uniqueBy([{id:'a'},{id:'a'},{id:'b'}],r=>r.id)).toEqual([{id:'a'},{id:'b'}]);
  });
  it('keeps pending, stale, unapproved and recorded approval separate from eligibility',()=>{
    const pending={id:'w',reason:{kind:'wrap' as const,required_role:'first_ad' as const,note:'Review'}};
    const approval=(s:typeof state)=>metrics(scene,s).find(m=>m.id==='approval')!.value;
    expect(approval(state)).toBe('Not approved');
    expect(approval({...state,pending_approval:pending})).toBe('Pending 1st AD');
    expect(approval({...state,pending_approval:{...pending,evidence_changed:true}})).toBe('Needs new review');
    expect(approval({...state,wrap_approved:true})).toBe('Recorded');
    expect(metrics(scene,{...state,eligible:true}).find(m=>m.id==='eligibility')?.value).toBe('Eligible');
    expect(metrics(scene,state).find(m=>m.id==='eligibility')?.value).toBe('Blocked');
  });
  it('keeps metric drills scoped to the same run and the named record subset',()=>{
    for(const m of metrics(scene,state)){location.hash=m.href;expect(readRoute().run).toBe(state.run_id);}
    const required={...scene.beats[1],required:true};
    const assessed={...state,beats:[...state.beats,{beat_id:required.beat_id,status:'no_release_record',reason:'missing',basis:'declared'}]};
    expect(beatMatches(scene.beats[0],assessed,'covered')).toBe(true);
    expect(beatMatches(required,assessed,'covered')).toBe(false);
    expect(beatMatches(required,assessed,'missing-releases')).toBe(true);
    expect(beatMatches(scene.beats[0],assessed,'missing-releases')).toBe(false);
    expect(beatMatches({...required,required:false},assessed,'missing-releases')).toBe(false);
    expect(beatMatches(scene.beats[0],assessed,'exceptions')).toBe(true);
    expect(beatMatches(required,{...state,counts:null},'exceptions')).toBe(false);
    expect(beatMatches(required,state,'all')).toBe(true);
  });
  it('refuses null/undefined/empty requirement matches even with supplied take locators',()=>{
    for(const id of [null,undefined,'',' '])expect(aboutBeat({...finding,requirement_id:id,locators:[{kind:'take',value:take.take_id}]} as Finding,scene.beats[0])).toBe(false);
    expect(aboutBeat({...finding,requirement_id:'ref',locators:[{kind:'take',value:take.take_id}]},scene.beats[0])).toBe(true);
    expect(aboutBeat({...finding,requirement_id:'ref',locators:[{kind:'take',value:''},{kind:'field',value:take.take_id}]},scene.beats[0])).toBe(false);
  });
  it('maps each actual requirement kind bidirectionally and preserves unmatched advisories',()=>{
    for(const id of ['B-01','CR-01','T-1','MARA','MUG'])expect(beatsFor(scene,{...finding,requirement_id:id}).map(b=>b.beat_id)).toEqual(['B-01']);
    expect(beatsFor(scene,state.exceptions[2])).toEqual([]);
    const selected=selectEvidence(scene,state,{finding:'f-orphan'});
    expect(selected.finding?.finding_id).toBe('f-orphan');expect(selected.related).toEqual([]);expect(selected.invalid).toBe(false);
    expect(selectEvidence(scene,state,{beat:'B-01'}).finding?.finding_id).toBe('f-con');
    expect(selectEvidence(scene,state,{beat:'B-17'}).findings).toEqual([]);
    expect(selectEvidence(scene,state,{filter:'missing-releases'}).findings.map(f=>f.check_type)).toEqual(['rights']);
    expect(selectEvidence(scene,state,{beat:'B-01',finding:'f-con'}).invalid).toBe(false);
    expect(selectEvidence(scene,state,{beat:'B-17',finding:'f-con'}).invalid).toBe(true);
    for(const selection of [{beat:'gone'},{finding:'gone'}]){
      expect(selectEvidence(scene,state,selection).invalid).toBe(true);
      expect(selectEvidence(scene,state,selection).finding).toBeUndefined();
    }
  });
  it('marks stale decisions as needing fresh review and keeps current decisions visible',()=>{
    const d:Decision={decision_id:'d1',finding_id:finding.finding_id,action:'accept_exception',actor:'Sue',role:'script_supervisor',reason:'intent',finding_sha256:'old',at:'date'};
    expect(reviewLabel(finding,state)).toBe('Needs review');
    expect(reviewLabel(finding,{...state,decisions:[d]})).toBe('Review changed evidence');
    const decided={...state,decisions:[{...d,finding_sha256:finding.record_sha256}]};
    expect(reviewLabel(finding,decided)).toBe('Decision recorded · exception retained');
    expect(metrics(scene,decided).find(m=>m.id==='exceptions')?.value).toBe('3');
  });
  it('sorts unique events without mutating source order or inventing dates',()=>{
    const events=[{event_id:'b',event_type:'take.captured',occurred_at:'2026-09-08T01:00:00Z',payload:{}},{event_id:'c',event_type:'x',occurred_at:'2026-09-09T01:00:00Z',payload:{}},{event_id:'a',event_type:'x',occurred_at:'2026-09-09T01:00:00Z',payload:{}}];
    const original=JSON.stringify(events);
    expect(recentEvents([...events,events[0]]).map(e=>e.event_id)).toEqual(['a','c','b']);
    expect(JSON.stringify(events)).toBe(original);
  });
  it('round trips selection and escaped query context through canonical and legacy routes',()=>{
    location.hash=link('records','run one',undefined,{beat:'B-01',finding:'f/a',filter:'findings',record:'record ?&',q:'Mara & mug'});
    expect(readRoute()).toMatchObject({page:'records',run:'run one',beat:'B-01',finding:'f/a',filter:'findings',record:'record ?&',q:'Mara & mug'});
    location.hash='#dashboard';expect(readRoute().page).toBe('overview');
    location.hash='#workspace';expect(readRoute().page).toBe('scene');
    location.hash='#actions';expect(readRoute().page).toBe('actions');
  });
});
