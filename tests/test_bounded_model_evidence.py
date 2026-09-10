"""Offline fake SDK only. Costs/receipts in these fixtures are NOT real measurements."""
import base64
from decimal import Decimal
import json
import socket

import boto3
from botocore.exceptions import ClientError
import pytest

from tools import bounded_model_evidence as B
from tools import model_evidence as E

NOW = 1789084800  # 2026-09-11T00:00:00Z, fixture clock only.


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline controls must never contact AWS or construct a model")
    monkeypatch.setattr(boto3, "client", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(E.BedrockInterpreter, "__init__", fail)


def authorized(p=None):
    p = p or B.plan()
    ctx = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "fixture/private-runner",
           "GITHUB_WORKFLOW_REF": "fixture/private-runner/.github/workflows/once.yml@refs/heads/main",
           "LASTTAKE_EVAL_PRIVATE_RUNNER": "true"}
    g = {"schema": "lasttake/bounded-converse-grant/v1", "status": "PARENT_AUTHORIZED",
         "source_sha": p["source_sha"], "instrument_sha256": B.INSTRUMENT_HASH,
         "protocol_sha256": E.PROTOCOL_HASH, "model_id": "eu.anthropic.claude-opus-5", "region": "eu-west-1",
         "config_sha256": p["config_sha256"], "request_manifest_sha256": p["request_manifest_sha256"],
         "call_limit": 16, "run_attempt": 1, "currency": "USD", "run_id": "12345",
         "repository": ctx["GITHUB_REPOSITORY"], "workflow_ref": ctx["GITHUB_WORKFLOW_REF"],
         "token_bound_assumption": "ascii-serialized-request-bytes-plus-4096-template-tokens/v1",
         "token_bound_reviewed": True, "grant_id": "a" * 32, "reservation_receipt_sha256": "b" * 64,
         "issued_at": "2026-09-11T00:00:00Z", "expires_at": "2026-09-11T00:30:00Z",
         "pricing_reference": "https://example.invalid/FAKE-FIXTURE-NOT-A-GRANT",
         "pricing_verified_at": "2026-09-11T00:00:00Z", "allocated_usd": "5.00",
         "rates": {"input_usd_per_million": "5.50", "output_usd_per_million": "27.50"}}
    return g, ctx


def grant_bytes(g, ctx):
    raw = E.encoded(g)
    ctx["LASTTAKE_EVAL_GRANT_SHA256"] = E.digest(raw)
    return raw


def response(index):
    value = {"confidence": 0.2, "rationale": "FAKE SDK fixture only, not model output."}
    value.update({"covers": False} if index < 10 else {"states_agree": False, "possibly_intentional": False})
    return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {
        "toolUseId": f"fake-{index}", "name": "record_opinion", "input": value}}]}},
        "stopReason": "tool_use", "usage": {"inputTokens": 123, "outputTokens": 47, "totalTokens": 170},
        "ResponseMetadata": {"RequestId": f"fake-request-{index}", "HTTPStatusCode": 200, "RetryAttempts": 0}}


class FakeClient:
    def __init__(self, output, mutate=None, stop=None):
        self.output, self.mutate, self.stop, self.calls = output, mutate, stop, []

    def converse(self, **request):
        index = len(self.calls)
        assert len(json.loads((self.output / "slots.json").read_text())) == 16
        reservation = json.loads((self.output / f"{index:02d}-reserved.json").read_text())
        assert reservation["request"] == request
        assert reservation["request_sha256"] == E.digest(B.ascii_request(request))
        assert Decimal(reservation["reserved_usd"]) > 0
        assert (self.output / "grant-original.bin").exists()
        self.calls.append(request)
        if self.stop is not None and index == 1:
            raise self.stop
        result = response(index)
        if self.mutate and index == 0:
            self.mutate(result)
        return result


def run_fake(tmp_path, **kwargs):
    output = tmp_path / "cohort"
    fake = FakeClient(output, **kwargs)
    g, ctx = authorized()
    result = B.collect(output, grant_bytes(g, ctx), ctx, lambda: fake, lambda: NOW)
    return output, fake, result


def hashes(output):
    raw = (output / "manifest.json").read_bytes()
    for path, digest in json.loads(raw)["files"].items():
        assert E.digest((output / path).read_bytes()) == digest
    return raw


