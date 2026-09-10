"""Read-only release-pair checks for the owner-gated recording workflow.

Frontend and backend ship independently. Optional workflow evidence must match
the observed revision of its own component; neither proof authorizes recording.
Only allowlisted release metadata is retained, never application session data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen


REPOSITORY = "upgradedev/lasttake-aws"
ORIGIN = "https://d3kf6hquzlli8g.cloudfront.net"
FRONTEND_WORKFLOW = ".github/workflows/frontend-deploy.yml"
BACKEND_WORKFLOW = ".github/workflows/deploy.yml"
BACKEND_STEPS = (
    "the URL answers, and it is the commit we just built",
    "the hero, on the deployed architecture",
    "the Strands to Bedrock path, actually run",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value),
            "An exact component revision is required")
    return value


def run_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value),
            "A proof run ID must be a positive decimal integer")
    return int(value)


def live_json(path):
    request = Request(ORIGIN + path, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        require(response.status == 200, "Live release endpoint did not return HTTP 200")
        return json.load(response)


def github_json(path):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{path}"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def workflow_proof(value, sha, workflow, api):
    if value == "":
        return None
    identity = run_id(value)
    run = api(f"actions/runs/{identity}")
    require(run.get("id") == identity and run.get("head_sha") == sha,
            "Proof run does not match its observed component revision")
    require(run.get("path") == workflow, "Proof run names the wrong workflow")
    require(run.get("status") == "completed" and run.get("conclusion") == "success",
            "Proof run must be completed and successful")
    attempt = run.get("run_attempt")
    require(type(attempt) is int and attempt > 0, "Proof run attempt is missing")
    if workflow == BACKEND_WORKFLOW:
        # deploy.yml also has teardown/lifecycle modes and a credential skip.
        # A successful workflow alone does not prove the deployed backend.
        jobs = api(f"actions/runs/{identity}/attempts/{attempt}/jobs?per_page=100")
        rows = jobs.get("jobs", [])
        require(jobs.get("total_count") == len(rows), "Incomplete backend proof jobs")
        deploy = [job for job in rows if job.get("name") == "deploy"]
        require(len(deploy) == 1 and deploy[0].get("status") == "completed"
                and deploy[0].get("conclusion") == "success",
                "Backend deployment job did not succeed")
        for name in BACKEND_STEPS:
            steps = [step for step in deploy[0].get("steps", []) if step.get("name") == name]
            require(len(steps) == 1 and steps[0].get("conclusion") == "success",
                    "Backend deployment proof step did not succeed")
    return {"runId": identity, "runAttempt": attempt, "headSha": sha,
            "workflow": workflow, "conclusion": "success"}


def observe(release_sha, hosted_id="", governed_id="", *, fetch=live_json, api=github_json):
    exact_sha(release_sha)
    for value in (hosted_id, governed_id):
        if value != "":
            run_id(value)
    release = fetch("/release.json")
    require(release.get("commit") == release_sha, "Frontend exact release mismatch")
    health = fetch("/healthz")
    require(health.get("ok") is True, "Backend health is not successful")
    backend_sha = exact_sha(health.get("commit"))
    return {
        "schemaVersion": "lasttake.video-release-proof/v1",
        "appOrigin": ORIGIN,
        "releaseSha": release_sha,
        "backendSha": backend_sha,
        "hostedProof": workflow_proof(hosted_id, release_sha, FRONTEND_WORKFLOW, api),
        "governedProof": workflow_proof(governed_id, backend_sha, BACKEND_WORKFLOW, api),
        "observedAt": datetime.now(timezone.utc).isoformat(),
    }


def unchanged(before, after):
    require(before.get("schemaVersion") == after.get("schemaVersion")
            == "lasttake.video-release-proof/v1", "Invalid release proof schema")
    for field in ("appOrigin", "releaseSha", "backendSha", "hostedProof", "governedProof"):
        require(field in before and field in after and before[field] == after[field],
                f"Recording release proof changed: {field}")


def recording_binding(before, after, capture, release_sha, hosted_id="", governed_id=""):
    unchanged(before, after)
    require(before["appOrigin"] == capture.get("appOrigin") == ORIGIN,
            "Capture origin does not match release evidence")
    require(before["releaseSha"] == capture.get("releaseSha") == exact_sha(release_sha),
            "Capture does not match the exact frontend release")
    binding = {"releaseSha": release_sha, "backendSha": exact_sha(before["backendSha"])}
    for field, value, proof_key, workflow, sha in (
        ("hostedRunId", hosted_id, "hostedProof", FRONTEND_WORKFLOW, release_sha),
        ("governedRunId", governed_id, "governedProof", BACKEND_WORKFLOW, binding["backendSha"]),
    ):
        proof = before[proof_key]
        if value == "":
            require(proof is None, "Unexpected optional workflow proof")
        else:
            identity = run_id(value)
            require(isinstance(proof, dict) and proof.get("runId") == identity
                    and proof.get("headSha") == sha and proof.get("workflow") == workflow
                    and proof.get("conclusion") == "success",
                    "Recording workflow proof does not match its component")
            binding[field] = identity
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    args = parser.parse_args()
    root = Path(os.environ["LASTTAKE_VIDEO_ROOT"])
    result = observe(os.environ["LASTTAKE_RELEASE_SHA"],
                     os.environ.get("LASTTAKE_HOSTED_RUN_ID", ""),
                     os.environ.get("LASTTAKE_GOVERNED_RUN_ID", ""))
    # Keep the actual after-observation even if drift makes the check fail.
    with (root / f"release-{args.phase}.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    if args.phase == "after":
        unchanged(json.loads((root / "release-before.json").read_text(encoding="utf-8")), result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
