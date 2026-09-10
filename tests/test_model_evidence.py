"""Credential-free instrument tests, not model performance measurements."""
import copy
import json
from pathlib import Path
import socket

import boto3
import pytest

from tools import model_evidence as E


@pytest.fixture(autouse=True)
def forbid_network_and_models(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Source instrument must not contact a model or network")
    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(E.BedrockInterpreter, "__init__", forbidden)


def fixtures():
    # Independent expected literals, not read from gold or computed by the adapter.
    expected = ["POSITIVE", "POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE",
                "ABSTAIN", "ABSTAIN", "ABSTAIN", "NEGATIVE", "NEGATIVE",
                "POSITIVE", "NEGATIVE", "NEGATIVE", "ABSTAIN", "ABSTAIN", "NEGATIVE"]
    _, cases, _ = E.frozen_inputs()
    attempts = []
    for case, label in zip(cases, expected, strict=True):
        opinion = {"confidence": 0.2 if label == "ABSTAIN" else 0.9, "rationale": "Synthetic instrument fixture, not a model response."}
        opinion.update({"covers": label == "POSITIVE"} if case["kind"] == "coverage" else
                       {"states_agree": label == "POSITIVE", "possibly_intentional": False})
        attempts.append({"case_id": case["id"], "request_sha256": E.digest(E.encoded(E.request_for(case))),
                         "response": json.dumps(opinion)})
    return {"mode": "fixture-replay-not-a-model", "protocol_sha256": E.PROTOCOL_HASH, "attempts": attempts}


def write_bundle(tmp_path, bundle):
    path = tmp_path / "replay.json"
    path.write_bytes(E.encoded(bundle))
    return path


def assert_hashes(output):
    manifest = json.loads((output / "manifest.json").read_text())
    for path, expected in manifest["files"].items():
        assert E.digest((output / path).read_bytes()) == expected
    return (output / "manifest.json").read_bytes()


def test_preregistered_inputs_are_frozen_before_instrument_and_gold_is_not_prompt():
    protocol, cases, gold = E.frozen_inputs()
    assert protocol["baseline_source"] == "fbb901caf41e624d4b200f6062794d101738236c"
    assert len(cases) == 16 and len(gold) == 16
    assert list(gold.values()).count("POSITIVE") == 4
    assert list(gold.values()).count("NEGATIVE") == 7
    assert list(gold.values()).count("ABSTAIN") == 5
    assert E.MIN_MATCH_CONFIDENCE == 0.55 and E.MIN_CONFLICT_CONFIDENCE == 0.6
    for case in cases:
        request = E.request_for(case)
        text = E.encoded(request).decode()
        assert request["inputs"] == case["inputs"]
        assert request["input_sha256"] == E.digest(E.encoded(case["inputs"]))
        for secret in (case["id"], "labels", "gold", "POSITIVE", "NEGATIVE", "ABSTAIN"):
            assert secret not in text
        assert "<evidence>" in request["user_prompt"]
        assert "production document" in request["system_prompt"]


def test_offline_baseline_is_measured_without_claiming_model_results(tmp_path):
    output = tmp_path / "evidence"
    summary = E.evaluate(output)
    baseline = summary["metrics"][E.BASELINE]
    assert baseline["counts"] == {"COMPLETE": 16, "FAILED": 0, "UNRUN": 0}
    assert baseline["false_positive"]["numerator"] > 0  # Do not hide lexical limitations.
    model = summary["metrics"]["declared-bedrock-replay-unverified"]
    assert model["counts"] == {"COMPLETE": 0, "FAILED": 0, "UNRUN": 16}
    assert model["capture"] == {"numerator": 0, "denominator": 11, "rate": None}
    assert summary["real_model_measurement"] == "NOT_RUN"
    identity = json.loads((output / "identity.json").read_text())
    assert identity["model_calls_this_offline_process"] == 0
    for key in ("original_replay_model_config", "original_replay_usage", "original_replay_model_cost", "runner_infrastructure_cost"):
        assert identity[key] == "UNKNOWN"
    assert len(list((output / "slots").glob("*.json"))) == 32
    assert len(list((output / "raw").glob("*.bin"))) == 16
    assert_hashes(output)
    with pytest.raises(FileExistsError):
        E.evaluate(output)


def test_fake_complete_cohort_checks_metric_arithmetic_not_real_model_quality(tmp_path):
    path = write_bundle(tmp_path, fixtures())
    output = tmp_path / "evidence"
    summary = E.evaluate(output, path)
    measured = summary["metrics"]["fixture-replay-not-a-model"]
    assert measured["capture"] == {"numerator": 11, "denominator": 11, "rate": 1.0}
    assert measured["false_positive"] == {"numerator": 0, "denominator": 12, "rate": 0.0}
    assert measured["correct_abstention"] == {"numerator": 5, "denominator": 5, "rate": 1.0}
    assert measured["decision_coverage"] == {"numerator": 11, "denominator": 16, "rate": 11 / 16}
    assert (output / "raw/original-replay.bin").read_bytes() == path.read_bytes()
    before = assert_hashes(output)
    path.write_text("producer changed after capture")
    assert assert_hashes(output) == before


@pytest.mark.parametrize("raw", [
    "not json", '{"covers":true}', '{"covers":"true","confidence":0.9,"rationale":"bad bool"}',
    '{"covers":true,"confidence":NaN,"rationale":"bad finite"}',
    '{"covers":true,"confidence":1.5,"rationale":"bad range"}',
    '{"covers":true,"confidence":1.0,"rationale":"unsafe certainty"}',
    '{"covers":true,"confidence":true,"rationale":"bool confidence"}',
    '{"covers":true,"confidence":0.9,"rationale":"ok","approve_wrap":true}',
    '{"covers":true,"confidence":0.9,"rationale":""}',
    '{"covers":true,"covers":false,"confidence":0.9,"rationale":"duplicate"}',
])
def test_bad_raw_opinions_are_failed_not_creditable_abstentions_and_retained(tmp_path, raw):
    bundle = fixtures()
    bundle["attempts"][0]["response"] = raw
    output = tmp_path / "evidence"
    summary = E.evaluate(output, write_bundle(tmp_path, bundle))
    result = summary["metrics"]["fixture-replay-not-a-model"]
    assert result["counts"] == {"COMPLETE": 15, "FAILED": 1, "UNRUN": 0}
    assert result["capture"]["numerator"] == 10 and result["capture"]["denominator"] == 11
    assert result["correct_abstention"]["numerator"] == 5
    assert (output / "raw/16.bin").read_bytes() == raw.encode()
    assert json.loads((output / "slots/16.json").read_text())["label"] is None
    assert_hashes(output)


@pytest.mark.parametrize("binding", ["0" * 64, "sha-from-previous-evidence-revision"])
def test_wrong_or_stale_request_citations_fail_without_dropping_response(tmp_path, binding):
    bundle = fixtures(); bundle["attempts"][0]["request_sha256"] = binding
    output = tmp_path / "evidence"
    summary = E.evaluate(output, write_bundle(tmp_path, bundle))
    assert summary["metrics"]["fixture-replay-not-a-model"]["counts"]["FAILED"] == 1
    assert (output / "raw/16.bin").exists()
    assert_hashes(output)


@pytest.mark.parametrize("problem", ["wrong_protocol", "duplicate_attempt", "unknown_case", "malformed_bundle", "wrong_mode"])
def test_refused_bundle_seals_available_bytes_error_and_all_slots_not_success(tmp_path, problem):
    bundle = fixtures()
    if problem == "wrong_protocol": bundle["protocol_sha256"] = "0" * 64
    elif problem == "duplicate_attempt": bundle["attempts"].append(copy.deepcopy(bundle["attempts"][0]))
    elif problem == "unknown_case": bundle["attempts"][0]["case_id"] = "UNREGISTERED"
    elif problem == "wrong_mode": bundle["mode"] = "real-model-measured"
    path = write_bundle(tmp_path, bundle)
    if problem == "malformed_bundle": path.write_bytes(b'{"attempts":')
    output = tmp_path / "evidence"
    with pytest.raises(ValueError): E.evaluate(output, path)
    assert (output / "raw/original-replay.bin").read_bytes() == path.read_bytes()
    assert not (output / "summary.json").exists()
    assert json.loads((output / "error.json").read_text())["successful_summary"] is False
    assert len(list((output / "slots").glob("*.json"))) == 32
    assert_hashes(output)


def test_missing_slots_and_optional_metadata_are_not_silent_hard_gates(tmp_path):
    bundle = fixtures(); bundle["attempts"] = bundle["attempts"][:1]
    output = tmp_path / "evidence"
    summary = E.evaluate(output, write_bundle(tmp_path, bundle))
    result = summary["metrics"]["fixture-replay-not-a-model"]
    assert result["counts"] == {"COMPLETE": 1, "FAILED": 0, "UNRUN": 15}
    assert result["capture"]["denominator"] == 11
    assert result["decision_coverage"]["denominator"] == 16
    assert json.loads((output / "identity.json").read_text())["declared_replay_metadata"] == "UNKNOWN"


def test_interrupt_retains_started_failed_and_unrun_slots_before_adapter_execution(tmp_path):
    calls = []
    output = tmp_path / "evidence"
    class Interrupted(E.OfflineInterpreter):
        def match_beat_to_take(self, **kwargs):
            assert len(list((output / "slots").glob("*.json"))) == 32
            assert len(list((output / "requests").glob("*.json"))) == 16
            current = json.loads((output / "slots" / f"{len(calls):02d}.json").read_text())
            assert current["status"] == "FAILED" and current["error"] == "INTERRUPTED_BEFORE_COMPLETION"
            calls.append(kwargs)
            if len(calls) == 2: raise KeyboardInterrupt()
            return super().match_beat_to_take(**kwargs)
    with pytest.raises(KeyboardInterrupt): E.evaluate(output, baseline_factory=Interrupted)
    assert json.loads((output / "slots/00.json").read_text())["status"] == "COMPLETE"
    assert json.loads((output / "slots/01.json").read_text())["status"] == "FAILED"
    assert json.loads((output / "slots/02.json").read_text())["status"] == "UNRUN"
    assert not (output / "summary.json").exists()
    assert_hashes(output)


def test_adapter_failure_cannot_be_relabelled_successful_abstention(tmp_path):
    def failed(): raise RuntimeError("fixture transport failure")
    summary = E.evaluate(tmp_path / "evidence", baseline_factory=failed)
    result = summary["metrics"][E.BASELINE]
    assert result["counts"] == {"COMPLETE": 0, "FAILED": 16, "UNRUN": 0}
    assert result["correct_abstention"]["numerator"] == 0


def test_corrupt_denominator_is_refused():
    with pytest.raises(ValueError): E.metrics([{"case_id":"C01","mode":"fixture"}], {"C01":"POSITIVE","C02":"NEGATIVE"})


def test_frozen_binding_mismatch_refuses_before_evaluation(tmp_path, monkeypatch):
    monkeypatch.setitem(E.FROZEN, "docs/model-evidence-cases.json", "0" * 64)
    with pytest.raises(ValueError, match="Frozen input changed"):
        E.evaluate(tmp_path / "never-started")
    assert not (tmp_path / "never-started").exists()


def test_cli_has_no_real_model_activation_and_incomplete_replay_returns_nonzero(tmp_path):
    bundle = fixtures(); bundle["attempts"] = []
    assert E.main(["--output", str(tmp_path / "evidence"), "--replay", str(write_bundle(tmp_path, bundle))]) == 1
    with pytest.raises(SystemExit): E.main(["--output", str(tmp_path / "no-write"), "--invoke-model"])
    assert not (tmp_path / "no-write").exists()
