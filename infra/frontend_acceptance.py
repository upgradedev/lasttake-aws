"""Sanitized, release-bound automated acceptance. No application mutations.

The browser job observes identity and parses JUnit without cloud credentials.
A separate main-only job publishes these inert bytes through the frontend role.
Neither receipt nor publisher claims that the containing workflow has completed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

URL = "https://d3kf6hquzlli8g.cloudfront.net/"
REPO = "upgradedev/lasttake-aws"
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
NUMBER = re.compile(r"[1-9][0-9]*")
MIN_PRODUCT_CASES = 20
MODE = "synthetic_data_scripted_planner_lexical_interpreter"
LIMITS = "Automated Chromium desktop/mobile journeys on fictional data. No human UAT, staff identity, live model evaluation, real messages or downstream delivery claim."
BASIS = "GET /healthz before and after journeys; unchanged observed commit"
KEYS = set("schema_version application environment frontend_commit backend_commit backend_commit_basis run_id run_attempt run_url observed_at preflight_at preflight journeys postflight totals retry_count human_uat execution_mode limits workflow_status junit_sha256 receipt_path".split())


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("invalid UTC observation time")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def fetch_json(path):
    # Paths are fixed by this module, never copied from scenario or receipt data.
    request = urllib.request.Request(URL + path, headers={"Cache-Control": "no-cache", "User-Agent": "lasttake-acceptance/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        require(response.status == 200, "public identity unavailable")
        media_type = "text/html" if path == "" else "application/json"
        require(media_type in response.headers.get("Content-Type", ""), "unexpected identity media type")
        data = response.read(1_000_001)
        require(len(data) <= 1_000_000, "identity too large")
        return data.decode("utf-8") if path == "" else read_json(data)


def identity(expected, request=fetch_json, now=utcnow):
    require(isinstance(expected, str) and SHA.fullmatch(expected), "full frontend SHA required")
    release, health = request("release.json"), request("healthz")
    require(release.get("commit") == expected, "frontend release mismatch")
    backend = health.get("commit")
    require(health.get("ok") is True and health.get("run_state_store") == "aurora-dsql", "backend health unavailable")
    require(isinstance(backend, str) and SHA.fullmatch(backend), "backend commit unavailable")
    html = request("")
    require(isinstance(html, str) and re.findall(r'<meta name="application-commit" content="([0-9a-f]{40})">', html) == [expected],
            "served root HTML differs from release")
    return {"frontend_commit": expected, "backend_commit": backend, "observed_at": stamp(now())}


def require_current_source(expected, environment=os.environ, command=subprocess.run):
    require(environment.get("GITHUB_REF") == "refs/heads/main", "main-only acceptance")
    require(environment.get("GITHUB_REPOSITORY") == REPO, "unexpected repository")
    require(environment.get("GITHUB_SHA") == expected and SHA.fullmatch(expected), "dispatch source differs from release")
    head = command(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    main = command(["gh", "api", f"repos/{REPO}/commits/main", "--jq", ".sha"],
                   check=True, capture_output=True, text=True).stdout.strip()
    require(head == expected == main, "stale dispatch or checkout")


def junit_totals(data, browser_results=None):
    require(len(data) <= 10_000_000 and b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "unsafe JUnit")
    root = ET.fromstring(data)
    require(root.tag == "testsuites", "expected Playwright JUnit testsuites")
    suites = list(root)
    require(bool(suites) and all(s.tag == "testsuite" for s in suites), "empty or malformed JUnit suites")
    total = 0
    names = set()
    for suite in suites:
        cases = suite.findall("testcase")
        require(bool(cases), "empty JUnit suite")
        require(not suite.findall("testsuite"), "nested suites unsupported")
        for key, expected in (("tests", len(cases)), ("failures", 0), ("errors", 0), ("skipped", 0)):
            require(suite.get(key) == str(expected), "JUnit suite counts disagree or contain failures/skips")
        for case in cases:
            require(case.get("name") and case.get("classname"), "unnamed JUnit case")
            name = (suite.get("name"), suite.get("hostname"), case.get("classname"), case.get("name"))
            require(name not in names, "duplicate JUnit case")
            names.add(name)
            require(all(child.tag in {"system-out", "system-err", "properties"} for child in case), "JUnit case failed, skipped or malformed")
        total += len(cases)
    for key, expected in (("tests", total), ("failures", 0), ("errors", 0), ("skipped", 0)):
        require(root.get(key) == str(expected), "JUnit totals disagree or contain failures/skips")
    require(total >= MIN_PRODUCT_CASES, "fewer than 20 required product cases")
    require(isinstance(browser_results, dict) and browser_results.get("errors") == [], "missing or failed Playwright JSON report")
    projects = browser_results.get("config", {}).get("projects", [])
    require({p.get("name") for p in projects} == {"desktop", "mobile"} and len(projects) == 2,
            "both browser projects required")
    require(all(p.get("retries") == 0 and p.get("repeatEach") == 1 for p in projects), "retries or repeated cases refused")
    stats = browser_results.get("stats", {})
    require(stats.get("expected") == total and all(stats.get(key) == 0 for key in ("unexpected", "skipped", "flaky")),
            "Playwright totals disagree or contain retries/failures/skips")
    tests = []

    def visit(suites):
        for suite in suites:
            for case in suite.get("specs", []):
                require(case.get("ok") is True, "failed browser case")
                tests.extend(case.get("tests", []))
            visit(suite.get("suites", []))

    visit(browser_results.get("suites", []))
    require(len(tests) == total, "JSON case count differs from JUnit")
    for test in tests:
        attempts = test.get("results", [])
        require(test.get("expectedStatus") == "passed" and test.get("status") == "expected", "expected failure or non-passing case refused")
        require(len(attempts) == 1 and attempts[0].get("status") == "passed" and attempts[0].get("retry") == 0
                and attempts[0].get("errors") == [] and not attempts[0].get("error"), "retried, skipped or failed attempt refused")
    return {"tests": total, "passed": total, "failed": 0, "skipped": 0}


def validate(receipt, now=None, fresh=False):
    require(isinstance(receipt, dict) and set(receipt) == KEYS, "unexpected receipt fields")
    for key, value in {"schema_version": 1, "application": "lasttake", "environment": "live_aws",
                       "backend_commit_basis": BASIS, "human_uat": "NOT_RUN", "execution_mode": MODE,
                       "limits": LIMITS, "workflow_status": "NOT_ASSERTED", "retry_count": 0, "preflight": "success",
                       "journeys": "success", "postflight": "success"}.items():
        require(type(receipt[key]) is type(value) and receipt[key] == value, "receipt scope or stage invalid")
    for key in ("frontend_commit", "backend_commit"):
        require(isinstance(receipt[key], str) and SHA.fullmatch(receipt[key]), "invalid commit")
    for key in ("run_id", "run_attempt"):
        require(isinstance(receipt[key], str) and NUMBER.fullmatch(receipt[key]), "invalid run identity")
    run, attempt = receipt["run_id"], receipt["run_attempt"]
    require(receipt["run_url"] == f"https://github.com/{REPO}/actions/runs/{run}/attempts/{attempt}", "invalid run URL")
    require(receipt["receipt_path"] == f"/acceptance/runs/{run}-{attempt}.json", "invalid receipt path")
    require(isinstance(receipt["junit_sha256"], str) and DIGEST.fullmatch(receipt["junit_sha256"]), "missing JUnit digest")
    counts = receipt["totals"]
    require(isinstance(counts, dict) and set(counts) == {"tests", "passed", "failed", "skipped"}, "invalid aggregate fields")
    require(all(type(n) is int and n >= 0 for n in counts.values()), "invalid aggregate counts")
    require(counts["tests"] >= MIN_PRODUCT_CASES and counts["passed"] == counts["tests"] and counts["failed"] == counts["skipped"] == 0, "incomplete acceptance")
    start, end = timestamp(receipt["preflight_at"]), timestamp(receipt["observed_at"])
    require(timedelta(0) <= end - start <= timedelta(minutes=20), "invalid acceptance time window")
    if fresh:
        require(timedelta(minutes=-5) <= (now or utcnow()) - end <= timedelta(hours=24), "stale or future proof")
    return receipt


def build(junit, before, after, environment=os.environ, browser_results=None):
    require(all(environment.get(key) == "success" for key in ("PREFLIGHT", "JOURNEYS", "POSTFLIGHT")), "all observed stages must succeed")
    expected = environment["EXPECTED_RELEASE"]
    require(before["frontend_commit"] == after["frontend_commit"] == expected, "frontend changed during acceptance")
    require(before["backend_commit"] == after["backend_commit"], "backend changed during acceptance")
    run, attempt = environment["GITHUB_RUN_ID"], environment["GITHUB_RUN_ATTEMPT"]
    receipt = {
        "schema_version": 1, "application": "lasttake", "environment": "live_aws",
        "frontend_commit": expected, "backend_commit": after["backend_commit"], "backend_commit_basis": BASIS,
        "run_id": run, "run_attempt": attempt,
        "run_url": f"https://github.com/{REPO}/actions/runs/{run}/attempts/{attempt}",
        "observed_at": after["observed_at"], "preflight_at": before["observed_at"],
        "preflight": "success", "journeys": "success", "postflight": "success",
        "totals": junit_totals(junit, browser_results), "retry_count": 0, "human_uat": "NOT_RUN", "execution_mode": MODE, "limits": LIMITS,
        "workflow_status": "NOT_ASSERTED", "junit_sha256": hashlib.sha256(junit).hexdigest(),
        "receipt_path": f"/acceptance/runs/{run}-{attempt}.json",
    }
    return validate(receipt, fresh=True)


def aws(*args):
    result = subprocess.run(["aws", *args, "--region", "eu-west-1", "--no-cli-pager"], check=True, capture_output=True, text=True)
    return read_json(result.stdout) if result.stdout.strip() else {}


def missing(error):
    return any(code in (error.stderr or "") for code in ("(NoSuchKey)", "(404)"))


def get_object(bucket, key, path, command):
    try:
        meta = command("s3api", "get-object", "--bucket", bucket, "--key", key, str(path))
        return path.read_bytes(), meta["ETag"]
    except subprocess.CalledProcessError as error:
        if missing(error):
            return None, None
        raise


def publish(data, expected, run, attempt, command=aws, request=fetch_json, now=utcnow):
    receipt = validate(read_json(data), now=now(), fresh=True)
    require(data == encode(receipt), "receipt bytes are not canonical")
    require((receipt["frontend_commit"], receipt["run_id"], receipt["run_attempt"]) == (expected, run, attempt), "artifact is from another run or release")
    outputs = command("cloudformation", "describe-stacks", "--stack-name", "lasttake-frontend")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in outputs["Stacks"][0]["Outputs"]}
    bucket = outputs["FrontendBucket"]
    require(re.fullmatch(r"lasttake-web-[0-9]{12}-eu-west-1", bucket) and outputs["FrontendUrl"] == URL, "unexpected frontend target")
    with tempfile.TemporaryDirectory(prefix="lasttake-proof-") as tmp:
        root = Path(tmp)
        payload = root / "receipt.json"
        payload.write_bytes(data)

        def same_release():
            live = identity(expected, request=request, now=now)
            require(live["backend_commit"] == receipt["backend_commit"], "backend changed since acceptance")
            deployed, _ = get_object(bucket, "release.json", root / "release.json", command)
            require(deployed is not None and read_json(deployed).get("commit") == expected, "origin release changed")

        same_release()
        key = receipt["receipt_path"].lstrip("/")
        # Always create-only. Even a retry with different bytes cannot erase history.
        try:
            command("s3api", "put-object", "--bucket", bucket, "--key", key, "--body", str(payload),
                    "--content-type", "application/json", "--cache-control", "no-store,max-age=0", "--if-none-match", "*")
        except subprocess.CalledProcessError as error:
            require(any(code in (error.stderr or "") for code in ("(PreconditionFailed)", "(ConditionalRequestConflict)")), "immutable publication refused")
            existing, _ = get_object(bucket, key, root / "existing.json", command)
            require(existing == data, "immutable receipt collision")
        previous, etag = get_object(bucket, "acceptance.json", root / "latest.json", command)
        if previous is not None:
            prior = validate(read_json(previous))
            require(timestamp(prior["observed_at"]) <= timestamp(receipt["observed_at"]), "newer acceptance already exists")
            if prior["observed_at"] == receipt["observed_at"]:
                require(previous == data, "same-time acceptance conflict")
        # The caller's job shares the frontend writer lock with frontend deploys.
        # Re-read the public pair and uncached S3 manifest immediately before CAS.
        same_release()
        if previous != data:
            condition = ("--if-match", etag) if etag else ("--if-none-match", "*")
            command("s3api", "put-object", "--bucket", bucket, "--key", "acceptance.json", "--body", str(payload),
                    "--content-type", "application/json", "--cache-control", "no-store,max-age=0", *condition)
        command("cloudfront", "create-invalidation", "--distribution-id", outputs["DistributionId"],
                "--paths", "/acceptance.json", "/acceptance.html", "/acceptance.js", "/" + key)
    return {"receipt_path": receipt["receipt_path"], "latest": "/acceptance.json", "workflow_status": "NOT_ASSERTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["observe", "build", "publish", "inspect-junit"])
    parser.add_argument("--output", default="frontend/acceptance-observations/acceptance-receipt.json")
    args = parser.parse_args()
    if args.action == "inspect-junit":
        print(json.dumps({"scope": "SOURCE_CI_ONLY", "totals": junit_totals(Path("frontend/test-results/e2e.xml").read_bytes(),
                         read_json(Path("frontend/test-results/e2e-results.json").read_bytes()))}))
        return
    expected = os.environ["EXPECTED_RELEASE"]
    if args.action in {"observe", "publish"}:
        require_current_source(expected)
    if args.action == "observe":
        result = identity(expected)
    elif args.action == "build":
        result = build(Path("frontend/test-results/e2e.xml").read_bytes(),
                       read_json(Path("frontend/acceptance-observations/preflight.json").read_bytes()),
                       read_json(Path("frontend/acceptance-observations/postflight.json").read_bytes()),
                       browser_results=read_json(Path("frontend/test-results/e2e-results.json").read_bytes()))
    else:
        # A publisher-only retry retains the producing acceptance job's attempt.
        result = publish(Path(args.output).read_bytes(), expected, os.environ["GITHUB_RUN_ID"], os.environ["PRODUCER_RUN_ATTEMPT"])
        print(json.dumps(result))
        return
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(encode(result))
    if args.action == "build":
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as outputs:
            outputs.write(f'artifact_name=acceptance-public-{result["run_id"]}-{result["run_attempt"]}\n')
            outputs.write(f'run_attempt={result["run_attempt"]}\n')


if __name__ == "__main__":
    main()
