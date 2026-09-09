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
#: The five numbers every judge-facing surface states. Compared field by field,
#: never as a whole dict: adding `basis` to the payload turned an unchanged count
#: into a red check for eighteen hours, because dict equality treats a new key as
#: a changed number. An assertion about five values should fail when one of the
#: five moves and at no other time.
EXPECTED_COUNTS = {
    "required_beats": 34,
    "covered_with_evidence": 31,
    "raising_exceptions": 2,
    "without_release_record": 1,
    "not_assessed": 0,
}

#: What those beats rest on. Not one of the five, and pinned separately so the
#: breakdown cannot drift unwatched either.
EXPECTED_BASIS = {
    "declared_by_the_production": 2,
    "corroborated_by_the_interpreter": 31,
    "confirmed_by_a_named_human": 0,
    "insufficient_evidence": 1,
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
    # And what the page must never say. This check speaks to the API for
    # eleven steps and used to read the page exactly once, for one sentence.
    # In that blind spot a browser-only feature shipped that printed
    # "CLEAR TO SHOOT. All labor, turnaround, and technical rules verified."
    # from three hardcoded conditionals, and sat on the live URL for six days
    # behind a green run of this file.
    for forbidden in (
        "CLEAR TO SHOOT",
        "rules verified",
        "Multi-Agent Evaluation",
        "safe to wrap.",
    ):
        if forbidden.lower() in body.lower():
            raise CheckFailed(
                f"the page prints {forbidden!r}. This product does not clear a scene "
                "and does not infer a pass from absent evidence, and the page it "
                "serves must not either"
            )
    lines.append("- the page loads, carries the promise, and gives no clearance")

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

    # 3. The lined script. It is what the page paints first, before any check
    #    has finished, so if it is broken a judge sees an empty product.
    run_id = f"uptime-{uuid.uuid4().hex[:12]}"
    status, scene = _request(base + "api/scene", {"run_id": run_id})
    if status != 200 or not isinstance(scene, dict):
        raise CheckFailed(f"api/scene returned {status}: {scene}")
    if scene.get("required_beats") != EXPECTED_COUNTS["required_beats"]:
        raise CheckFailed(
            f"the scene says {scene.get('required_beats')} required beats, the count "
            f"says {EXPECTED_COUNTS['required_beats']}"
        )
    with_takes = sum(1 for b in scene.get("beats", []) if b.get("takes"))
    if with_takes < 30:
        raise CheckFailed(f"only {with_takes} beats carry takes; the lined script is empty")
    if scene.get("authority", {}).get("rights", {}).get("may_accept") != []:
        raise CheckFailed("the page would offer a control that accepts away a missing release")
    lines.append(
        f"- the lined script paints {len(scene['beats'])} beats, "
        f"{scene['take_count']} takes, and offers nobody a way to accept away a release"
    )

    # 4. The checkpoint, and the count every judge-facing surface states.
    status, state = _request(base + "api/checkpoint", {"run_id": run_id})
    if status != 200 or not isinstance(state, dict):
        raise CheckFailed(f"checkpoint returned {status}: {state}")
    counts = state.get("counts") or {}
    moved = {
        name: (want, counts.get(name))
        for name, want in EXPECTED_COUNTS.items()
        if counts.get(name) != want
    }
    if moved:
        raise CheckFailed(f"the count changed: {moved}")

    basis = counts.get("basis")
    if basis is None:
        raise CheckFailed(
            "the count no longer says what it rests on. `basis` is what separates a "
            "mapping the production declared from one a reader corroborated, and "
            "without it `covered` is one word doing four jobs again"
        )
    shifted = {
        name: (want, basis.get(name))
        for name, want in EXPECTED_BASIS.items()
        if basis.get(name) != want
    }
    if shifted:
        raise CheckFailed(f"what the count rests on changed: {shifted}")

    lines.append(f"- `{state['headline']}`")
    lines.append(
        "- of those beats, "
        f"{basis['corroborated_by_the_interpreter']} corroborated by the interpreter, "
        f"{basis['declared_by_the_production']} resting on the production's record alone, "
        f"{basis['insufficient_evidence']} on nothing"
    )

    # 5. The product's whole point: it stops and waits for a named human.
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

    # 6. A second request resumes it. This is the hero, checked twice a day.
    status, resumed = _request(
        base + "api/approve",
        {"run_id": run_id, "interrupt_id": pending["id"], "approve": True},
    )
    if status != 200 or not isinstance(resumed, dict):
        raise CheckFailed(f"approve returned {status}: {resumed}")
    if "Pickup approved" not in str(resumed.get("message", "")) or "Bus accepted" not in str(resumed.get("message", "")):
        raise CheckFailed(f"the resume has no accepted pickup receipt: {resumed.get('message')}")
    deliveries = [d for d in resumed.get("delivery_outcomes", []) if d["event_type"] == "pickup.requested"]
    if len(deliveries) != 1 or deliveries[0]["status"] != "accepted" or not deliveries[0]["reference"]:
        raise CheckFailed("No saved bus-acceptance receipt for the pickup")
    lines.append("- a separate request resumed the run; the bus accepted the pickup request, not proof of downstream completion")

    # 7. Eligibility is still refused, because a release is still missing.
    if resumed.get("eligible"):
        raise CheckFailed(
            "the scene reads as eligible while a release is still missing. The gate is "
            "failing open, which is the one thing it must never do."
        )
    lines.append("- the gate still refuses, because a release is still missing")

    # 8. The rest of the shoot day, to a published turnover. This walk is here
    #    because it was not: three defects lived on the live URL for a day
    #    behind a check that stopped at step seven. A take that did not survive
    #    the request that captured it, a raw 500 from any prompt while an
    #    approval was open, and a gate reached by asking a model to invoke it,
    #    which on a resumed run returned the previous packet.
    status, late = _request(base + "api/late-take", {"run_id": run_id, "beat_id": "B-17"})
    if status != 200:
        raise CheckFailed(f"late-take returned {status}: {late}")
    status, after = _request(base + "api/state", {"run_id": run_id})
    covered = {b["beat_id"]: b["status"] for b in after.get("beats", [])}
    if covered.get("B-17") != "covered_with_evidence":
        raise CheckFailed(
            "the pickup take did not survive the request that captured it: B-17 reads "
            f"{covered.get('B-17')!r} on the next request"
        )
    lines.append("- the pickup take is still on the card on the following request")

    status, _ = _request(base + "api/resolve-rights", {"run_id": run_id, "subject": "BG-07"})
    if status != 200:
        raise CheckFailed(f"resolve-rights returned {status}")
    status, gated = _request(base + "api/evaluate", {"run_id": run_id})
    if status != 200:
        raise CheckFailed(f"evaluate returned {status}: {gated}")
    if gated.get("eligible"):
        raise CheckFailed(
            "the scene reads as eligible while two conflicts are untriaged. Supplying "
            "evidence is not the same as settling a judgement."
        )
    owed = {c["finding_id"]: c["required_role"] for c in gated.get("causes", [])}
    if set(owed.values()) != {"script_supervisor", "dit"}:
        raise CheckFailed(f"the gate owes the wrong people: {owed}")
    lines.append(
        "- evidence is on file and the gate still refuses, naming two people who owe a "
        "judgement it will not make for them"
    )

    for finding_id, role in owed.items():
        status, _ = _request(
            base + "api/decide",
            {
                "run_id": run_id,
                "finding_id": finding_id,
                "action": "accept_exception",
                "role": role,
                "actor": f"uptime check standing in as the {role}",
                "reason": "Automated liveness walk.",
            },
        )
        if status != 200:
            raise CheckFailed(f"{role} could not triage {finding_id}: {status}")
    status, cleared = _request(base + "api/evaluate", {"run_id": run_id})
    if not cleared.get("eligible"):
        raise CheckFailed(f"still not eligible after triage: {cleared.get('causes')}")
    lines.append("- both judgements recorded by the role the policy names, and the gate clears")

    status, asked = _request(base + "api/wrap", {"run_id": run_id})
    approval = (asked or {}).get("pending_approval")
    if status != 200 or not approval:
        raise CheckFailed(f"the wrap was not put to the 1st AD: {status} {asked}")
    status, wrapped = _request(
        base + "api/wrap",
        {"run_id": run_id, "interrupt_id": approval["id"], "approve": True},
    )
    if not wrapped.get("wrap_approved"):
        raise CheckFailed("the wrap approval did not take")
    status, turnover = _request(base + "api/turnover", {"run_id": run_id})
    if status != 200 or not turnover.get("turnover"):
        raise CheckFailed(f"editorial received nothing: {status}")
    lines.append("- the 1st AD approved the wrap and the turnover is published and sealed")

    # 9. The cross-run query that is the reason a database is here at all.
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
