"""Walk the judge's journey against the live URL and fail on the first lie.

A status code is not a check. The page can load while the checkpoint is broken,
the count can be wrong, the run can fail to stop for the 1st AD, or the whole
thing can have quietly fallen back to S3 for run state. Each of those looks
fine from the outside and none of them is fine.

So this asserts the specific claims the README makes, in the order a judge
meets them, and says which one failed rather than "the site is down".

    python tools/uptime_check.py https://<url>/

Exit code 0 when every claim holds, 1 otherwise. No dependencies beyond the
standard library, so it runs anywhere without an install step.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

TIMEOUT = 60

#: The numbers the README, the video and the Devpost description all state. If
#: the deployed pipeline stops producing them, every one of those surfaces is
#: making a claim that is no longer true, which is the failure this catches.
EXPECTED_COUNTS = {
    "required_beats": 34,
    "covered_with_evidence": 31,
    "raising_exceptions": 2,
    "without_release_record": 1,
    "not_assessed": 0,
}


class CheckFailed(Exception):
    """One named claim did not hold."""


def _request(url: str, payload: dict | None = None) -> tuple[int, dict | str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - a network failure is a real result
        raise CheckFailed(f"{type(exc).__name__}: {exc}") from exc
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


def check(base: str) -> list[str]:
    """Return the lines to print. Raises :class:`CheckFailed` on the first problem."""
    base = base if base.endswith("/") else base + "/"
    lines: list[str] = ["## Live URL check", "", f"`{base}`", ""]
    started = time.time()

    # 1. The page a judge lands on.
    status, body = _request(base)
    if status != 200:
        raise CheckFailed(f"GET / returned {status}, not 200")
    if not isinstance(body, str) or "know whether you truly have the scene" not in body:
        raise CheckFailed("GET / did not serve the demo page")
    lines.append("- the page loads and carries the promise")

    # 2. What the deployment says about itself.
    status, health = _request(base + "healthz")
    if status != 200 or not isinstance(health, dict) or not health.get("ok"):
        raise CheckFailed(f"healthz returned {status}: {health}")
    store = health.get("run_state_store")
    if store != "aurora-dsql":
        raise CheckFailed(
            f"run state is on {store!r}, not aurora-dsql. The architecture the README "
            "describes is not the one that is running."
        )
    lines.append(f"- run state is on Aurora DSQL, commit `{str(health.get('commit'))[:12]}`")

    # 3. The checkpoint, and the count every judge-facing surface states.
    run_id = f"uptime-{uuid.uuid4().hex[:12]}"
    status, state = _request(base + "api/checkpoint", {"run_id": run_id})
    if status != 200 or not isinstance(state, dict):
        raise CheckFailed(f"checkpoint returned {status}: {state}")
    counts = state.get("counts")
    if counts != EXPECTED_COUNTS:
        raise CheckFailed(f"the count changed. expected {EXPECTED_COUNTS}, got {counts}")
    lines.append(f"- `{state['headline']}`")

    # 4. The product's whole point: it stops and waits for a named human.
    pending = state.get("pending_approval")
    if not pending:
        raise CheckFailed(
            "the run did not stop for the 1st AD. A checkpoint that never pauses is "
            "not this product."
        )
    reason = pending.get("reason", {})
    if reason.get("required_role") != "first_ad":
        raise CheckFailed(f"stopped for {reason.get('required_role')!r}, expected first_ad")
    first_container = health.get("served_by", {}).get("container_id")
    lines.append(f"- the run stopped and is waiting for the {reason['required_role']} on {reason.get('beat_id')}")

    # 5. A second request resumes it. This is the hero, checked twice a day.
    status, resumed = _request(
        base + "api/approve",
        {"run_id": run_id, "interrupt_id": pending["id"], "approve": True},
    )
    if status != 200 or not isinstance(resumed, dict):
        raise CheckFailed(f"approve returned {status}: {resumed}")
    if "Pickup approved" not in str(resumed.get("message", "")):
        raise CheckFailed(f"the resume did not route the pickup: {resumed.get('message')}")
    lines.append("- a separate request resumed the run and routed the pickup")

    # 6. Eligibility is still refused, because a release is still missing.
    if resumed.get("eligible"):
        raise CheckFailed(
            "the scene reads as eligible while a release is still missing. The gate is "
            "failing open, which is the one thing it must never do."
        )
    lines.append("- the gate still refuses, because a release is still missing")

    # 7. The cross-run query that is the reason a database is here at all.
    status, blocked = _request(base + "api/blocked")
    if status != 200 or not isinstance(blocked, dict) or "blocked" not in blocked:
        raise CheckFailed(f"the blocked-runs query returned {status}: {blocked}")
    lines.append(f"- the cross-run query answers: {len(blocked['blocked'])} run(s) blocked")

    lines += ["", f"All checks passed in {time.time() - started:.1f}s."]
    return lines


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: uptime_check.py <base-url>", file=sys.stderr)
        return 2
    try:
        for line in check(argv[1]):
            print(line)
    except CheckFailed as exc:
        print("## Live URL check FAILED")
        print()
        print(f"**{exc}**")
        print()
        print("The rules require the project to be reachable until the judging period")
        print("ends on 2026-10-08 17:00 PT.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
