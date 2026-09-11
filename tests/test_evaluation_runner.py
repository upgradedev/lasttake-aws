"""Offline supervisor controls. Fake grants and GitHub/AWS receipts have no authority."""
from copy import deepcopy
import json
import os
import signal
import socket
import subprocess
import sys
from unittest.mock import Mock

import boto3
import pytest

from tools import evaluation_runner as R

B, E = R.B, R.E
NOW = B.timestamp("2026-09-11T00:00:00Z")
ROLE = "arn:aws:iam::111111111111:role/fixture-evaluation-only"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Offline source controls cannot contact a service")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(boto3, "client", deny)
    monkeypatch.setattr(E.BedrockInterpreter, "__init__", deny)


def fixture_plan():
    p = B.plan()
    ctx = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_RUN_ID": "9001", "GITHUB_RUN_NUMBER": "41", "GITHUB_RUN_ATTEMPT": "1",
           "GITHUB_REPOSITORY": R.REPO, "GITHUB_REPOSITORY_ID": "111",
           "GITHUB_WORKFLOW_REF": R.REPO + "/.github/workflows/ci.yml@refs/heads/fixture",
           "GITHUB_SHA": p["source_sha"]}
    allocations = {}
    for app, repo in R.REPOSITORIES.items():
        allocations[app] = {"repository": repo, "source_sha": "a" * 40,
            "request_manifest_sha256": "b" * 64, "protocol_sha256": "c" * 64,
            "config_sha256": "d" * 64, "allocated_usd": "1.00" if app != "Archon" else "2.50",
            "max_calls": R.MAX_CALLS[app], "run_number": "41", "bound_reviewed": True,
            "workflow_ref": repo + "/.github/workflows/ci.yml@refs/heads/fixture", "role_arn": ROLE}
    allocations[R.APP].update({key: p[key] for key in (
        "source_sha", "request_manifest_sha256", "protocol_sha256", "config_sha256")})
    plan = {"schema": R.SCHEMA, "status": "PARENT_APPROVED", "currency": "USD",
        "fixed_slices": True, "budget_id": "a" * 32, "ceiling_usd": "5.00",
        "issued_at": "2026-09-11T00:00:00Z", "expires_at": "2026-09-11T00:30:00Z",
        "pricing_verified_at": "2026-09-11T00:00:00Z",
        "pricing_reference": "https://example.invalid/SYNTHETIC-NOT-A-GRANT",
        "rates": {"input_usd_per_million": "5.50", "output_usd_per_million": "27.50"},
        "allocations": allocations}
    return plan, p, ctx


