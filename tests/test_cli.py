"""The commands a judge runs, exercised end to end against a temp workdir.

These matter more than they look. The CLI is the only surface a stranger
touches, and every claim on it is a claim we are making to somebody with no
reason to believe us.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lasttake import cli

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


@pytest.fixture()
def work(tmp_path):
    return tmp_path / "work"


def _run(work, *args):
    return cli.main(["--corpus", str(CORPUS), "--workdir", str(work), *args])


def test_checkpoint_prints_the_count_and_stops_for_the_first_ad(work, capsys):
    assert _run(work, "checkpoint") == 0
    out = capsys.readouterr().out
    assert "Of 34 required beats, 31 covered with evidence" in out
    assert "waiting for a human" in out
    assert "first_ad" in out
    assert "B-17" in out
    assert "correlation token:" in out


def test_the_checkpoint_fires_from_an_event(work, capsys):
    _run(work, "checkpoint")
    assert _run(work, "events") == 0
    out = capsys.readouterr().out
    assert "scene.wrap-checkpoint.requested" in out
    assert "finding.recorded" in out
    assert "Nobody pressed a button" in out


def test_approve_resumes_the_run_and_routes_the_pickup(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    assert _run(work, "approve", "--yes") == 0
    out = capsys.readouterr().out
    assert "this process did not exist when the run stopped" in out
    assert "Pickup approved" in out

    events = [json.loads(line) for line in (work / "events" / "events.jsonl").read_text().splitlines()]
    pickups = [e for e in events if e["event_type"] == "pickup.requested"]
    assert len(pickups) == 1


def test_declining_routes_nothing(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    _run(work, "approve")  # no --yes
    out = capsys.readouterr().out
    assert "did not approve" in out
    events = (work / "events" / "events.jsonl").read_text()
    assert "pickup.requested" not in events


def test_approve_with_nothing_pending_says_so(work, capsys):
    (work / "sessions").mkdir(parents=True)
    assert _run(work, "approve", "--yes") == 1
    assert "Nothing is waiting" in capsys.readouterr().err


def test_a_late_take_reruns_only_the_affected_checks(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    assert _run(work, "late-take", "--beat", "B-17") == 0
    out = capsys.readouterr().out
    # A new take changes the `takes` digest and every check reads `takes`, so
    # all four are genuinely affected and all four rerun. The narrowing story
    # belongs to `resolve rights` below, where exactly one artifact moves.
    assert "Affected checks: coverage, continuity, metadata, rights" in out
    assert "32 covered with evidence" in out
    assert "no_viable_coverage" not in out, "B-17 is covered once the pickup lands"


def test_supplying_the_release_clears_the_rights_exception(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    assert _run(work, "resolve", "rights", "--subject", "BG-07") == 0
    out = capsys.readouterr().out
    assert "Affected checks: rights" in out
    assert "keep their results" in out
    assert "0 with no release record" in out
    # The narrowing is not a claim in a print statement. The gate independently
    # re-derives it from which source digests moved, and this line is the gate
    # agreeing that the un-rerun findings are still admissible.
    assert "still cite digests that have not moved" in out


def test_a_decision_by_the_wrong_role_is_refused(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    findings = json.loads((work / "runs" / cli.RUN_ID / "findings.json").read_text())
    rights_gap = next(
        f for f in findings if f["check_type"] == "rights" and f["truth_state"] != "verified"
    )
    code = _run(
        work,
        "resolve",
        "decision",
        "--finding-id",
        rights_gap["finding_id"],
        "--action",
        "accept_exception",
        "--role",
        "dit",
        "--actor",
        "a data manager",
        "--reason",
        "looks fine",
    )
    assert code == 1
    assert "may not accept_exception" in capsys.readouterr().err


def test_a_supervisor_may_reject_a_coverage_false_positive(work, capsys):
    _run(work, "checkpoint")
    capsys.readouterr()
    findings = json.loads((work / "runs" / cli.RUN_ID / "findings.json").read_text())
    gap = next(
        f
        for f in findings
        if f["check_type"] == "coverage" and f["truth_state"] == "missing" and f["requirement_id"]
    )
    assert (
        _run(
            work,
            "resolve",
            "decision",
            "--finding-id",
            gap["finding_id"],
            "--action",
            "reject_false_positive",
            "--role",
            "script_supervisor",
            "--actor",
            "the script supervisor",
            "--reason",
            "it is on the B camera card",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "The original finding is unchanged" in out


def test_cli_decision_binds_current_finding_and_does_not_follow_same_id_reread(work):
    from lasttake.domain import policy
    from lasttake.domain.findings import from_dict
    _run(work, "checkpoint")
    records = json.loads((work / "runs" / cli.RUN_ID / "findings.json").read_text())
    conflict = next(f for f in records if f["check_type"] == "continuity" and f["requirement_id"])
    assert _run(work, "resolve", "decision", "--finding-id", conflict["finding_id"],
        "--action", "accept_exception", "--role", "script_supervisor", "--actor", "Reviewer", "--reason", "Reviewed exact records") == 0
    decision = policy.decision_from_dict(json.loads((work / "runs" / cli.RUN_ID / "decisions.json").read_text())[-1])
    assert decision.finding_sha256 == conflict["record_sha256"]
    assert policy._resolution(from_dict(conflict), [decision]) is True
    _run(work, "late-take", "--beat", "B-17")
    reread = next(f for f in json.loads((work / "runs" / cli.RUN_ID / "findings.json").read_text()) if f["finding_id"] == conflict["finding_id"])
    assert reread["record_sha256"] != decision.finding_sha256
    assert policy._resolution(from_dict(reread), [decision]) is None


def test_verify_accepts_an_intact_manifest_and_rejects_a_tampered_one(work, tmp_path, capsys):
    from lasttake.domain.sealing import seal

    good = tmp_path / "good.json"
    good.write_text(json.dumps(seal({"schema": "x", "scene_id": "SC-042", "counts": {"a": 1}})))
    assert cli.main(["verify", str(good)]) == 0
    assert "intact" in capsys.readouterr().out

    payload = json.loads(good.read_text())
    payload["counts"]["a"] = 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload))
    assert cli.main(["verify", str(bad)]) == 1
    assert "has been altered" in capsys.readouterr().out


def test_doctor_reports_the_environment_without_touching_aws(work, capsys):
    assert _run(work, "doctor") == 0
    out = capsys.readouterr().out
    assert "strands-agents" in out
    assert "Bedrock not checked" in out