def test_export_exact_frozen_prompts_schema_sizes_and_reference_not_grant(tmp_path):
    p = B.export(tmp_path / "export")
    assert p["config"]["max_output_tokens"] == 512
    assert p["config"]["sdk_total_max_attempts"] == 1
    assert p["scope"] == "EVALUATION_ONLY_DIRECT_CONVERSE_NOT_PRODUCTION_STRANDS"
    _, cases, _ = E.frozen_inputs()
    assert [r["case_id"] for r in p["cases"]] == ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "N01", "N02", "N03", "N04", "N05", "N06"]
    for row, case in zip(p["cases"], cases, strict=True):
        old, request = E.request_for(case), row["request"]
        assert request["system"] == [{"text": old["system_prompt"]}]
        assert request["messages"] == [{"role": "user", "content": [{"text": old["user_prompt"]}]}]
        assert request["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"] == {"json": old["output_schema"]}
        assert request["modelId"] == "eu.anthropic.claude-opus-5"
        assert request["inferenceConfig"] == {"maxTokens": 512}
        assert request["additionalModelRequestFields"] == {"thinking": {"type": "disabled"}}
        assert row["serialized_request_bytes"] == len(B.ascii_request(request)) <= 16384
        assert row["input_tokens_reserved"] == len(B.ascii_request(request)) + 4096
        assert row["frozen_request_sha256"] == E.digest(E.encoded(old))
        for excluded in ("gold", "labels", "POSITIVE", "NEGATIVE", "ABSTAIN", row["case_id"]):
            assert excluded not in B.ascii_request(request).decode()
    cost = json.loads((tmp_path / "export/cost-plan-NOT-A-GRANT.json").read_text())
    assert cost["status"] == "NOT_AUTHORIZED_REFERENCE_ONLY" and cost["actual_model_cost"] == "UNKNOWN"
    assert cost["allocated_usd"] == "UNKNOWN"
    assert Decimal(cost["reference_worst_usd"]) < Decimal("5")
    hashes(tmp_path / "export")


def test_full_offline_flow_retains_16_requests_raw_receipts_and_frozen_replay(tmp_path, capsys):
    output, fake, result = run_fake(tmp_path)
    assert len(fake.calls) == 16
    assert result["counts"] == {"COMPLETE": 16, "FAILED": 0, "UNRUN": 0}
    assert result["actual_model_cost_usd"] == "0.031504"
    assert Decimal(result["reserved_usd_never_refunded"]) > Decimal(result["actual_model_cost_usd"])
    assert result["metrics"]["declared-bedrock-replay-unverified"]["correct_abstention"] == {"numerator": 5, "denominator": 5, "rate": 1.0}
    assert result["response_body_bytes"] == "UNKNOWN"
    for i in range(16):
        assert json.loads((output / f"final/captured/{i:02d}-raw.json").read_text()) == response(i)
        assert result["slots"][i]["aws_request_id"] == f"fake-request-{i}"
    recorded = capsys.readouterr().out.splitlines()
    line = next(line for line in recorded if line.startswith("LASTTAKE_JOURNAL_BASE64 00-raw.json "))
    assert base64.b64decode(line.split(" ", 2)[2]) == (output / "00-raw.json").read_bytes()
    before = hashes(output / "final")
    (output / "00-raw.json").write_text("producer changed after sealed copy")
    assert hashes(output / "final") == before
    with pytest.raises(FileExistsError): B.finalize(output)
    g, ctx = authorized()
    with pytest.raises(FileExistsError):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: pytest.fail("no reused call"), lambda: NOW)


@pytest.mark.parametrize("key,value", [
    ("source_sha", "0" * 40), ("model_id", "other-model"), ("region", "us-east-1"),
    ("protocol_sha256", "0" * 64), ("instrument_sha256", "0" * 64),
    ("config_sha256", "0" * 64), ("request_manifest_sha256", "0" * 64),
    ("run_attempt", 2), ("run_attempt", True), ("run_id", "other-run"),
    ("repository", "other/repo"), ("workflow_ref", "other-workflow"),
    ("call_limit", 17), ("status", "NOT_AUTHORIZED"), ("currency", "EUR"),
    ("token_bound_reviewed", False), ("token_bound_assumption", "unreviewed"),
    ("grant_id", ""), ("reservation_receipt_sha256", ""), ("allocated_usd", "0.00001"),
    ("allocated_usd", "5.01"), ("expires_at", "2026-09-10T23:59:59Z"),
    ("issued_at", "2026-09-11T00:01:00Z"), ("expires_at", "2026-09-11T02:00:00Z"),
    ("pricing_verified_at", "2026-09-01T00:00:00Z"), ("pricing_reference", "UNKNOWN"),
])
def test_wrong_binding_or_budget_denies_before_sdk_or_output(tmp_path, key, value):
    g, ctx = authorized(); g[key] = value
    output = tmp_path / "no-call"
    with pytest.raises(ValueError):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: pytest.fail("SDK must not be initialized"), lambda: NOW)
    assert not output.exists()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "1e-3", "5.50000000001", 5.5, True])