class FakeLedger:
    def __init__(self):
        self.calls, self.refs, self.tags = [], {}, {}
        self.is_private, self.lose_ack = True, False

    def request(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if path == "":
            return {"private": self.is_private, "full_name": R.REPO, "id": 111}
        if method == "POST" and path == "/git/tags":
            sha = E.digest(E.encoded(body))[:40]
            self.tags[sha] = {"sha": sha, "message": body["message"],
                              "object": {"type": "commit", "sha": body["object"]}}
            return {"sha": sha}
        if method == "POST" and path == "/git/refs":
            if body["ref"] in self.refs:
                raise ValueError("HTTP422 already consumed")
            value = {"ref": body["ref"], "object": {"type": "tag", "sha": body["sha"]}}
            self.refs[body["ref"]] = value
            if self.lose_ack:
                raise TimeoutError("Response lost AFTER successful create")
            return deepcopy(value)
        if method == "GET" and path.startswith("/git/ref/"):
            return deepcopy(self.refs["refs/" + path.removeprefix("/git/ref/")])
        if method == "GET" and path.startswith("/git/tags/"):
            return deepcopy(self.tags[path.rsplit("/", 1)[1]])
        raise AssertionError((method, path))


def reserve(output, ledger=None, mutate=None):
    plan, p, ctx = fixture_plan()
    if mutate:
        mutate(plan, ctx)
    raw = E.encoded(plan)
    ledger = ledger or FakeLedger()
    grant = R.reserve_bundle(raw, E.digest(raw), p, ctx, NOW, ROLE, output, ledger)
    return plan, p, ctx, raw, ledger, grant


def test_complete_supervisor_to_frozen_collector_and_replay(tmp_path, monkeypatch):
    output = tmp_path / "run"
    plan, p, ctx, raw, ledger, grant = reserve(output)
    monkeypatch.setenv("GH_TOKEN", "SYNTHETIC-TOKEN-MUST-NOT-REACH-CHILD")
    counter = []
    class FakeModel:
        def converse(self, **request):
            index = len(counter)
            opinion = {"confidence": 0.2, "rationale": "Synthetic plumbing control, not model evidence"}
            opinion.update({"covers": False} if index < 10 else {"states_agree": False, "possibly_intentional": False})
            counter.append(request)
            return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {
                "name": "record_opinion", "toolUseId": str(index), "input": opinion}}]}},
                "stopReason": "tool_use", "usage": {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
                "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "FAKE", "RetryAttempts": 0}}
    def launch(command, env):
        assert "GH_TOKEN" not in env
        assert (output / "launch-consumed.json").exists()
        child_ctx = {key: env[key] for key in B.context()}
        result = B.collect(output / "cohort", (output / "grant.json").read_bytes(), child_ctx,
                           client_factory=FakeModel, clock=lambda: NOW)
        assert result["counts"] == {"COMPLETE": 16, "FAILED": 0, "UNRUN": 0}
        return 0
    assert R.run_bundle(raw, E.digest(raw), p, ctx, NOW, ROLE, output, ledger, launch) == 0
    assert len(counter) == 16 and len(ledger.refs) == 1
    assert grant["run_id"] == "9001"
    assert json.loads((output / "reservation.json").read_text())["allocated_usd"] == "1.00"
    with pytest.raises(FileExistsError):
        R.run_bundle(raw, E.digest(raw), p, ctx, NOW, ROLE, output, ledger,
                     lambda *args: pytest.fail("No second child"))


@pytest.mark.parametrize("key,value", [("status", "NOT_APPROVED"), ("fixed_slices", False),
    ("currency", "EUR"), ("budget_id", "../escape"), ("ceiling_usd", "NaN"),
    ("ceiling_usd", "5.01"), ("ceiling_usd", "4.00"),
    ("expires_at", "2026-09-11T02:00:00Z"), ("expires_at", "2026-09-10T23:00:00Z"),
    ("pricing_verified_at", "2026-09-01T00:00:00Z")])
def test_bad_portfolio_refused_before_remote_write(tmp_path, key, value):
    ledger = FakeLedger()
    with pytest.raises(ValueError):
        reserve(tmp_path / "denied", ledger, lambda plan, ctx: plan.update({key: value}))
    assert ledger.calls == []


@pytest.mark.parametrize("app,key,value", [
    ("Merismos", "allocated_usd", "4.00"), ("Archon", "allocated_usd", "NaN"),
    ("Merismos", "repository", R.REPO), ("Archon", "bound_reviewed", False),
    ("LastTake", "allocated_usd", "0.01"), ("LastTake", "source_sha", "b" * 40),
    ("LastTake", "config_sha256", "c" * 64), ("LastTake", "protocol_sha256", "d" * 64),
    ("LastTake", "request_manifest_sha256", "f" * 64), ("LastTake", "run_number", "42"),
    ("LastTake", "max_calls", 15), ("LastTake", "max_calls", True),
    ("LastTake", "role_arn", "arn:aws:iam::222222222222:role/wrong")])
def test_other_slices_count_and_candidate_cannot_change(tmp_path, app, key, value):
    ledger = FakeLedger()
    with pytest.raises(ValueError):
        reserve(tmp_path / "denied", ledger, lambda plan, ctx: plan["allocations"][app].update({key: value}))
    assert ledger.calls == []


@pytest.mark.parametrize("key,value", [("GITHUB_EVENT_NAME", "push"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("GITHUB_REPOSITORY", "somewhere/else"), ("GITHUB_RUN_ID", ""), ("GITHUB_SHA", "c" * 40)])
def test_context_denial_before_network(tmp_path, key, value):
    ledger = FakeLedger()
    with pytest.raises(ValueError):
        reserve(tmp_path / "denied", ledger, lambda plan, ctx: ctx.update({key: value}))
    assert ledger.calls == []


def test_independent_hash_role_and_private_identity_required(tmp_path):
    plan, p, ctx = fixture_plan()
    raw = E.encoded(plan)
    for digest, role in (("", ROLE), ("0" * 64, ROLE), (E.digest(raw), "")):
        with pytest.raises(ValueError): R.validate(raw, digest, p, ctx, NOW, role)
    ledger = FakeLedger()
    ledger.is_private = False
    with pytest.raises(ValueError, match="private"):
        reserve(tmp_path / "public", ledger)
    assert not any(method == "POST" for method, _, _ in ledger.calls)


def test_exported_template_is_not_an_activation_grant():
    _, p, ctx = fixture_plan()
    raw = E.encoded(R.template(p))
    assert R.template(p)["allocations"][R.APP]["source_sha"] == p["source_sha"]
    with pytest.raises(ValueError): R.validate(raw, E.digest(raw), p, ctx, NOW, ROLE)


def test_lost_create_ack_and_new_directory_do_not_reset_budget(tmp_path):
    ledger = FakeLedger()
    ledger.lose_ack = True
    with pytest.raises(TimeoutError): reserve(tmp_path / "lost", ledger)
    assert len(ledger.refs) == 1 and not (tmp_path / "lost/grant.json").exists()
    ledger.lose_ack = False
    with pytest.raises(ValueError, match="consumed"): reserve(tmp_path / "retry", ledger)
    assert len(ledger.refs) == 1


@pytest.mark.parametrize("damage", ["ref", "tag", "local_grant", "local_receipt", "raw_plan"])
def test_tampered_reservation_never_starts_child(tmp_path, damage):
    output = tmp_path / "run"
    plan, p, ctx, raw, ledger, grant = reserve(output)
    if damage == "ref": next(iter(ledger.refs.values()))["object"]["sha"] = "f" * 40
    if damage == "tag": next(iter(ledger.tags.values()))["message"] = "tampered"
    if damage == "local_grant": (output / "grant.json").write_text("{}")
    if damage == "local_receipt":
        receipt = json.loads((output / "reservation.json").read_text())
        receipt["run_id"] = "9002"
        (output / "reservation.json").write_text(json.dumps(receipt))
    if damage == "raw_plan": (output / "approved-plan.json").write_text("{}")
    launch = Mock(side_effect=AssertionError("No child allowed"))
    with pytest.raises((ValueError, KeyError)): R.run_bundle(raw, E.digest(raw), p, ctx, NOW, ROLE, output, ledger, launch)
    launch.assert_not_called()


def test_timeout_does_not_refund_or_offer_replacement(tmp_path):
    output = tmp_path / "run"
    plan, p, ctx, raw, ledger, grant = reserve(output)
    assert R.run_bundle(raw, E.digest(raw), p, ctx, NOW, ROLE, output, ledger, lambda *args: 124) == 124
    assert (output / "launch-consumed.json").exists()
    assert len(ledger.refs) == 1
    assert json.loads((output / "supervisor-result.json").read_text())["replacement_calls"] == 0


def test_real_subprocess_timeout_and_normal_exit_without_network():
    assert R.supervise([sys.executable, "-c", "raise SystemExit(7)"], dict(os.environ)) == 7
    assert R.supervise([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ), seconds=.1, grace=1) == 124


@pytest.mark.skipif(os.name == "nt", reason="CI supervisor uses Linux process groups")
def test_external_sigterm_stops_and_reaps_uncooperative_child():
    import select
    child = "import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(os.getpid(),flush=True); time.sleep(30)"
    command = [sys.executable, "-u", "-c", child]
    outer = subprocess.Popen([sys.executable, "-u", "-c",
        "import os; from tools.evaluation_runner import supervise; "
        f"raise SystemExit(supervise({command!r},dict(os.environ),seconds=20,grace=.2))"],
        cwd=E.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([outer.stdout], [], [], 10)[0], "Child did not start"
        pid = int(outer.stdout.readline().strip())
        outer.send_signal(signal.SIGTERM)
        _, error = outer.communicate(timeout=5)
        assert outer.returncode == 143, error
        with pytest.raises(ProcessLookupError): os.kill(pid, 0)
    finally:
        if outer.poll() is None:
            outer.kill()
            outer.wait(timeout=5)


@pytest.mark.parametrize("damage", ["missing_seal", "partial_seal", "changed_summary"])
def test_partial_final_is_preserved_and_replayed_without_model_calls(tmp_path, monkeypatch, damage):
    test_complete_supervisor_to_frozen_collector_and_replay(tmp_path, monkeypatch)
    output = tmp_path / "run"
    final = output / "cohort/final"
    assert R.recover(output) == final
    if damage == "missing_seal": (final / "manifest.json").unlink()
    if damage == "partial_seal": (final / "manifest.json").write_text('{"partial":')
    if damage == "changed_summary": (final / "summary.json").write_text('{"partial":')
    before = {str(path): path.read_bytes() for path in final.rglob("*") if path.is_file()}
    recovered = R.recover(output)
    assert recovered == output / "recovery/final" and R.sealed(recovered)
    assert json.loads((recovered / "summary.json").read_text())["counts"]["COMPLETE"] == 16
    assert before == {str(path): path.read_bytes() for path in final.rglob("*") if path.is_file()}
    assert R.recover(output) == recovered


def test_no_cohort_recovery_is_inert_and_partial_recovery_is_not_overwritten(tmp_path):
    assert R.recover(tmp_path) is None
    (tmp_path / "cohort/final").mkdir(parents=True)
    (tmp_path / "recovery").mkdir()
    with pytest.raises(FileExistsError): R.recover(tmp_path)


def test_ledger_has_no_update_delete_redirect_or_arbitrary_origin():
    ledger = R.GitHubLedger("FAKE")
    for method, path in (("DELETE", "/git/refs/x"), ("PATCH", "/git/refs/x"), ("GET", "https://evil.invalid")):
        with pytest.raises(ValueError): ledger.request(method, path)
    with pytest.raises(ValueError): R.NoRedirect().redirect_request(None)


def test_workflow_separates_source_credentials_and_gates_manual_job():
    workflow = (E.ROOT / ".github/workflows/ci.yml").read_text()
    job = workflow.split("  evaluation-parent:")[1].split("  hero:")[0]
    assert "github.event_name == 'workflow_dispatch'" in job
    assert "github.event.repository.private == true" in job
    assert "github.run_attempt == 1" in job
    assert "vars.LASTTAKE_EVAL_APPROVED_PLAN_SHA256 != ''" in job
    assert "persist-credentials: false" in job and "timeout-minutes: 20" in job
    assert job.index("evaluation_runner.py preflight") < job.index("evaluation_runner.py reserve") < job.index("configure-aws-credentials") < job.index("evaluation_runner.py run")
    assert "if: always()" in job and "evaluation_runner.py recover" in job
    assert "AWS_ACCESS_KEY_ID" not in job and "AWS_SECRET_ACCESS_KEY" not in job
