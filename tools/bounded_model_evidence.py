"""Evaluation-only one-shot Converse collector; export/finalize never use AWS.

The parent private runner owns single-use grant consumption and aggregate budget.
This is not the application's Strands adapter and has no repair/fallback loop.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import model_evidence as E

INSTRUMENT_SOURCE = "e1a090192df6b3470489d36349d9aba2960cda9d"
INSTRUMENT_HASH = "25ddeff4d0f4cb381a00a507c7d101cd9b20ebacc2b57fe3b497cf3e03a900ab"
MODEL = "eu.anthropic.claude-opus-5"
REGION = "eu-west-1"
MAX_OUTPUT = 512
MAX_REQUEST_BYTES = 16384
TEMPLATE_ALLOWANCE = 4096
BOUND = "ascii-serialized-request-bytes-plus-4096-template-tokens/v1"
CONFIG = {"model_id": MODEL, "region": REGION, "max_output_tokens": MAX_OUTPUT,
          "thinking": "disabled", "tool_choice": "record_opinion", "sdk_total_max_attempts": 1,
          "call_limit": 16, "max_request_bytes": MAX_REQUEST_BYTES,
          "input_token_bound": BOUND, "max_process_seconds": 900,
          "connect_timeout_seconds": 5, "read_timeout_seconds": 30}


def ascii_request(value):
    # Auditable, conservative serialization size, NOT a measured HTTP byte count.
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode("ascii")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=E.ROOT, text=True).strip()


def plan():
    _, cases, _ = E.frozen_inputs()
    if E.digest((E.ROOT / "tools/model_evidence.py").read_bytes()) != INSTRUMENT_HASH:
        raise ValueError("Frozen evaluator changed")
    git("merge-base", "--is-ancestor", INSTRUMENT_SOURCE, "HEAD")
    rows = []
    for case in cases:
        frozen = E.request_for(case)
        request = {"modelId": MODEL, "system": [{"text": frozen["system_prompt"]}],
                   "messages": [{"role": "user", "content": [{"text": frozen["user_prompt"]}]}],
                   "inferenceConfig": {"maxTokens": MAX_OUTPUT},
                   "additionalModelRequestFields": {"thinking": {"type": "disabled"}},
                   "toolConfig": {"tools": [{"toolSpec": {"name": "record_opinion",
                       "description": "Return the bounded opinion in the supplied schema.",
                       "inputSchema": {"json": frozen["output_schema"]}}}],
                       "toolChoice": {"tool": {"name": "record_opinion"}}}}
        raw = ascii_request(request)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("Request byte ceiling exceeded")
        rows.append({"case_id": case["id"], "request": request,
                     "request_sha256": E.digest(raw), "serialized_request_bytes": len(raw),
                     "input_tokens_reserved": len(raw) + TEMPLATE_ALLOWANCE,
                     "output_tokens_reserved": MAX_OUTPUT,
                     "frozen_request_sha256": E.digest(E.encoded(frozen))})
    return {"schema": "lasttake/bounded-converse-plan/v1", "source_sha": git("rev-parse", "HEAD"),
            "instrument_source": INSTRUMENT_SOURCE, "instrument_sha256": INSTRUMENT_HASH,
            "preregistration_sha": E.PREREGISTRATION, "protocol_sha256": E.PROTOCOL_HASH,
            "config": CONFIG, "config_sha256": E.digest(E.encoded(CONFIG)),
            "request_manifest_sha256": E.digest(E.encoded(rows)), "cases": rows,
            "scope": "EVALUATION_ONLY_DIRECT_CONVERSE_NOT_PRODUCTION_STRANDS",
            "token_bound_limit": "Reviewed assumption, not CountTokens or a provider-certified maximum: "
                "one token per serialized ASCII byte including schema, plus4096 for hidden framing. "
                "Parent must review this exact model/template allowance before granting. "
                "No cache, images, tools executed, repair, streaming, retries or warmup.",
            "model_measurement": "NOT_RUN", "runner_infrastructure_cost": "UNKNOWN"}


def decimal(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,7}(\.[0-9]{1,9})?", value):
        raise ValueError("Exact finite positive decimal string required")
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise ValueError("Exact finite positive decimal string required")
    return result


def reserve(row, rates):
    return (Decimal(row["input_tokens_reserved"]) * decimal(rates["input_usd_per_million"])
            + Decimal(MAX_OUTPUT) * decimal(rates["output_usd_per_million"])) / Decimal(1000000)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("UTC timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def context():
    return {key: os.environ.get(key, "") for key in (
        "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
        "GITHUB_REPOSITORY", "GITHUB_WORKFLOW_REF", "LASTTAKE_EVAL_PRIVATE_RUNNER",
        "LASTTAKE_EVAL_GRANT_SHA256")}


def validate(grant_raw, p, ctx, now):
    if (ctx["GITHUB_ACTIONS"] != "true" or ctx["GITHUB_EVENT_NAME"] != "workflow_dispatch"
            or ctx["GITHUB_RUN_ATTEMPT"] != "1" or ctx["LASTTAKE_EVAL_PRIVATE_RUNNER"] != "true"):
        raise ValueError("Only parent-controlled private manual run attempt1")
    if E.digest(grant_raw) != ctx["LASTTAKE_EVAL_GRANT_SHA256"]:
        raise ValueError("Parent-configured exact grant digest mismatch")
    g = E.strict_json(grant_raw)
    expected = {"schema": "lasttake/bounded-converse-grant/v1", "status": "PARENT_AUTHORIZED",
                "source_sha": p["source_sha"], "instrument_sha256": INSTRUMENT_HASH,
                "protocol_sha256": E.PROTOCOL_HASH, "model_id": MODEL, "region": REGION,
                "config_sha256": p["config_sha256"], "request_manifest_sha256": p["request_manifest_sha256"],
                "call_limit": 16, "run_attempt": 1, "currency": "USD",
                "run_id": ctx["GITHUB_RUN_ID"], "repository": ctx["GITHUB_REPOSITORY"],
                "workflow_ref": ctx["GITHUB_WORKFLOW_REF"], "token_bound_assumption": BOUND,
                "token_bound_reviewed": True}
    if any(type(g.get(k)) is not type(v) or g.get(k) != v for k, v in expected.items()):
        raise ValueError("Grant source/model/config/protocol/request/run binding mismatch")
    if not all(ctx[k] for k in ("GITHUB_RUN_ID", "GITHUB_REPOSITORY", "GITHUB_WORKFLOW_REF")):
        raise ValueError("Missing runner identity")
    if not re.fullmatch(r"[a-f0-9]{32}", g.get("grant_id", "")):
        raise ValueError("Unique grant identifier required")
    if not re.fullmatch(r"[a-f0-9]{64}", g.get("reservation_receipt_sha256", "")):
        raise ValueError("Parent single-use aggregate reservation receipt required")
    issued, expiry = timestamp(g["issued_at"]), timestamp(g["expires_at"])
    if not issued <= now < expiry or not 0 < expiry - issued <= 3600:
        raise ValueError("Grant expired/not yet active or exceeds one hour")
    if not isinstance(g.get("pricing_reference"), str) or not g["pricing_reference"].startswith("https://"):
        raise ValueError("Parent verified pricing reference required")
    if not issued - 86400 <= timestamp(g["pricing_verified_at"]) <= now:
        raise ValueError("Fresh parent price verification required")
    rates = g["rates"]
    if set(rates) != {"input_usd_per_million", "output_usd_per_million"}:
        raise ValueError("Exact two-rate plan required; unsupported billing needs new review")
    amount = decimal(g["allocated_usd"])
    worst = sum((reserve(row, rates) for row in p["cases"]), Decimal(0))
    if amount > Decimal(5) or worst > amount:
        raise ValueError("Full cohort worst reserve exceeds parent allocation or hard ceiling")
    return g, worst


def write_bytes_once(path, raw, echo=False):
    with path.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    if hasattr(os, "O_DIRECTORY"):
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    if echo:
        print("LASTTAKE_JOURNAL_BASE64 " + path.name + " " + base64.b64encode(raw).decode(), flush=True)


def write_once(path, value, echo=False):
    write_bytes_once(path, E.encoded(value), echo)


def export(output):
    p = plan()
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "request-plan.json", p)
    write_once(output / "grant-template-NOT_AUTHORIZED.json", {
        "schema": "lasttake/bounded-converse-grant/v1", "status": "NOT_AUTHORIZED",
        "source_sha": p["source_sha"], "instrument_sha256": INSTRUMENT_HASH,
        "protocol_sha256": E.PROTOCOL_HASH, "model_id": MODEL, "region": REGION,
        "config_sha256": p["config_sha256"], "request_manifest_sha256": p["request_manifest_sha256"],
        "call_limit": 16, "run_attempt": 1, "currency": "USD", "run_id": "PARENT_EXACT_RUN_ID",
        "repository": "PARENT_PRIVATE_REPOSITORY", "workflow_ref": "PARENT_EXACT_WORKFLOW_REF",
        "token_bound_assumption": BOUND, "token_bound_reviewed": False,
        "grant_id": "PARENT_UNIQUE_32_LOWERCASE_HEX", "reservation_receipt_sha256": "PARENT_SINGLE_USE_RECEIPT",
        "issued_at": "PARENT_UTC", "expires_at": "PARENT_UTC_WITHIN_ONE_HOUR",
        "pricing_reference": "PARENT_VERIFIED_HTTPS_SOURCE", "pricing_verified_at": "PARENT_UTC",
        "allocated_usd": "UNKNOWN", "rates": {"input_usd_per_million": "UNKNOWN", "output_usd_per_million": "UNKNOWN"}})
    # Reference arithmetic ONLY. These numbers are never accepted as a grant.
    rates = {"input_usd_per_million": "5.50", "output_usd_per_million": "27.50"}
    write_once(output / "cost-plan-NOT-A-GRANT.json", {
        "status": "NOT_AUTHORIZED_REFERENCE_ONLY", "model_measurement": "NOT_RUN",
        "reference_rates": rates, "allocated_usd": "UNKNOWN", "actual_model_cost": "UNKNOWN",
        "reference_worst_usd": str(sum((reserve(r, rates) for r in p["cases"]), Decimal(0))),
        "cases": [{"case_id": r["case_id"], "serialized_request_bytes": r["serialized_request_bytes"],
                   "input_tokens_reserved": r["input_tokens_reserved"], "max_output_tokens": MAX_OUTPUT,
                   "reference_worst_usd": str(reserve(r, rates))} for r in p["cases"]],
        "pricing_reference": "https://platform.claude.com/docs/en/about-claude/pricing",
        "limits": "Reference geo rates only; parent verifies rates, template bound and shared allocation. "
                  "No global-budget inference. No CountTokens, model request or real measurement."})
    E.seal(output)
    return p


def sdk_client():
    # No alternate auth setup, model discovery, STS call or Strands constructor.
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=REGION, config=Config(
        retries={"mode": "standard", "total_max_attempts": 1}, connect_timeout=5,
        read_timeout=30, ignore_configured_endpoint_urls=True))


def response_bytes(response):
    # Preserve the FULL SDK object, not a truncated rationale. SDK-decoded JSON is
    # not claimed to be original HTTP wire bytes. Unexpected binary is reversible.
    def binary(value):
        if isinstance(value, bytes):
            return {"__sdk_bytes_base64__": base64.b64encode(value).decode()}
        raise TypeError("Unsupported SDK response value")
    # Nonfinite SDK values are retained as-is; strict replay will refuse them.
    return (json.dumps(response, default=binary, allow_nan=True, sort_keys=True, indent=2) + "\n").encode()


def check_usage(response, row, rates):
    metadata = response["ResponseMetadata"]
    if (metadata["HTTPStatusCode"] != 200 or metadata["RetryAttempts"] != 0
            or not isinstance(metadata["RequestId"], str) or not metadata["RequestId"]):
        raise ValueError("Missing request identity or unexpected SDK retry/status")
    usage = response["usage"]
    for key, ceiling in (("inputTokens", row["input_tokens_reserved"]), ("outputTokens", MAX_OUTPUT)):
        if type(usage.get(key)) is not int or not 0 <= usage[key] <= ceiling:
            raise ValueError("Usage absent or token reservation bound exceeded")
    if type(usage.get("totalTokens")) is not int or usage["totalTokens"] != usage["inputTokens"] + usage["outputTokens"]:
        raise ValueError("Inconsistent total usage")
    if any(usage.get(key, 0) != 0 for key in ("cacheReadInputTokens", "cacheWriteInputTokens")):
        raise ValueError("Unexpected cache billing")
    return str((Decimal(usage["inputTokens"]) * decimal(rates["input_usd_per_million"])
                + Decimal(usage["outputTokens"]) * decimal(rates["output_usd_per_million"])) / Decimal(1000000))


def opinion(response):
    if response["stopReason"] != "tool_use" or response["output"]["message"]["role"] != "assistant":
        raise ValueError("No complete opinion tool response; no repair allowed")
    content = response["output"]["message"]["content"]
    if len(content) != 1 or set(content[0]) != {"toolUse"}:
        raise ValueError("Exactly one bounded tool output required")
    tool = content[0]["toolUse"]
    if tool["name"] != "record_opinion":
        raise ValueError("Wrong output tool")
    return E.encoded(tool["input"]).decode()


def collect(output, grant_raw, ctx=None, client_factory=sdk_client, clock=time.time):
    """One fresh directory per parent-consumed grant; never resume or replace calls."""
    p = plan()
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked source must be clean")
    ctx = context() if ctx is None else ctx
    authorized_at = clock()
    g, worst = validate(grant_raw, p, ctx, authorized_at)
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", p, True)
    write_once(output / "grant.json", g, True)
    write_bytes_once(output / "grant-original.bin", grant_raw, True)
    write_once(output / "authorization.json", {"context": ctx, "authorized_at": authorized_at}, True)
    write_once(output / "slots.json", [{"case_id": r["case_id"], "status": "UNRUN"} for r in p["cases"]], True)
    started = time.monotonic()
    reserved = Decimal(0)
    try:
        client = client_factory()
        for index, row in enumerate(p["cases"]):
            if clock() >= timestamp(g["expires_at"]) or time.monotonic() - started >= 900:
                raise TimeoutError("Expiry or finite process boundary reached")
            cost = reserve(row, g["rates"])
            if reserved + cost > worst or E.digest(ascii_request(row["request"])) != row["request_sha256"]:
                raise ValueError("Reservation/request drift refused before call")
            write_once(output / f"{index:02d}-reserved.json", {
                "case_id": row["case_id"], "request": row["request"], "request_sha256": row["request_sha256"],
                "reserved_usd": str(cost), "unknown_outcome_consumes_full_reservation": True}, True)
            reserved += cost  # Never refunded, even with low actual usage or unknown outcome.
            try:
                response = client.converse(**copy.deepcopy(row["request"]))
            except BaseException as exc:
                if hasattr(exc, "response"):
                    write_bytes_once(output / f"{index:02d}-sdk-error.json", response_bytes(exc.response), True)
                raise
            write_bytes_once(output / f"{index:02d}-raw.json", response_bytes(response), True)
            # Full response was fsynced and flushed to stdout BEFORE any semantic/usage parse.
            check_usage(response, row, g["rates"])  # Missing/over-bound usage stops further calls.
    except BaseException as exc:
        write_once(output / "interruption.json", {"error": type(exc).__name__, "remaining": "UNRUN"}, True)
        raise
    finally:
        finalize(output)
    return E.strict_json((output / "final/summary.json").read_bytes())


def finalize(output):
    """Snapshot available bytes before validation; no SDK, retries or resumed calls.

    Parent runner must stop the producer first. Even if it did not, only captured
    immutable bytes feed replay/hashes. A partial snapshot refuses with raw intact.
    """
    final = output / "final"
    final.mkdir(exist_ok=False)
    captured = final / "captured"
    captured.mkdir()
    # Copy before parsing, including malformed files. No successful summary on refusal.
    for path in sorted(p for p in output.iterdir() if p.is_file()):
        with (captured / path.name).open("xb") as target:
            target.write(path.read_bytes())
            target.flush()
            os.fsync(target.fileno())
    try:
        read = lambda name: E.strict_json((captured / name).read_bytes())
        p, g = read("plan.json"), read("grant.json")
        expected = plan()
        if p != expected or read("slots.json") != [{"case_id": r["case_id"], "status": "UNRUN"} for r in p["cases"]]:
            raise ValueError("Captured plan/denominator does not match frozen source")
        auth = read("authorization.json")
        verified, _ = validate((captured / "grant-original.bin").read_bytes(), p, auth["context"], auth["authorized_at"])
        if verified != g:
            raise ValueError("Captured grant changed")
        attempts, slots = [], []
        total_reserved, known_cost = Decimal(0), Decimal(0)
        unknown_cost = False
        for index, row in enumerate(p["cases"]):
            slot = {"case_id": row["case_id"], "status": "UNRUN", "actual_model_cost_usd": "UNKNOWN"}
            if (captured / f"{index:02d}-reserved.json").exists():
                reservation = read(f"{index:02d}-reserved.json")
                if (reservation["case_id"] != row["case_id"] or reservation["request"] != row["request"]
                        or reservation["request_sha256"] != row["request_sha256"]
                        or Decimal(reservation["reserved_usd"]) != reserve(row, g["rates"])):
                    raise ValueError("Captured reservation binding mismatch")
                total_reserved += Decimal(reservation["reserved_usd"])
                slot.update(status="FAILED", error="UNKNOWN_OUTCOME", reserved_usd=reservation["reserved_usd"])
                attempt = {"case_id": row["case_id"], "request_sha256": row["frozen_request_sha256"], "response": ""}
                try:
                    response = read(f"{index:02d}-raw.json")
                    slot["actual_model_cost_usd"] = check_usage(response, row, g["rates"])
                    known_cost += Decimal(slot["actual_model_cost_usd"])
                    slot.update(usage=response["usage"], aws_request_id=response["ResponseMetadata"]["RequestId"])
                    attempt["response"] = opinion(response)
                except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
                    slot["error"] = type(exc).__name__
                unknown_cost |= slot["actual_model_cost_usd"] == "UNKNOWN"
                attempts.append(attempt)
            elif (captured / f"{index:02d}-raw.json").exists():
                raise ValueError("Raw response without prior reservation")
            slots.append(slot)
        replay = {"mode": "declared-bedrock-replay-unverified", "protocol_sha256": E.PROTOCOL_HASH,
                  "attempts": attempts, "metadata": {"collector_scope": p["scope"], "grant": g,
                      "raw_capture_directory": "../captured", "source_sha": p["source_sha"],
                      "provenance_limit": "SDK receipts and request hashes, not independent attestation or model-authored citations."}}
        write_once(final / "replay.json", replay)
        summary = E.evaluate(final / "evaluation", final / "replay.json")
        for index, slot in enumerate(slots):
            evaluated = E.strict_json((final / "evaluation/slots" / f"{index + 16:02d}.json").read_bytes())
            slot["status"] = evaluated["status"]
            if slot["status"] == "COMPLETE":
                slot.pop("error", None)
        write_once(final / "summary.json", {"source_sha": p["source_sha"], "scope": p["scope"], "slots": slots,
            "counts": {s: sum(r["status"] == s for r in slots) for s in ("COMPLETE", "FAILED", "UNRUN")},
            "reserved_usd_never_refunded": str(total_reserved), "known_usage_cost_usd": str(known_cost),
            "actual_model_cost_usd": "UNKNOWN" if unknown_cost else str(known_cost),
            "allocation_usd": g["allocated_usd"], "runner_infrastructure_cost": "UNKNOWN",
            "response_body_bytes": "UNKNOWN", "request_bytes_scope": "serialized request estimate, not total network",
            "model_origin": "DECLARED_SDK_RECEIPTS_NOT_INDEPENDENTLY_ATTESTED", "metrics": summary["metrics"],
            "limits": "Author development set; no independent accuracy, production Strands, human-time or AWS latency claim."})
    except BaseException as exc:
        write_once(final / "error.json", {"error": type(exc).__name__, "successful_summary": False})
        raise
    finally:
        E.seal(final)
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "collect", "finalize"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export":
        export(args.output)
        return 0
    if args.command == "collect":
        if args.grant is None:
            parser.error("collect requires a parent grant; export cannot authorize calls")
        collect(args.output, args.grant.read_bytes())
    else:
        finalize(args.output)
    summary = E.strict_json((args.output / "final/summary.json").read_bytes())
    return int(summary["counts"] != {"COMPLETE": 16, "FAILED": 0, "UNRUN": 0})


if __name__ == "__main__":
    raise SystemExit(main())
