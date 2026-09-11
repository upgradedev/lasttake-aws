"""Private, manual evaluation supervisor. Source CI exercises only injected fakes.

An approved portfolio plan partitions the entire dollar ceiling before any call.
This LastTake supervisor consumes only its fixed slice via a create-only GitHub
reservation tag. Other application runners remain unintegrated and inactive.
Tags are durable workflow records, NOT WORM or protection against repo admins.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import bounded_model_evidence as B

E = B.E
REPOSITORIES = {"LastTake": "upgradedev/lasttake-aws", "Merismos": "upgradedev/merismos-aws",
                "Archon": "upgradedev/archon-aws-strands"}
MAX_CALLS = {"LastTake": 16, "Merismos": 14, "Archon": 12}
APP = "LastTake"
REPO = REPOSITORIES[APP]
SCHEMA = "portfolio/fixed-evaluation-slices/v1"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def context():
    return {key: os.environ.get(key, "") for key in (
        "GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER",
        "GITHUB_RUN_ATTEMPT", "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_ID",
        "GITHUB_WORKFLOW_REF", "GITHUB_SHA")}


def template(p):
    """Export source bindings, never manufacture approval, authority or run identity."""
    allocations = {}
    for app, repo in REPOSITORIES.items():
        row = {key: "REQUIRES_REVIEW" for key in (
            "source_sha", "request_manifest_sha256", "protocol_sha256", "config_sha256")}
        if app == APP:
            row.update({key: p[key] for key in row})
        row.update(repository=repo, allocated_usd="0.00", max_calls=MAX_CALLS[app],
                   run_number="REQUIRES_PINNING", workflow_ref="REQUIRES_PINNING",
                   role_arn="NOT_PROVISIONED", bound_reviewed=False)
        allocations[app] = row
    return {"schema": SCHEMA, "status": "NOT_APPROVED", "currency": "USD",
            "fixed_slices": True, "budget_id": "REQUIRES_PARENT_SINGLE_BUDGET_ID",
            "ceiling_usd": "5.00", "issued_at": "NOT_ISSUED", "expires_at": "NOT_ISSUED",
            "pricing_verified_at": "NOT_VERIFIED", "pricing_reference": "NOT_VERIFIED",
            "rates": {"input_usd_per_million": "0.00", "output_usd_per_million": "0.00"},
            "allocations": allocations}


def validate(raw, approved_digest, p, ctx, now, role_arn):
    if (not re.fullmatch(r"[a-f0-9]{64}", approved_digest or "")
            or E.digest(raw) != approved_digest):
        raise ValueError("Exact independently configured approval digest required")
    plan = E.strict_json(raw)
    if (plan.get("schema") != SCHEMA or plan.get("status") != "PARENT_APPROVED"
            or plan.get("currency") != "USD" or plan.get("fixed_slices") is not True
            or not re.fullmatch(r"[a-f0-9]{32}", plan.get("budget_id", ""))):
        raise ValueError("Unapproved fixed portfolio budget")
    issued, expiry = B.timestamp(plan["issued_at"]), B.timestamp(plan["expires_at"])
    if not issued <= now < expiry or not 0 < expiry - issued <= 3600:
        raise ValueError("Budget expiry must be within one hour of issue")
    if not issued - 86400 <= B.timestamp(plan["pricing_verified_at"]) <= now:
        raise ValueError("Fresh parent price verification required")
    if not str(plan["pricing_reference"]).startswith("https://"):
        raise ValueError("Price reference required")
    rates = plan["rates"]
    if set(rates) != {"input_usd_per_million", "output_usd_per_million"}:
        raise ValueError("Only reviewed two-rate text inference is supported")
    for key, floor in (("input_usd_per_million", "5.50"), ("output_usd_per_million", "27.50")):
        if B.decimal(rates[key]) < Decimal(floor):
            raise ValueError("Rates below the reference floor need a separately reviewed instrument")
    slices = plan["allocations"]
    if set(slices) != set(REPOSITORIES):
        raise ValueError("All three fixed allocations must be present exactly once")
    total = Decimal(0)
    for app, row in slices.items():
        if row["repository"] != REPOSITORIES[app] or row["bound_reviewed"] is not True:
            raise ValueError("Wrong repository or unreviewed token bound")
        for key, length in (("source_sha", 40), ("request_manifest_sha256", 64),
                            ("protocol_sha256", 64), ("config_sha256", 64)):
            if not re.fullmatch(r"[a-f0-9]{" + str(length) + "}", row[key]):
                raise ValueError("Every allocation needs an exact source/request binding")
        if type(row["max_calls"]) is not int or not 0 < row["max_calls"] <= MAX_CALLS[app]:
            raise ValueError("Finite per-application call bound required")
        if (not re.fullmatch(r"[1-9][0-9]*", row["run_number"])
                or not row["workflow_ref"].startswith(
                    row["repository"] + "/.github/workflows/ci.yml@refs/heads/")):
            raise ValueError("Exact manual workflow number and branch required")
        total += B.decimal(row["allocated_usd"])
    ceiling = B.decimal(plan["ceiling_usd"])
    if ceiling > Decimal(5) or total > ceiling:
        raise ValueError("Fixed slices exceed aggregate USD5 ceiling")
    row = slices[APP]
    if (ctx["GITHUB_ACTIONS"] != "true" or ctx["GITHUB_EVENT_NAME"] != "workflow_dispatch"
            or ctx["GITHUB_RUN_ATTEMPT"] != "1" or ctx["GITHUB_REPOSITORY"] != REPO
            or ctx["GITHUB_SHA"] != p["source_sha"]
            or ctx["GITHUB_RUN_NUMBER"] != row["run_number"]
            or ctx["GITHUB_WORKFLOW_REF"] != row["workflow_ref"]
            or not re.fullmatch(r"[1-9][0-9]*", ctx["GITHUB_RUN_ID"])
            or not re.fullmatch(r"[1-9][0-9]*", ctx["GITHUB_REPOSITORY_ID"])):
        raise ValueError("Only the pinned manual first attempt can consume a slice")
    for key in ("source_sha", "request_manifest_sha256", "protocol_sha256", "config_sha256"):
        if row[key] != p[key]:
            raise ValueError("Current collector differs from the approved allocation")
    if row["max_calls"] != len(p["cases"]):
        raise ValueError("The entire fixed cohort must be reserved")
    if (not re.fullmatch(r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+", role_arn or "")
            or row["role_arn"] != role_arn):
        raise ValueError("Exact separately provisioned evaluation role required; no fallback")
    worst = sum((B.reserve(case, rates) for case in p["cases"]), Decimal(0))
    if worst > B.decimal(row["allocated_usd"]):
        raise ValueError("Full cohort cannot fit its fixed allocation")
    return plan


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("GitHub ledger redirects are refused")


class GitHubLedger:
    """Fixed-origin API; one attempt, no ref updates/deletes or secret-valued logs."""

    def __init__(self, token):
        if not token:
            raise ValueError("Missing repository-scoped workflow token")
        self.token = token

    def request(self, method, suffix, body=None):
        allowed = ((method == "GET" and (suffix == "" or suffix.startswith("/git/ref/tags/eval-reservations/")
                                         or re.fullmatch(r"/git/tags/[a-f0-9]{40}", suffix)))
                   or (method == "POST" and suffix in ("/git/tags", "/git/refs")))
        if not allowed:
            raise ValueError("Ledger operation outside the create-only contract")
        request = urllib.request.Request("https://api.github.com/repos/" + REPO + suffix,
            data=None if body is None else E.encoded(body), method=method,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2026-03-10"})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                data = response.read(1048577)
                if response.status != (201 if method == "POST" else 200) or len(data) > 1048576:
                    raise ValueError("Uncertain ledger response; no inference allowed")
                return E.strict_json(data)
        except urllib.error.HTTPError as error:
            # 409/422 may mean a consumed ref; never retry or reclaim the slice.
            raise ValueError(f"Ledger refused HTTP {error.code}; reservation remains unavailable") from None


def private_repository(ledger, ctx):
    identity = ledger.request("GET", "")
    if (identity.get("private") is not True or identity.get("full_name") != REPO
            or str(identity.get("id")) != ctx["GITHUB_REPOSITORY_ID"]):
        raise ValueError("Actual private repository identity required before reservation")


def consume(plan, p, ctx, ledger):
    private_repository(ledger, ctx)
    ref = "refs/tags/eval-reservations/" + plan["budget_id"] + "/lasttake"
    receipt = {"schema": "portfolio/consumed-fixed-slice/v1", "budget_id": plan["budget_id"],
               "app": APP, "source_sha": p["source_sha"], "run_id": ctx["GITHUB_RUN_ID"],
               "run_number": ctx["GITHUB_RUN_NUMBER"], "allocated_usd": plan["allocations"][APP]["allocated_usd"],
               "plan_sha256": E.digest(E.encoded(plan)), "ref": ref,
               "refund": "NEVER; failures, cancellation and unknown outcomes retain the entire slice"}
    tag = ledger.request("POST", "/git/tags", {"tag": ref.removeprefix("refs/tags/"),
        "message": E.encoded(receipt).decode(), "object": p["source_sha"], "type": "commit"})
    tag_sha = tag.get("sha", "")
    if not re.fullmatch(r"[a-f0-9]{40}", tag_sha):
        raise ValueError("Invalid immutable reservation object")
    created = ledger.request("POST", "/git/refs", {"ref": ref, "sha": tag_sha})
    expected = {"ref": ref, "object": {"type": "tag", "sha": tag_sha}}
    def matches(value):
        return value.get("ref") == ref and all(value.get("object", {}).get(k) == v for k, v in expected["object"].items())
    if not matches(created) or not matches(ledger.request("GET", "/git/ref/" + ref.removeprefix("refs/"))):
        raise ValueError("Reservation creation not independently observed; no inference")
    return {**receipt, "tag_sha": tag_sha}


def collector_grant(plan, p, ctx, receipt):
    row = plan["allocations"][APP]
    return {"schema": "lasttake/bounded-converse-grant/v1", "status": "PARENT_AUTHORIZED",
        "source_sha": p["source_sha"], "instrument_sha256": B.INSTRUMENT_HASH,
        "protocol_sha256": E.PROTOCOL_HASH, "model_id": B.MODEL, "region": B.REGION,
        "config_sha256": p["config_sha256"], "request_manifest_sha256": p["request_manifest_sha256"],
        "call_limit": 16, "run_attempt": 1, "currency": "USD", "run_id": ctx["GITHUB_RUN_ID"],
        "repository": REPO, "workflow_ref": ctx["GITHUB_WORKFLOW_REF"],
        "token_bound_assumption": B.BOUND, "token_bound_reviewed": True,
        "grant_id": E.digest((plan["budget_id"] + "/lasttake").encode())[:32],
        "reservation_receipt_sha256": E.digest(E.encoded(receipt)),
        "issued_at": plan["issued_at"], "expires_at": plan["expires_at"],
        "pricing_reference": plan["pricing_reference"], "pricing_verified_at": plan["pricing_verified_at"],
        "allocated_usd": row["allocated_usd"], "rates": plan["rates"]}


def reserve_bundle(raw, approved_digest, p, ctx, now, role_arn, output, ledger):
    plan = validate(raw, approved_digest, p, ctx, now, role_arn)
    output.mkdir(parents=True, exist_ok=False)
    B.write_bytes_once(output / "approved-plan.json", raw, True)
    B.write_once(output / "context.json", ctx, True)
    receipt = consume(plan, p, ctx, ledger)
    B.write_once(output / "reservation.json", receipt, True)
    grant = collector_grant(plan, p, ctx, receipt)
    B.write_once(output / "grant.json", grant, True)
    return grant


def verify_bundle(raw, approved_digest, p, ctx, now, role_arn, output, ledger):
    plan = validate(raw, approved_digest, p, ctx, now, role_arn)
    if (output / "approved-plan.json").read_bytes() != raw or E.strict_json((output / "context.json").read_bytes()) != ctx:
        raise ValueError("Local bundle does not match this exact approved run")
    receipt = E.strict_json((output / "reservation.json").read_bytes())
    grant = E.strict_json((output / "grant.json").read_bytes())
    if grant != collector_grant(plan, p, ctx, receipt):
        raise ValueError("Collector grant was modified")
    ref = "refs/tags/eval-reservations/" + plan["budget_id"] + "/lasttake"
    if (receipt["ref"] != ref or receipt["source_sha"] != p["source_sha"]
            or receipt["run_id"] != ctx["GITHUB_RUN_ID"] or receipt["plan_sha256"] != E.digest(E.encoded(plan))):
        raise ValueError("Consumed reservation identity changed")
    private_repository(ledger, ctx)
    observed = ledger.request("GET", "/git/ref/" + ref.removeprefix("refs/"))
    if (observed.get("ref") != ref or observed.get("object", {}).get("type") != "tag"
            or observed.get("object", {}).get("sha") != receipt["tag_sha"]):
        raise ValueError("Durable reservation no longer agrees")
    tagged = ledger.request("GET", "/git/tags/" + receipt["tag_sha"])
    payload = {key: value for key, value in receipt.items() if key != "tag_sha"}
    if (tagged.get("sha") != receipt["tag_sha"] or tagged.get("object", {}).get("type") != "commit"
            or tagged.get("object", {}).get("sha") != p["source_sha"]
            or tagged.get("message") != E.encoded(payload).decode()):
        raise ValueError("Reservation object does not bind the exact receipt and source")
    return grant


def supervise(command, environment, seconds=960, grace=5):
    """Outer timeout terminates the process group; never starts a replacement call."""
    child = subprocess.Popen(command, env=environment, start_new_session=os.name != "nt")
    try:
        return child.wait(timeout=seconds)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            if os.name == "nt":
                child.terminate()
            else:
                os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # Child exit raced with the timeout; still no replacement.
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    child.kill()
                else:
                    os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=grace)
        return 124


def run_bundle(raw, digest, p, ctx, now, role, output, ledger, launch=supervise):
    grant = verify_bundle(raw, digest, p, ctx, now, role, output, ledger)
    # Same-run duplicate steps cannot spawn a second child, even before first raw output.
    B.write_once(output / "launch-consumed.json", {"run_id": ctx["GITHUB_RUN_ID"], "grant": E.digest(E.encoded(grant))}, True)
    env = dict(os.environ)
    for name in list(env):
        if name in {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"}:
            env.pop(name)
    env.update(ctx, LASTTAKE_EVAL_PRIVATE_RUNNER="true", LASTTAKE_EVAL_GRANT_SHA256=E.digest(E.encoded(grant)))
    cohort = output / "cohort"
    code = launch([sys.executable, str(E.ROOT / "tools/bounded_model_evidence.py"), "collect",
                   "--grant", str(output / "grant.json"), "--output", str(cohort)], env)
    B.write_once(output / "supervisor-result.json", {"exit_code": code, "replacement_calls": 0}, True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["template", "preflight", "reserve", "run", "recover"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "template":
        args.output.mkdir(parents=True, exist_ok=False)
        B.write_once(args.output / "plan-NOT_APPROVED.json", template(B.plan()))
        return 0
    if args.mode == "recover":
        cohort = args.output / "cohort"
        if cohort.exists() and not (cohort / "final").exists():
            B.finalize(cohort)  # Offline snapshot only after the supervisor has exited.
        return 0
    p, ctx = B.plan(), context()
    if B.git("status", "--porcelain", "--untracked-files=no") or B.git("rev-parse", "HEAD") != ctx["GITHUB_SHA"]:
        raise ValueError("Clean exact-source checkout required")
    raw = os.environ.get("LASTTAKE_EVAL_PLAN_JSON", "").encode()
    approved = os.environ.get("LASTTAKE_EVAL_APPROVED_PLAN_SHA256", "")
    role = os.environ.get("LASTTAKE_EVAL_ROLE_ARN", "")
    now = B.timestamp(utc_now())
    validate(raw, approved, p, ctx, now, role)
    if args.mode == "preflight":
        print("Pinned plan and all fixed allocations validated; no ledger or AWS call")
        return 0
    ledger = GitHubLedger(os.environ.get("GH_TOKEN", ""))
    if args.mode == "reserve":
        reserve_bundle(raw, approved, p, ctx, now, role, args.output, ledger)
        return 0
    return run_bundle(raw, approved, p, ctx, now, role, args.output, ledger)


if __name__ == "__main__":
    raise SystemExit(main())
