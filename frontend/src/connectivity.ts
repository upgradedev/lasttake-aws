import type {EventRow,RunState,Scene,Session} from './types';

const SNAPSHOT_KEY='lasttake.offline.snapshot.v1';
const DRAFT_KEY='lasttake.offline.evidence-draft.v1';
const SNAPSHOT_LIMIT=1_500_000;
const DRAFT_LIMIT=96_000;

export type Connectivity='checking'|'online'|'offline'|'uncertain';
export type EvidenceKind='take'|'rights_record';

export interface WorkspaceSnapshot {
  schema:'lasttake/offline-snapshot/v1';
  session_id:string;
  run_id:string;
  confirmed_at:string;
  session:Session;
  state:RunState;
  scene:Scene;
  events:EventRow[];
}

export interface EvidenceDraft {
  schema:'lasttake/evidence-draft/v1';
  session_id:string;
  run_id:string;
  base_revision_digest:string;
  kind:EvidenceKind;
  advanced:boolean;
  json:string;
  fields:Record<string,string>;
  checks:Record<string,boolean>;
  updated_at:string;
}

const record=(value:unknown):value is Record<string,unknown>=>!!value && typeof value==='object' && !Array.isArray(value);
const validTime=(value:unknown)=>typeof value==='string' && Number.isFinite(Date.parse(value));
const byteLength=(text:string)=>new TextEncoder().encode(text).byteLength;

function readStored(key:string,limit:number):unknown {
  try {
    const raw=sessionStorage.getItem(key);
    if(!raw || byteLength(raw)>limit)return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeStored(key:string,value:unknown,limit:number) {
  try {
    const raw=JSON.stringify(value);
    if(byteLength(raw)>limit)return false;
    sessionStorage.setItem(key,raw);
    return true;
  } catch {
    return false;
  }
}

export function readWorkspaceSnapshot(sessionId:string,runId:string):WorkspaceSnapshot|null {
  const value=readStored(SNAPSHOT_KEY,SNAPSHOT_LIMIT);
  if(!record(value) || value.schema!=='lasttake/offline-snapshot/v1' || value.session_id!==sessionId || value.run_id!==runId || !validTime(value.confirmed_at))return null;
  if(!record(value.session) || value.session.session_id!==sessionId || !record(value.state) || value.state.run_id!==runId || !record(value.scene) || !Array.isArray(value.events))return null;
  if(typeof value.state.package_revision_digest!=='string' || value.state.package_revision_digest.length<1)return null;
  return value as unknown as WorkspaceSnapshot;
}

export function writeWorkspaceSnapshot(snapshot:WorkspaceSnapshot) {
  if(snapshot.session.session_id!==snapshot.session_id || snapshot.state.run_id!==snapshot.run_id || !validTime(snapshot.confirmed_at))return false;
  return writeStored(SNAPSHOT_KEY,snapshot,SNAPSHOT_LIMIT);
}

export function clearWorkspaceSnapshot(sessionId:string,runId:string) {
  const current=readWorkspaceSnapshot(sessionId,runId);
  if(current)try {sessionStorage.removeItem(SNAPSHOT_KEY);}catch {/* The browser already refused storage. */}
}

function stringMap(value:unknown):value is Record<string,string> {
  return record(value) && Object.values(value).every(item=>typeof item==='string');
}

function booleanMap(value:unknown):value is Record<string,boolean> {
  return record(value) && Object.values(value).every(item=>typeof item==='boolean');
}

export function readEvidenceDraft(sessionId:string,runId:string):EvidenceDraft|null {
  const value=readStored(DRAFT_KEY,DRAFT_LIMIT);
  if(!record(value) || value.schema!=='lasttake/evidence-draft/v1' || value.session_id!==sessionId || value.run_id!==runId || !validTime(value.updated_at))return null;
  if(value.kind!=='take' && value.kind!=='rights_record')return null;
  if(typeof value.base_revision_digest!=='string' || typeof value.advanced!=='boolean' || typeof value.json!=='string' || !stringMap(value.fields) || !booleanMap(value.checks))return null;
  return value as unknown as EvidenceDraft;
}

export function writeEvidenceDraft(draft:EvidenceDraft) {
  if(!draft.session_id || !draft.run_id || !draft.base_revision_digest || !validTime(draft.updated_at))return false;
  return writeStored(DRAFT_KEY,draft,DRAFT_LIMIT);
}

export function rebaseEvidenceDraft(sessionId:string,runId:string,digest:string) {
  const draft=readEvidenceDraft(sessionId,runId);
  if(!draft)return false;
  return writeEvidenceDraft({...draft,base_revision_digest:digest,updated_at:new Date().toISOString()});
}

export function clearEvidenceDraft(sessionId:string,runId:string) {
  const current=readEvidenceDraft(sessionId,runId);
  if(current)try {sessionStorage.removeItem(DRAFT_KEY);}catch {/* The browser already refused storage. */}
}

export function clearOfflineScope(sessionId:string,runId:string) {
  clearWorkspaceSnapshot(sessionId,runId);
  clearEvidenceDraft(sessionId,runId);
}

export async function prepareOfflineShell() {
  if(!('serviceWorker' in navigator))return false;
  try {
    await navigator.serviceWorker.register('/sw.js',{scope:'/'});
    await navigator.serviceWorker.ready;
    return true;
  } catch {
    return false;
  }
}