def test_rate_validation_exact_finite_decimal_not_float(tmp_path, value):
    g, ctx = authorized(); g["rates"]["input_usd_per_million"] = value
    with pytest.raises(ValueError):
        B.collect(tmp_path / "no-call", grant_bytes(g, ctx), ctx, lambda: pytest.fail("no SDK"), lambda: NOW)


@pytest.mark.parametrize("key,value", [("GITHUB_EVENT_NAME", "push"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("LASTTAKE_EVAL_PRIVATE_RUNNER", "false"), ("GITHUB_ACTIONS", "false"), ("GITHUB_RUN_ID", "")])
def test_manual_private_first_attempt_only(tmp_path, key, value):
    g, ctx = authorized(); ctx[key] = value
    with pytest.raises(ValueError):
        B.collect(tmp_path / "no-call", grant_bytes(g, ctx), ctx, lambda: pytest.fail("no SDK"), lambda: NOW)


def test_grant_hash_is_independent_and_no_cli_default_activation(tmp_path):
    g, ctx = authorized(); raw = grant_bytes(g, ctx); ctx["LASTTAKE_EVAL_GRANT_SHA256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        B.collect(tmp_path / "no-call", raw, ctx, lambda: pytest.fail("no SDK"), lambda: NOW)
    with pytest.raises(SystemExit): B.main(["collect", "--output", str(tmp_path / "no-call")])


@pytest.mark.parametrize("stop", [KeyboardInterrupt(), TimeoutError("fake timeout"),
    ClientError({"Error": {"Code": "ThrottlingException", "Message": "FAKE"}}, "Converse")])
def test_interruption_reservation_raw_first_and_all_unrun_slots_retained(tmp_path, stop):
    output = tmp_path / "cohort"; fake = FakeClient(output, stop=stop); g, ctx = authorized()
    with pytest.raises(type(stop)):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: fake, lambda: NOW)
    result = json.loads((output / "final/summary.json").read_text())
    assert len(fake.calls) == 2
    assert result["counts"] == {"COMPLETE": 1, "FAILED": 1, "UNRUN": 14}
    assert result["actual_model_cost_usd"] == "UNKNOWN"
    assert Decimal(result["reserved_usd_never_refunded"]) == sum(Decimal(json.loads((output / f"{i:02d}-reserved.json").read_text())["reserved_usd"]) for i in range(2))
    assert (output / "final/captured/00-raw.json").exists()
    if isinstance(stop, ClientError): assert (output / "final/captured/01-sdk-error.json").exists()
    hashes(output / "final")


@pytest.mark.parametrize("problem", ["missing_usage", "over_input", "over_output", "retry", "cache"])
def test_unknown_or_out_of_bound_usage_stops_without_next_call(tmp_path, problem):
    def bad(result):
        if problem == "missing_usage": result.pop("usage")
        elif problem == "over_input": result["usage"]["inputTokens"] = 999999
        elif problem == "over_output": result["usage"]["outputTokens"] = 513
        elif problem == "retry": result["ResponseMetadata"]["RetryAttempts"] = 1
        else: result["usage"]["cacheReadInputTokens"] = 5
    output = tmp_path / "cohort"; fake = FakeClient(output, mutate=bad); g, ctx = authorized()
    with pytest.raises((KeyError, ValueError)):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: fake, lambda: NOW)
    assert len(fake.calls) == 1
    assert json.loads((output / "final/summary.json").read_text())["counts"] == {"COMPLETE": 0, "FAILED": 1, "UNRUN": 15}
    assert (output / "final/captured/00-raw.json").exists()
    hashes(output / "final")


@pytest.mark.parametrize("problem", ["malformed", "extra_authority", "certainty", "wrong_tool", "truncated"])
def test_bad_semantics_keeps_raw_and_failed_not_abstain_no_repair(tmp_path, problem):
    def bad(result):
        tool = result["output"]["message"]["content"][0]["toolUse"]
        if problem == "malformed": tool["input"] = "not a bounded JSON opinion"
        elif problem == "extra_authority": tool["input"]["approve_wrap"] = True
        elif problem == "certainty": tool["input"]["confidence"] = 1.0
        elif problem == "wrong_tool": tool["name"] = "approve_wrap"
        else: result["stopReason"] = "max_tokens"
    output, fake, result = run_fake(tmp_path, mutate=bad)
    assert len(fake.calls) == 16
    assert result["counts"] == {"COMPLETE": 15, "FAILED": 1, "UNRUN": 0}
    assert json.loads((output / "final/evaluation/slots/16.json").read_text())["label"] is None
    hashes(output / "final")


