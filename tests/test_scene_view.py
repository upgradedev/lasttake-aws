"""The lined script is what a visitor sees before any check has finished.

If it is wrong the product looks broken to the only person qualified to judge
it, so the shape is pinned here. These tests import no SDK, which is the point:
the view over the package is domain shaping, not agent output.
"""

from __future__ import annotations

import pathlib

from lasttake.adapters.local.interpreter import OfflineInterpreter
from lasttake.app.scene_view import scene_view
from lasttake.checks import continuity as continuity_check
from lasttake.checks import coverage as coverage_check
from lasttake.checks import metadata as metadata_check
from lasttake.checks import rights as rights_check
from lasttake.domain import policy
from lasttake.domain.package import load_package

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus"


def view() -> dict:
    return scene_view(load_package(CORPUS))


def findings() -> list:
    package = load_package(CORPUS)
    interpreter = OfflineInterpreter()
    run_id = "test-sceneview"
    return (
        coverage_check.run(package, run_id, interpreter, policy.POLICY_VERSION)
        + continuity_check.run(package, run_id, interpreter, policy.POLICY_VERSION)
        + metadata_check.run(package, run_id, policy.POLICY_VERSION)
        + rights_check.run(package, run_id, policy.POLICY_VERSION)
    )


def test_the_script_is_the_whole_scene_and_says_which_beats_are_required():
    v = view()
    assert len(v["beats"]) == 36, "every beat is drawn, required or not"
    assert v["required_beats"] == 34
    optional = [b["beat_id"] for b in v["beats"] if not b["required"]]
    assert optional == ["B-35", "B-36"], (
        "the two the shot plan adds and the current revision does not require"
    )


def test_every_take_hangs_off_a_beat_and_no_slate_is_used_twice():
    v = view()
    seen = {t["take_id"] for b in v["beats"] for t in b["takes"]}
    assert len(seen) == v["take_count"] == 40, "a take that hangs off nothing is invisible"

    slates = [t["slate"] for b in v["beats"] for t in b["takes"]]
    unique = {s for s in slates}
    assert len(unique) == 40, (
        "one slate identifies one take on a real set. A repeated slate is the "
        f"first thing a script supervisor would catch: {sorted(unique)}"
    )


def test_the_beat_with_no_coverage_is_visibly_empty():
    v = view()
    empty = [b for b in v["beats"] if b["required"] and not b["takes"]]
    assert [b["beat_id"] for b in empty] == ["B-17"]
    assert empty[0]["planned_shot"] is None, "it was never on the shot plan either"


def test_every_finding_can_be_pointed_at_a_place_a_person_can_turn_to():
    v = view()
    for finding in findings():
        where = v["locations"].get(finding.requirement_id)
        assert where, (
            f"{finding.check_type.value} finding {finding.finding_id} names "
            f"{finding.requirement_id!r}, which the scene cannot locate. The "
            "interface would print a bare identifier at a script supervisor."
        )
        assert where != finding.requirement_id, (
            f"{finding.requirement_id!r} resolves to itself, which tells nobody "
            "which page to turn to"
        )


def test_the_view_carries_no_verdict():
    """Judgement arrives from the checks and the gate, never from this."""
    v = view()
    assert "status" not in v and "eligible" not in v
    for beat in v["beats"]:
        assert "status" not in beat, "a beat's status comes from the rollup, not from here"
        assert "reason" not in beat
    for beat in v["beats"]:
        for take in beat["takes"]:
            assert set(take) == {
                "take_id", "slate", "shot_id", "lens_mm", "camera_roll", "sound_roll",
                "timecode_in", "media_id", "preferred", "usable", "note",
                "visible_people", "visible_assets",
            }, "a take is what the report says it is, with nothing added"


def test_nobody_is_offered_a_way_to_accept_away_a_missing_release():
    v = view()
    assert v["authority"]["rights"]["may_accept"] == [], (
        "the page reads this table to decide whether to draw a control. If it "
        "ever gains a role, the interface grows a button that must not exist."
    )
    assert v["authority"]["rights"]["may_confirm"] == ["production_coordinator"]
