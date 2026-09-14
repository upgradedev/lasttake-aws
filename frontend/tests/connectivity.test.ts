import {describe,expect,it,vi} from 'vitest';
import {
  clearEvidenceDraft,clearOfflineScope,prepareOfflineShell,readEvidenceDraft,readWorkspaceSnapshot,
  rebaseEvidenceDraft,writeEvidenceDraft,writeWorkspaceSnapshot,
} from '../src/connectivity';
import {scene,session,state} from './fixtures';

const snapshot=()=>({schema:'lasttake/offline-snapshot/v1' as const,session_id:session.session_id,
  run_id:state.run_id,confirmed_at:'2026-09-14T16:00:00Z',session,state,scene,events:[]});
const draft=()=>({schema:'lasttake/evidence-draft/v1' as const,session_id:session.session_id,
  run_id:state.run_id,base_revision_digest:state.package_revision_digest,kind:'take' as const,
  advanced:true,json:'{"take_id":"T-900"}',fields:{note:'Keep this'},checks:{preferred:true},updated_at:'2026-09-14T16:01:00Z'});

describe('bounded offline state',()=>{
  it('round-trips only an exact session/run snapshot and clears only that scope',()=>{
    expect(writeWorkspaceSnapshot(snapshot())).toBe(true);
    expect(readWorkspaceSnapshot(session.session_id,state.run_id)?.state.headline).toBe(state.headline);
    expect(readWorkspaceSnapshot('different-session',state.run_id)).toBeNull();
    expect(readWorkspaceSnapshot(session.session_id,'different-run')).toBeNull();
    clearOfflineScope('different-session',state.run_id);
    expect(readWorkspaceSnapshot(session.session_id,state.run_id)).not.toBeNull();
    clearOfflineScope(session.session_id,state.run_id);
    expect(readWorkspaceSnapshot(session.session_id,state.run_id)).toBeNull();
  });

  it('refuses malformed and oversized snapshots instead of treating them as current',()=>{
    sessionStorage.setItem('lasttake.offline.snapshot.v1','{"schema":"wrong"}');
    expect(readWorkspaceSnapshot(session.session_id,state.run_id)).toBeNull();
    sessionStorage.setItem('lasttake.offline.snapshot.v1','not-json');
    expect(readWorkspaceSnapshot(session.session_id,state.run_id)).toBeNull();
    expect(writeWorkspaceSnapshot({...snapshot(),confirmed_at:'not-a-time'})).toBe(false);
    expect(writeWorkspaceSnapshot({...snapshot(),events:[{event_id:'e',event_type:'x',occurred_at:'now',payload:{large:'x'.repeat(1_500_000)}}]})).toBe(false);
  });

  it('binds a draft to one session/run/revision and rebases only after explicit review',()=>{
    expect(writeEvidenceDraft(draft())).toBe(true);
    expect(readEvidenceDraft(session.session_id,state.run_id)?.fields.note).toBe('Keep this');
    expect(readEvidenceDraft('different-session',state.run_id)).toBeNull();
    expect(rebaseEvidenceDraft(session.session_id,state.run_id,'new-digest')).toBe(true);
    expect(readEvidenceDraft(session.session_id,state.run_id)?.base_revision_digest).toBe('new-digest');
    clearEvidenceDraft('different-session',state.run_id);
    expect(readEvidenceDraft(session.session_id,state.run_id)).not.toBeNull();
    clearEvidenceDraft(session.session_id,state.run_id);
    expect(readEvidenceDraft(session.session_id,state.run_id)).toBeNull();
    expect(rebaseEvidenceDraft(session.session_id,state.run_id,'unused')).toBe(false);
  });

  it('refuses malformed or oversized drafts',()=>{
    sessionStorage.setItem('lasttake.offline.evidence-draft.v1',JSON.stringify({...draft(),fields:{note:3}}));
    expect(readEvidenceDraft(session.session_id,state.run_id)).toBeNull();
    expect(writeEvidenceDraft({...draft(),json:'x'.repeat(96_000)})).toBe(false);
  });
});

describe('offline shell registration',()=>{
  it('waits for the registered worker to become ready',async()=>{
    const register=vi.fn().mockResolvedValue({});
    vi.stubGlobal('navigator',{onLine:true,serviceWorker:{register,ready:Promise.resolve({})}});
    await expect(prepareOfflineShell()).resolves.toBe(true);
    expect(register).toHaveBeenCalledWith('/sw.js',{scope:'/'});
  });

  it('fails closed when service workers are unavailable or registration fails',async()=>{
    vi.stubGlobal('navigator',{onLine:true});
    await expect(prepareOfflineShell()).resolves.toBe(false);
    vi.stubGlobal('navigator',{onLine:true,serviceWorker:{register:vi.fn().mockRejectedValue(new Error('blocked')),ready:Promise.resolve({})}});
    await expect(prepareOfflineShell()).resolves.toBe(false);
  });
});
