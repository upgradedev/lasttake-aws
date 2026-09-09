"""The targeted rerun, idempotency, and the version window.

The last test in this file is gate C6: a fixture that starts at a different
offset from the parameter under test. A test whose fixture is built from the
same value the code passes in cannot fail, and that class of test is how a
version window silently stops working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lasttake.adapters.local.infrastructure import LocalEventBus, LocalRunStore
from lasttake.adapters.local.interpreter import OfflineInterpreter
from lasttake.checks import coverage, rights
from lasttake.domain import policy, rollup
from lasttake.domain.events import Event, EventType, affected_by
from lasttake.ports.infrastructure import Receipt
from lasttake.domain.findings import TruthState
from lasttake.domain.package import (
    CameraReportRow,
    RightsRecord,
    Take,
    load_package,
    with_extra_take,
    with_rights_record,
)

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


@pytest.fixture()
def package():
    return load_package(CORPUS)


def _event(event_type: EventType, payload: dict) -> Event:
    return Event(
        event_type=event_type,
        production_id="P",
        scene_id="SC-042",
        payload=payload,
        actor="test",
        correlation_id="c1",
    )


# -- events ----------------------------------------------------------------


def test_the_same_fact_delivered_twice_has_one_idempotency_key():
    a = _event(EventType.TAKE_CAPTURED, {"take_id": "T-041"})
    b = _event(EventType.TAKE_CAPTURED, {"take_id": "T-041"})
    assert a.event_id != b.event_id, "two deliveries, two ids"
    assert a.idempotency_key == b.idempotency_key, "one fact, one key"


def test_a_different_fact_gets_a_different_key():
    a = _event(EventType.TAKE_CAPTURED, {"take_id": "T-041"})
    b = _event(EventType.TAKE_CAPTURED, {"take_id": "T-042"})
    assert a.idempotency_key != b.idempotency_key


def test_a_rights_update_does_not_rerun_coverage():
    """This table is what makes the rerun targeted instead of total."""
    assert affected_by(_event(EventType.RIGHTS_RECORD_UPDATED, {})) == ("rights",)
    assert "coverage" in affected_by(_event(EventType.TAKE_CAPTURED, {}))
    assert affected_by(_event(EventType.FINDING_RECORDED, {})) == ()


def test_a_child_event_keeps_the_chain_walkable():
    parent = _event(EventType.WRAP_CHECKPOINT_REQUESTED, {})
    child = parent.child(EventType.ANALYSIS_REQUESTED, {"checks": ["coverage"]}, "orch")
    assert child.parent_event_id == parent.event_id
    assert child.causation_id == parent.event_id
    assert child.correlation_id == parent.correlation_id


def test_the_run_store_makes_duplicate_delivery_harmless(tmp_path):
    store = LocalRunStore(tmp_path)
    event = _event(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"})
    assert store.already_handled(event.idempotency_key) is False
    store.mark_handled(event.idempotency_key, "run-1")
    assert store.already_handled(event.idempotency_key) is True


def test_the_event_log_is_durable(tmp_path):
    bus = LocalEventBus(tmp_path)
    receipt = bus.publish(_event(EventType.WRAP_CHECKPOINT_REQUESTED, {}))
    assert receipt.accepted
    assert len(LocalEventBus(tmp_path).replay()) == 1


# -- the targeted rerun ----------------------------------------------------


def test_a_late_take_closes_the_coverage_gap_and_moves_the_revision(package):
    before = package.revision_digest()
    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=["B-17"],
        slate="42K/1",
        camera_roll="A006",
        sound_roll="SR06",
        timecode_in="22:41:12:00",
        timecode_out="22:42:03:00",
        lens_mm=50,
        media_id="A006R2F41",
        preferred=True,
        usable=True,
        note="Pickup. Clean single, held for the reaction.",
        visible_people=["DELPHINE"],
        visible_assets=[],
        captured_at="2026-08-19T22:41:00Z",
    )
    row = CameraReportRow("T-041", "A006R2F41", 50, "A006")
    updated = with_extra_take(package, take, row)

    assert updated.revision_digest() != before, "a new take is a new revision"
    assert len(updated.takes) == len(package.takes) + 1
    assert len(package.takes) == 40, "the original package is untouched"

    fresh = coverage.run(
        updated, "r", OfflineInterpreter(), policy.POLICY_VERSION, only_beats=("B-17",)
    )
    assert len(fresh) == 1, "a targeted rerun checks one beat, not thirty-four"
    assert fresh[0].truth_state is TruthState.VERIFIED


def test_a_supplied_release_closes_the_rights_gap(package):
    record = RightsRecord(
        record_id="REL-007",
        subject_id="BG-07",
        subject_kind="person",
        document_type="background release",
        scope="all media",
        territory="worldwide",
        expires_on=None,
        status="executed",
    )
    updated = with_rights_record(package, record)
    fresh = rights.run(
        updated, "r", policy.POLICY_VERSION, only_subjects=("BG-07",)
    )
    assert len(fresh) == 1
    assert fresh[0].truth_state is TruthState.VERIFIED
    assert "not a legal opinion" in fresh[0].observation


def test_an_unexecuted_release_is_conflicting_not_verified(package):
    updated = with_rights_record(
        package,
        RightsRecord(
            record_id="REL-008",
            subject_id="BG-07",
            subject_kind="person",
            document_type="background release",
            scope="all media",
            territory="worldwide",
            expires_on=None,
            status="pending signature",
        ),
    )
    fresh = rights.run(updated, "r", policy.POLICY_VERSION, only_subjects=("BG-07",))
    assert fresh[0].truth_state is TruthState.CONFLICTING
    assert "pending signature" in fresh[0].observation


# -- gate C6: a fixture at a different offset from the parameter -----------


def test_an_expired_licence_is_caught_from_a_date_the_code_never_sees(package):
    """The window fixture starts somewhere the production code cannot reach.

    ``as_of`` is a parameter the check takes. Building the fixture's expiry from
    that same parameter would make the assertion true by construction. So the
    expiry is a literal, the as-of dates are literals on both sides of it, and
    the test asserts the boundary flips.
    """
    from datetime import date

    updated = with_rights_record(
        package,
        RightsRecord(
            record_id="LIC-099",
            subject_id="BG-07",
            subject_kind="person",
            document_type="background release",
            scope="all media",
            territory="worldwide",
            expires_on="2026-06-30",
            status="executed",
        ),
    )

    before_expiry = rights.run(
        updated,
        "r",
        policy.POLICY_VERSION,
        as_of=date(2026, 6, 29),
        only_subjects=("BG-07",),
    )[0]
    after_expiry = rights.run(
        updated,
        "r",
        policy.POLICY_VERSION,
        as_of=date(2026, 7, 1),
        only_subjects=("BG-07",),
    )[0]

    assert before_expiry.truth_state is TruthState.VERIFIED
    assert after_expiry.truth_state is TruthState.CONFLICTING
    assert "expired on 2026-06-30" in after_expiry.observation


def test_a_scope_narrower_than_policy_is_not_verified(package):
    updated = with_rights_record(
        package,
        RightsRecord(
            record_id="LIC-100",
            subject_id="BG-07",
            subject_kind="person",
            document_type="background release",
            scope="festival only",
            territory="worldwide",
            expires_on=None,
            status="executed",
        ),
    )
    finding = rights.run(
        updated, "r", policy.POLICY_VERSION, only_subjects=("BG-07",)
    )[0]
    assert finding.truth_state is TruthState.CONFLICTING
    assert "festival only" in finding.observation


# -- one claim, one publish, and a failure that can be retried --------------


def test_two_callers_racing_one_approval_publish_it_once(tmp_path):
    """The check-then-set this replaced let both of them through.

    Two Lambdas resuming the same approval is not hypothetical: it is what a
    double-tapped Approve button on a slow connection does. The cost of getting
    it wrong is a real assistant director receiving the same pickup request
    twice, which is exactly the noise this product exists to remove.
    """
    import threading

    from lasttake.adapters.local.infrastructure import LocalRunStore

    store = LocalRunStore(tmp_path / "runs")
    key = "the-same-approval"
    won: list[bool] = []
    barrier = threading.Barrier(8)

    def race() -> None:
        barrier.wait()
        won.append(store.claim(key, "run-1"))

    threads = [threading.Thread(target=race) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(won) == 1, f"{sum(won)} callers were told they had the claim"
    assert store.already_handled(key)


def test_a_publish_that_fails_can_be_retried(tmp_path):
    """Marking before publishing turned a bus outage into a lost event.

    The key was on file, nothing was on the bus, and no retry could ever send
    it. One lost event is worse than two duplicates on a set.
    """
    from lasttake.adapters.local.infrastructure import LocalArtifactStore, LocalRunStore
    from lasttake.agents.runtime import WrapRun
    from lasttake.domain.events import EventType

    class BrokenBus:
        def __init__(self) -> None:
            self.attempts = 0
            self.working = False

        def publish(self, event):
            self.attempts += 1
            if not self.working:
                return Receipt(accepted=False, reference=event.event_id, detail="entry explicitly rejected")
            return Receipt(accepted=True, reference=event.event_id, detail="published")

    bus = BrokenBus()
    store = LocalRunStore(tmp_path / "runs")
    run = WrapRun(
        run_id="demo-retryable",
        correlation_id="demo-retryable",
        package=load_package(CORPUS),
        bus=bus,
        artifacts=LocalArtifactStore(tmp_path / "artifacts"),
        runs=store,
        interpreter=OfflineInterpreter(),
    )

    refused = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    assert refused.outcome == "rejected" and not refused.accepted
    assert bus.attempts == 1

    bus.working = True
    receipt = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    assert receipt.accepted and bus.attempts == 2
    assert "already handled" not in receipt.detail, "the failure was never released"

    again = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    assert again.to_dict() == receipt.to_dict(), "return the saved bus receipt, not a fabricated one"
    assert bus.attempts == 2, "a successful publish was repeated"