@pytest.mark.parametrize("problem", ["missing", "malformed"])
def test_hard_kill_snapshot_retains_available_raw_on_denominator_refusal(tmp_path, monkeypatch, problem):
    output = tmp_path / "cohort"; g, ctx = authorized(); fake = FakeClient(output, stop=KeyboardInterrupt())
    original = B.finalize
    monkeypatch.setattr(B, "finalize", lambda _: None)  # Simulate killed process before finally.
    with pytest.raises(KeyboardInterrupt):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: fake, lambda: NOW)
    raw = (output / "00-raw.json").read_bytes()
    if problem == "missing": (output / "slots.json").unlink()
    else: (output / "slots.json").write_text('{"incomplete":')
    with pytest.raises((FileNotFoundError, ValueError)): original(output)
    assert (output / "final/captured/00-raw.json").read_bytes() == raw
    assert json.loads((output / "final/error.json").read_text())["successful_summary"] is False
    assert not (output / "final/summary.json").exists()
    before = hashes(output / "final")
    (output / "00-raw.json").write_text("later writer")
    assert hashes(output / "final") == before


def test_sdk_factory_has_one_attempt_finite_timeouts_and_no_endpoint_override(monkeypatch):
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *a, **k: calls.append((a, k)) or "fake-client")
    assert B.sdk_client() == "fake-client"
    args, kwargs = calls[0]
    assert args == ("bedrock-runtime",) and kwargs["region_name"] == "eu-west-1"
    cfg = kwargs["config"]
    assert cfg.retries == {"mode": "standard", "total_max_attempts": 1}
    assert cfg.connect_timeout == 5 and cfg.read_timeout == 30
    assert cfg.ignore_configured_endpoint_urls is True


def test_existing_sdk_accepts_exact_exported_converse_request_shape_offline():
    from botocore.session import Session
    from botocore.validate import validate_parameters
    shape = Session().get_service_model("bedrock-runtime").operation_model("Converse").input_shape
    for row in B.plan()["cases"]:
        validate_parameters(row["request"], shape)


def test_response_is_durable_before_any_usage_or_semantic_parse(tmp_path, monkeypatch):
    output = tmp_path / "cohort"; original = B.check_usage
    def check(response, row, rates):
        index = [r["case_id"] for r in B.plan()["cases"]].index(row["case_id"])
        assert json.loads((output / f"{index:02d}-raw.json").read_text()) == response
        return original(response, row, rates)
    monkeypatch.setattr(B, "check_usage", check)
    _, fake, result = run_fake(tmp_path)
    assert len(fake.calls) == 16 and result["counts"]["COMPLETE"] == 16


@pytest.mark.parametrize("boundary", ["expiry", "process"])
def test_finite_boundary_stops_with_remaining_slots_unrun(tmp_path, monkeypatch, boundary):
    output = tmp_path / "cohort"; fake = FakeClient(output); g, ctx = authorized()
    times = iter([NOW, NOW, NOW + 1800])
    monotonic = iter([0, 0, 901])
    if boundary == "process": monkeypatch.setattr(B.time, "monotonic", lambda: next(monotonic))
    clock = (lambda: next(times)) if boundary == "expiry" else (lambda: NOW)
    with pytest.raises(TimeoutError):
        B.collect(output, grant_bytes(g, ctx), ctx, lambda: fake, clock)
    assert len(fake.calls) == 1
    assert json.loads((output / "final/summary.json").read_text())["counts"] == {"COMPLETE": 1, "FAILED": 0, "UNRUN": 15}
    hashes(output / "final")


def test_raw_nonfinite_response_is_preserved_even_when_strict_replay_refuses(tmp_path):
    def bad(result):
        result["output"]["message"]["content"][0]["toolUse"]["input"]["confidence"] = float("nan")
    output, fake, result = run_fake(tmp_path, mutate=bad)
    assert b"NaN" in (output / "final/captured/00-raw.json").read_bytes()
    assert len(fake.calls) == 16 and result["counts"]["FAILED"] == 1
    assert result["actual_model_cost_usd"] == "UNKNOWN"
    hashes(output / "final")


def test_request_ceiling_and_frozen_evaluator_are_fail_closed(monkeypatch):
    monkeypatch.setattr(B, "MAX_REQUEST_BYTES", 10)
    with pytest.raises(ValueError, match="ceiling"): B.plan()
    monkeypatch.setattr(B, "MAX_REQUEST_BYTES", 16384)
    monkeypatch.setattr(B, "INSTRUMENT_HASH", "0" * 64)
    with pytest.raises(ValueError, match="Frozen evaluator"): B.plan()


def test_ci_only_exports_no_paid_job_or_credentials():
    workflow = (E.ROOT / ".github/workflows/ci.yml").read_text()
    assert "python tools/bounded_model_evidence.py export" in workflow
    assert "bounded_model_evidence.py collect" not in workflow
    assert "configure-aws-credentials" not in workflow
    assert "LASTTAKE_EVAL_GRANT_SHA256" not in workflow
