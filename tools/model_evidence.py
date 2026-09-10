"""Offline development evidence only. No model constructor, SDK or network runner.

Reuse the existing interpreter prompts/types and lexical baseline. Replay accepts
declared, already-captured structured responses, not proof of their origin.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lasttake.adapters.aws.bedrock_interpreter import (  # noqa: E402
    BedrockInterpreter, COVERAGE_PROMPT, CONTINUITY_PROMPT,
    _BeatMatchOut, _ContinuityOut,
)
from lasttake.adapters.local.interpreter import OfflineInterpreter  # noqa: E402
from lasttake.checks.coverage import MIN_MATCH_CONFIDENCE  # noqa: E402
from lasttake.checks.continuity import MIN_CONFLICT_CONFIDENCE  # noqa: E402

PREREGISTRATION = "c0593b9e5c464f7b3cdb5574aece7ff8aabb71ba"
FROZEN = {
    "docs/model-evidence-cases.json": "076d95085479b1f5f4efe948bd101613d49ce4888981229ba47dc0d82c55aa91",
    "docs/model-evidence-gold.json": "3c10cbf3561bd3f5491e12d0d4d8efba4bb798891fb55a5a29237ff6fa48e361",
    "docs/model-evidence-protocol.json": "04b77ed2627dff95a7c89676f10d78ef847fc5db6d251c44754c51f0c7da7847",
    "src/lasttake/adapters/local/interpreter.py": "ec0c53a016002bc43f08215f3a9c08c44f2b9e155fb69dd91b41514cee5bac91",
    "src/lasttake/adapters/aws/bedrock_interpreter.py": "c1d5cf97aff85aaa30194f53f871ad41ea111845841e677107afa2912a39032f",
    "src/lasttake/ports/interpreter.py": "933f68242d4b6ad859db2c2f01da472d2445e6677f5ebbb29765f2deb7fbe770",
}
BASELINE = "offline-lexical/1.0.0"
REPLAY_MODES = {"fixture-replay-not-a-model", "declared-bedrock-replay-unverified"}
PROTOCOL_HASH = FROZEN["docs/model-evidence-protocol.json"]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError("Nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def frozen_inputs():
    for path, expected in FROZEN.items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {path}")
    subprocess.run(["git", "merge-base", "--is-ancestor", PREREGISTRATION, "HEAD"], cwd=ROOT, check=True)
    protocol = strict_json((ROOT / "docs/model-evidence-protocol.json").read_bytes())
    cases = strict_json((ROOT / protocol["case_file"]).read_bytes())
    gold = strict_json((ROOT / protocol["gold_file"]).read_bytes())["labels"]
    if ([case["id"] for case in cases] != protocol["order"] or len(cases) != 16
            or set(gold) != set(protocol["order"])):
        raise ValueError("Frozen denominator mismatch")
    if protocol["confidence_thresholds"] != {"coverage": MIN_MATCH_CONFIDENCE, "continuity": MIN_CONFLICT_CONFIDENCE}:
        raise ValueError("Production threshold changed; require a new versioned protocol")
    return protocol, cases, gold


def invoke(interpreter, case):
    method = (interpreter.match_beat_to_take if case["kind"] == "coverage"
              else interpreter.compare_continuity)
    # Only the existing four input fields cross the model boundary, never gold/ID.
    return method(**case["inputs"])


class CapturedAgent:
    def __init__(self, response=None):
        self.request = None
        self.response = response

    def structured_output(self, schema, prompt):
        self.request = {"user_prompt": prompt, "output_schema": schema.model_json_schema()}
        if self.response is not None:
            return schema.model_validate(self.response, strict=True)
        values = {"confidence": 0.0, "rationale": "Prompt capture only; no inference."}
        values.update({"covers": False} if schema is _BeatMatchOut else
                      {"states_agree": False, "possibly_intentional": False})
        return schema.model_validate(values)


def isolated_adapter(agent):
    # Deliberately bypass __init__: it is the only place that constructs a model.
    adapter = object.__new__(BedrockInterpreter)
    adapter._model_id = "recorded-response-only"
    adapter._coverage = agent
    adapter._continuity = agent
    return adapter


def request_for(case):
    capture = CapturedAgent()
    invoke(isolated_adapter(capture), case)
    return {"kind": case["kind"], "inputs": case["inputs"],
            "input_sha256": digest(encoded(case["inputs"])),
            "system_prompt": COVERAGE_PROMPT if case["kind"] == "coverage" else CONTINUITY_PROMPT,
            **capture.request}


def opinion_from_raw(case, raw):
    response = strict_json(raw)
    required = {"covers", "confidence", "rationale"} if case["kind"] == "coverage" else {
        "states_agree", "possibly_intentional", "confidence", "rationale"}
    if not isinstance(response, dict) or set(response) != required:
        raise ValueError("Exact bounded opinion fields required")
    if any(type(response[k]) is not bool for k in required - {"confidence", "rationale"}):
        raise ValueError("Outcome fields must be booleans")
    confidence = response["confidence"]
    # Existing findings.validate disallows certainty for an interpretation.
    if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence < 1:
        raise ValueError("Finite non-certain interpretation confidence required")
    if not isinstance(response["rationale"], str) or not 0 < len(response["rationale"]) <= 10000:
        raise ValueError("Bounded nonempty rationale required")
    return invoke(isolated_adapter(CapturedAgent(response)), case)


def classify(case, opinion):
    threshold = MIN_MATCH_CONFIDENCE if case["kind"] == "coverage" else MIN_CONFLICT_CONFIDENCE
    if opinion.confidence < threshold:
        return "ABSTAIN"
    positive = opinion.covers if case["kind"] == "coverage" else opinion.states_agree
    return "POSITIVE" if positive else "NEGATIVE"


def metrics(slots, gold):
    result = {}
    for mode in sorted({slot["mode"] for slot in slots}):
        rows = [slot for slot in slots if slot["mode"] == mode]
        if len(rows) != len(gold) or {r["case_id"] for r in rows} != set(gold):
            raise ValueError("Cannot invent a complete denominator")
        counts = {state: sum(r["status"] == state for r in rows) for state in ("COMPLETE", "FAILED", "UNRUN")}
        eligible = lambda r: r["status"] == "COMPLETE"
        expected = lambda r: gold[r["case_id"]]
        def ratio(numerator, denominator):
            return {"numerator": numerator, "denominator": denominator,
                    "rate": numerator / denominator if counts["COMPLETE"] and denominator else None}
        result[mode] = {"slots": len(rows), "counts": counts,
            "capture": ratio(sum(eligible(r) and r["label"] == expected(r) and expected(r) != "ABSTAIN" for r in rows), sum(v != "ABSTAIN" for v in gold.values())),
            "false_positive": ratio(sum(eligible(r) and r["label"] == "POSITIVE" and expected(r) != "POSITIVE" for r in rows), sum(v != "POSITIVE" for v in gold.values())),
            "false_exception": ratio(sum(eligible(r) and r["label"] == "NEGATIVE" and expected(r) == "POSITIVE" for r in rows), sum(v == "POSITIVE" for v in gold.values())),
            "correct_abstention": ratio(sum(eligible(r) and r["label"] == "ABSTAIN" and expected(r) == "ABSTAIN" for r in rows), sum(v == "ABSTAIN" for v in gold.values())),
            "decision_coverage": ratio(sum(eligible(r) and r["label"] != "ABSTAIN" for r in rows), len(gold))}
    return result


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as target:
        target.write(encoded(value))
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def seal(output):
    files = {str(path.relative_to(output)).replace("\\", "/"): digest(path.read_bytes())
             for path in sorted(output.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    atomic_json(output / "manifest.json", {"schema": "lasttake/source-evidence-hashes/v1", "files": files})


def evaluate(output: Path, replay: Path | None = None, baseline_factory=OfflineInterpreter):
    """CI/offline only. A fresh output root retains failures, unrun slots and bytes."""
    protocol, cases, gold = frozen_inputs()
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "requests").mkdir()
    (output / "slots").mkdir()
    requests = {case["id"]: request_for(case) for case in cases}
    for case_id, request in requests.items():
        atomic_json(output / "requests" / f"{case_id}.json", request)
    slots = [{"case_id": case["id"], "kind": case["kind"], "mode": mode,
              "status": "UNRUN", "label": None, "request_sha256": digest(encoded(requests[case["id"]]))}
             for mode in (BASELINE, "declared-bedrock-replay-unverified") for case in cases]
    def save_slots():
        for index, slot in enumerate(slots):
            atomic_json(output / "slots" / f"{index:02d}.json", slot)
    save_slots()  # Before parsing external bytes or executing any adapter.
    identity = {"schema": protocol["schema"], "scope": "AUTHOR_DEVELOPMENT_SET_NOT_INDEPENDENT_ACCURACY",
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "preregistration_sha": PREREGISTRATION, "protocol_sha256": PROTOCOL_HASH,
        "source_hashes": {**FROZEN, "tools/model_evidence.py": digest(Path(__file__).read_bytes())},
        "ci_run_id": os.environ.get("GITHUB_RUN_ID", "UNKNOWN"), "ci_event": os.environ.get("GITHUB_EVENT_NAME", "UNKNOWN"),
        "model_calls_this_offline_process": 0, "offline_model_cost": 0,
        "original_replay_model_config": "UNKNOWN", "original_replay_usage": "UNKNOWN", "original_replay_model_cost": "UNKNOWN",
        "runner_infrastructure_cost": "UNKNOWN", "replay_provenance": "UNVERIFIED_DECLARATION"}
    atomic_json(output / "identity.json", identity)
    try:
        entries = {}
        if replay is not None:
            raw = replay.read_bytes()
            (output / "raw" / "original-replay.bin").write_bytes(raw)
            bundle = strict_json(raw)
            if bundle["protocol_sha256"] != PROTOCOL_HASH or bundle["mode"] not in REPLAY_MODES:
                raise ValueError("Replay mode/protocol binding refused")
            for entry in bundle["attempts"]:
                case_id = entry["case_id"]
                if case_id not in requests or case_id in entries:
                    raise ValueError("Unknown or duplicate attempt; no replacement allowed")
                entries[case_id] = entry
            for slot in slots[16:]:
                slot["mode"] = bundle["mode"]
            identity["declared_replay_metadata"] = bundle.get("metadata", "UNKNOWN")
            atomic_json(output / "identity.json", identity)
            save_slots()
        for index, slot in enumerate(slots):
            case = cases[index % 16]
            entry = entries.get(case["id"]) if index >= 16 else None
            if index >= 16 and entry is None:
                continue
            slot.update(status="FAILED", error="INTERRUPTED_BEFORE_COMPLETION")
            atomic_json(output / "slots" / f"{index:02d}.json", slot)
            try:
                if index < 16:
                    raw = encoded(asdict(invoke(baseline_factory(), case)))
                else:
                    raw = entry["response"].encode("utf-8")
                raw_path = f"raw/{index:02d}.bin"
                (output / raw_path).write_bytes(raw)  # Preserve BEFORE binding/parse.
                slot.update(raw_path=raw_path, raw_sha256=digest(raw))
                if entry is not None and entry["request_sha256"] != slot["request_sha256"]:
                    raise ValueError("Wrong/stale request citation binding")
                opinion = opinion_from_raw(case, raw)
                slot.update(status="COMPLETE", opinion=asdict(opinion), label=classify(case, opinion))
                slot.pop("error", None)
            except Exception as exc:
                slot.update(status="FAILED", error=type(exc).__name__)
            atomic_json(output / "slots" / f"{index:02d}.json", slot)
    except BaseException as exc:
        atomic_json(output / "error.json", {"error": type(exc).__name__, "status": "REFUSED_OR_INTERRUPTED", "successful_summary": False})
        raise
    else:
        summary = {"scope": identity["scope"], "protocol_sha256": PROTOCOL_HASH, "metrics": metrics(slots, gold),
                   "real_model_measurement": "NOT_RUN" if replay is None else "DECLARED_REPLAY_ORIGIN_UNVERIFIED",
                   "limits": "Text development set only; no quality advantage, footage/audio, human-time or production claim. Failures/unrun remain in fixed denominators."}
        atomic_json(output / "summary.json", summary)
        return summary
    finally:
        seal(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path, help="Already-captured inert JSON only; never invokes a model")
    args = parser.parse_args(argv)
    summary = evaluate(args.output, args.replay)
    print(json.dumps(summary, indent=2))
    return int(any(value["counts"]["FAILED"] or (args.replay and value["counts"]["UNRUN"])
                   for value in summary["metrics"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
