"""Guard fixtures stop before network/credential access; no benchmark samples here."""
import importlib.util
import json
import socket
from contextlib import ExitStack
from pathlib import Path

import boto3
import pytest

SPEC = importlib.util.spec_from_file_location('benchmark_server', Path(__file__).parents[1] / 'tools/hero_benchmark_server.py')
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


@pytest.mark.parametrize('operation', ['connect', 'connect_ex', 'client', 'resource'])
def test_outbound_attempts_refuse_before_network_and_keep_durable_counters(tmp_path, operation):
    evidence = {'blocked_outbound': 0, 'blocked_clients': 0}
    path = tmp_path / 'guards.json'
    with ExitStack() as stack:
        for guard in SERVER.guards(evidence, path):
            stack.enter_context(guard)
        with pytest.raises(RuntimeError, match='refused'):
            if operation in {'client', 'resource'}:
                getattr(boto3.session.Session(), operation)('s3')
            else:
                with socket.socket() as connection:
                    getattr(connection, operation)(('203.0.113.1', 443))
    assert json.loads(path.read_text()) == evidence
    assert sum(evidence.values()) == 1


def test_benchmark_server_requires_explicit_source_ci(monkeypatch):
    monkeypatch.delenv('CI', raising=False)
    with pytest.raises(RuntimeError, match='Manual source CI only'):
        SERVER.main()


def test_guarded_existing_server_reaches_real_scripted_checkpoint_without_outbound(tmp_path, monkeypatch):
    from lasttake.app import handler as handler
    from types import SimpleNamespace
    for name in ('from_environment', 'run_store_kind', 'build_agent', '_json', '_SCHEMA_READY'):
        monkeypatch.setattr(handler, name, getattr(handler, name))
    monkeypatch.setenv('CI', 'true')
    monkeypatch.setenv('LASTTAKE_BENCHMARK_ROOT', str(tmp_path))
    monkeypatch.setenv('LASTTAKE_COMMIT_SHA', 'a' * 40)

    def call(path, body=None):
        response = handler.handler({'requestContext': {'http': {'path': path, 'method': 'POST' if body is not None else 'GET'}},
                                    'body': json.dumps(body or {})}, SimpleNamespace(aws_request_id='fixture'))
        assert response['statusCode'] == 200
        return json.loads(response['body'])

    class FixtureServer:
        def __init__(self, address, request_handler):
            assert address == ('127.0.0.1', 8765)

        def serve_forever(self):
            assert call('/healthz')['commit'] == 'a' * 40
            session = call('/api/session', {})
            created = call('/api/reset', {'session_id': session['session_id']})
            state = call('/api/checkpoint', {'session_id': session['session_id'], 'run_id': created['run_id']})
            assert state['run_state_store'] == 'local-files'
            assert state['interpreter'] == 'offline-lexical/1.0.0'

    monkeypatch.setattr(SERVER, 'HTTPServer', FixtureServer)
    SERVER.main()
    evidence = json.loads((tmp_path / 'guards.json').read_text())
    assert evidence['blocked_clients'] == evidence['blocked_outbound'] == 0
    assert evidence['scripted_stream_calls'] > 0
    assert evidence['offline_run_builds'] > 0
