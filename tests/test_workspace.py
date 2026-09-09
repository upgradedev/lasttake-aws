"""Owned navigation, exact evidence review and portable receipt contracts."""
import json

import pytest

from .test_handler import offline_backends, post, RUN, A_TAKE
from lasttake.app import handler as H, workspace as W


def owned():
    session = post('/api/session', {})
    assert session['status'] == 200
    handle = session['session_id']
    run = post('/api/reset', {'session_id': handle})
    return {'run_id': run['run_id'], 'session_id': handle}


def test_owned_run_index_survives_reload_and_rejects_another_visitor():
    body = owned()
    checkpoint = post('/api/checkpoint', body)
    assert checkpoint['pending_approval']
    reloaded = post('/api/state', body)
    assert reloaded['pending_approval']['id'] == checkpoint['pending_approval']['id']
    assert not reloaded['pending_approval']['evidence_changed']
    saved = post('/api/session', {'session_id': body['session_id']})
    assert saved['runs'][0]['checked'] is True
    other = owned()
    for path in ('state', 'scene', 'events', 'ingest', 'approve', 'receipt', 'turnover'):
        assert post('/api/'+path, {'run_id': body['run_id']})['status'] == 403
        assert post('/api/'+path, {**body, 'session_id': other['session_id']})['status'] == 403
    assert post('/api/state', {**body, 'run_id': RUN})['status'] == 403
    assert len(post('/api/session', {'session_id': other['session_id']})['runs']) == 1


def test_legacy_and_owned_runs_have_distinct_access_contracts():
    assert post('/api/state', {'run_id': RUN})['status'] == 200
    assert post('/api/session', {'session_id': 'a'*64})['status'] == 403
    assert post('/api/session', {'session_id': '../invalid'})['status'] == 400
    assert post('/api/reset', {'session_id': 'a'*64})['status'] == 403
    event = {'requestContext': {'http': {'path':'/api/state', 'method':'POST'}}, 'body':'[]'}
    assert H.handler(event, None)['statusCode'] == 400


def test_owned_decisions_require_the_digest_that_the_human_saw():
    body=owned()
    state=post('/api/checkpoint',body)
    finding=next(f for f in state['exceptions'] if f['requirement_id']=='CR-01')
    decision={**body,'finding_id':finding['finding_id'],'action':'accept_exception',
              'role':'script_supervisor','actor':'Demo supervisor','reason':'Intentional match.'}
    assert post('/api/decide',decision)['status']==400
    assert post('/api/decide',{**decision,'finding_sha256':'wrong'})['status']==409
    decision['finding_sha256']=finding['record_sha256']
    assert post('/api/decide',decision)['status']==200
    assert post('/api/ingest',{**body,'kind':'take','document':A_TAKE})['status']==200
    assert post('/api/decide',decision)['status']==409
    assert post('/api/state',body)['pending_approval']['evidence_changed'] is True


def test_owned_approval_role_and_type_and_retry():
    body=owned()
    pending=post('/api/checkpoint',body)['pending_approval']
    answer={**body,'interrupt_id':pending['id'],'approve':True}
    assert post('/api/approve',answer)['status']==403
    assert post('/api/approve',{**answer,'role':'first_ad','approve':'yes'})['status']==400
    assert post('/api/approve',{**answer,'role':'first_ad'})['status']==200
    assert post('/api/state',body)['pending_approval'] is None
    post('/api/approve',{**answer,'role':'first_ad'})
    rows=post('/api/events',body)['events']
    assert sum(r['event_type']=='pickup.requested' for r in rows)==1


@pytest.mark.parametrize('subject', ['caller text', {'assertion':'approved'},
    {'beat_id':'does-not-exist'},{'beat_id':[]}, {'beat_id':'B-17','approved':True}])
def test_lt03_r1_unchecked_caller_subject_is_rejected(subject):
    post('/api/checkpoint',{'run_id':RUN})
    result=post('/api/receipt',{'run_id':RUN,'subject':subject})
    assert result['status']==400
    assert 'receipt' not in result


def test_receipt_allows_only_existing_beat_and_never_infers_approval():
    post('/api/checkpoint',{'run_id':RUN})
    result=post('/api/receipt',{'run_id':RUN,'subject':{'beat_id':'B-17'}})
    assert result['receipt']['subject']=={'beat_id':'B-17'}
    assert result['receipt']['approved_by'] is None
    assert post('/api/receipt',{'run_id':RUN,'subject':{}})['status']==200


def test_stale_pending_wrap_rejected_and_decline_is_available():
    body=owned()
    post('/api/checkpoint',body)
    run=H.build_run(body['run_id'])
    W.remember_pending(run,{'id':'example-interrupt','reason':{'kind':'wrap'}})
    assert W.guard_action('/api/wrap',{'approve':True,'role':'first_ad'},run,True)[0]==409
    post('/api/ingest',{**body,'kind':'take','document':A_TAKE})
    changed=H.build_run(body['run_id'])
    assert W.guard_action('/api/wrap',{'approve':True,'role':'first_ad'},changed,True)[0]==409
    assert W.guard_action('/api/wrap',{'approve':False,'role':'first_ad'},changed,True) is None
    run.audit('wrap.approved',{'package_revision_digest':run.package.revision_digest()})
    assert run.wrap_approved()
    assert not changed.wrap_approved()


def test_saved_turnover_retry_returns_the_original_bytes(offline_backends):
    _,artifacts,_=offline_backends
    artifacts.put(f'turnover/{RUN}.json',json.dumps({'package_revision_digest':'original','record_sha256':'seal'}).encode())
    first=post('/api/turnover',{'run_id':RUN})
    again=post('/api/turnover',{'run_id':RUN})
    assert first['turnover']==again['turnover']
    assert 'already saved' in again['message']
