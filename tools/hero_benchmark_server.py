"""CI-only instrument around the existing local HTTP server, never an app API change."""
import json
import os
import socket
from importlib.metadata import version
from pathlib import Path
from http.server import HTTPServer
from unittest.mock import patch


def durable(path, data):
    temporary = path.with_suffix('.next')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def guards(evidence, path):
    def refused(counter):
        def fail(*_args, **_kwargs):
            evidence[counter] += 1
            durable(path, evidence)
            raise RuntimeError('Source benchmark outbound operation refused')
        return fail
    return [patch.object(socket.socket, 'connect', refused('blocked_outbound')),
            patch.object(socket.socket, 'connect_ex', refused('blocked_outbound')),
            patch('boto3.session.Session.client', refused('blocked_clients')),
            patch('boto3.session.Session.resource', refused('blocked_clients'))]


def main():
    if os.environ.get('CI') != 'true' or not os.environ.get('LASTTAKE_BENCHMARK_ROOT'):
        raise RuntimeError('Manual source CI only')
    root = Path(os.environ['LASTTAKE_BENCHMARK_ROOT'])
    evidence_path = root / 'guards.json'
    evidence = dict(commit=os.environ['LASTTAKE_COMMIT_SHA'], pid=os.getpid(),
                    guards_active=True, blocked_clients=0, blocked_outbound=0,
                    scripted_stream_calls=0, offline_run_builds=0,
                    run_state_store='local-files', interpreter='offline-lexical/1.0.0',
                    planner='offline-scripted/1.0.0',
                    versions={name: version(name) for name in ['strands-agents','boto3','botocore','pydantic']})
    from contextlib import ExitStack
    with ExitStack() as stack:
        for guard in guards(evidence, evidence_path):
            stack.enter_context(guard)
        from lasttake.app import local_server as server
        from lasttake.agents.orchestrator import OfflineOrchestratorModel
        from lasttake.adapters.local.interpreter import OfflineInterpreter
        from lasttake.adapters.local.infrastructure import LocalArtifactStore, LocalRunStore, LocalEventBus
        server.configure(root.parent / 'hero-benchmark-state')
        original_build = server.H.build_run
        original_stream = OfflineOrchestratorModel.stream

        def build(*args, **kwargs):
            run = original_build(*args, **kwargs)
            if (type(run.interpreter) is not OfflineInterpreter or type(run.artifacts) is not LocalArtifactStore
                    or type(run.runs) is not LocalRunStore or type(run.bus) is not LocalEventBus):
                raise RuntimeError('Unexpected runtime adapter')
            evidence['offline_run_builds'] += 1
            durable(evidence_path, evidence)
            return run

        async def stream(self, *args, **kwargs):
            if type(self) is not OfflineOrchestratorModel:
                raise RuntimeError('Unexpected planner')
            evidence['scripted_stream_calls'] += 1
            durable(evidence_path, evidence)
            async for event in original_stream(self, *args, **kwargs):
                yield event

        stack.enter_context(patch.object(server.H, 'build_run', build))
        stack.enter_context(patch.object(OfflineOrchestratorModel, 'stream', stream))
        durable(evidence_path, evidence)
        class QuietHandler(server.RequestHandler):
            def log_message(self, *_args):
                pass  # Do not retain request bodies/session handles in server logs.
        HTTPServer(('127.0.0.1',8765), QuietHandler).serve_forever()


if __name__ == '__main__':
    main()
