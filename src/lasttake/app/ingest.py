"""Amendments to a scene package, and the documents people supply to make them.

A run starts from the corpus on disk. Everything that happens to it afterwards,
a take that was captured, a release that was signed, is an amendment: a document
recorded once, replayed onto the base package deterministically, and never
mutated. That determinism is what lets a finding written in one request stay
admissible in the next, because the digests it cites still match.

This lives apart from the HTTP layer because it is not about HTTP. The route in
`handler.py` validates a body, calls `build`, and reports; everything about what
a package amendment *is* belongs here.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..domain import policy
from ..checks import continuity as continuity_check
from ..checks import coverage as coverage_check
from ..checks import metadata as metadata_check
from ..checks import rights as rights_check
from ..domain.events import EventType, affected_by
from ..domain.sealing import SEAL_KEY
from ..domain.package import CameraReportRow, RightsRecord, Take, with_extra_take, with_rights_record


# A take that was captured and a release that was signed are facts about the
# world, and the next request has to see them. They were being applied in
# memory and thrown away when the Lambda returned, so `POST /api/late-take`
# reported a beat covered and the very next `POST /api/state` reported it
# uncovered again, correctly: the take was not in the package any more, so the
# finding that cited it was stale and the gate withdrew it. The staleness rule
# was right. The take should have been there.
#
# Each amendment is written once, under its own key, and read back by probing
# the sequence. The artifact store has no update, no delete and no list, and
# that is the contract, not an inconvenience to work around.

AMENDMENT_LIMIT = 200


def _amendment_key(run_id: str, index: int) -> str:
    return f"amendments/{run_id.replace(':', '_')}/{index:04d}.json"


def load_amendments(artifacts, run_id: str) -> list[dict]:
    out: list[dict] = []
    for index in range(AMENDMENT_LIMIT):
        key = _amendment_key(run_id, index)
        if not artifacts.exists(key):
            break
        out.append(json.loads(artifacts.get(key).decode("utf-8")))
    return out


def record_amendment(artifacts, run_id: str, amendment: dict) -> None:
    for index in range(AMENDMENT_LIMIT):
        key = _amendment_key(run_id, index)
        if not artifacts.exists(key):
            artifacts.put(key, json.dumps(amendment, sort_keys=True).encode("utf-8"))
            return
    raise RuntimeError(f"{run_id} has {AMENDMENT_LIMIT} amendments; refusing to add more")


def apply_amendments(package, amendments: list[dict]):
    """Replay amendments onto the base package, in the order they arrived.

    Deterministic: the same amendments produce the same package and therefore
    the same digests, which is what lets a finding written in one request stay
    admissible in the next.
    """
    for amendment in amendments:
        if amendment["kind"] == "take":
            package = with_extra_take(
                package,
                Take(**amendment["take"]),
                CameraReportRow(**amendment["camera_report_row"]),
            )
        elif amendment["kind"] == "rights_record":
            package = with_rights_record(package, RightsRecord(**amendment["record"]))
        else:
            raise ValueError(f"unknown amendment kind {amendment['kind']!r}")
    return package



# The demo had two buttons that fabricated a take and a release. They showed the
# targeted rerun honestly enough, but a visitor could not put their own scene
# through the pipeline, which made the whole thing a fixture with a play button
# rather than a product. This takes a document.

INGEST_SHAPES = {
    "take": {
        "required": [
            "take_id", "shot_id", "beat_ids", "slate", "camera_roll", "sound_roll",
            "timecode_in", "timecode_out", "lens_mm", "media_id", "preferred", "usable",
        ],
        "optional": ["note", "visible_people", "visible_assets", "captured_at",
                     "camera_report_row"],
    },
    "rights_record": {
        "required": [
            "record_id", "subject_id", "subject_kind", "document_type", "scope",
            "territory", "status",
        ],
        "optional": ["expires_on"],
    },
}


#: Identifiers a caller supplies that reach a finding, a message or a package.
#: `run_id` has been validated since the first commit; these two were not, so a
#: crafted subject came back inside a human-readable message on the page. It was
#: escaped and it was not a clearance the product gave, but it read like one, and
#: an identifier is an identifier.
# 128, because a real Strands interrupt id is 83 characters and looks like
# `v1:tool_call:offline-5-request_pickup_approval:<uuid>`. The first cap here was
# 64 and the test suite caught it in one run, which is the argument for having
# the identifier the product actually uses in a test rather than a plausible one.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def bad_identifier(name: str, value: object) -> Optional[str]:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        return (
            f"{name} must be 1 to 128 characters of letters, digits and the "
            "separators . : _ and -, starting with a letter or a digit"
        )
    return None


def shape_error(kind: str, document: object) -> Optional[dict]:
    """Say what is wrong with a supplied document, in the shape it should be."""
    if kind not in INGEST_SHAPES:
        return {
            "error": f"unknown kind {kind!r}",
            "accepted_kinds": sorted(INGEST_SHAPES),
        }
    if not isinstance(document, dict):
        return {"error": "document must be a JSON object", "expected": INGEST_SHAPES[kind]}
    shape = INGEST_SHAPES[kind]
    missing = [field for field in shape["required"] if field not in document]
    unknown = [
        field
        for field in document
        if field not in shape["required"] and field not in shape["optional"]
    ]
    if missing or unknown:
        return {
            "error": "the document does not match the shape for this kind",
            "missing": missing,
            "unexpected": unknown,
            "expected": shape,
        }
    for field in ("take_id", "record_id", "subject_id", "shot_id"):
        if field in document:
            problem = bad_identifier(field, document[field])
            if problem:
                return {"error": problem}
    return None




def perform_ingest(run, kind, document, rebuild, base_package, state_of) -> dict:
    """Record the amendment, replay it, rerun what it touches, report what fell.

    `rebuild` and `base_package` are passed in rather than imported so this
    module stays out of the HTTP layer's import graph. `state_of` shapes the
    response, which is the one thing here that is genuinely the caller's.
    """
    before = {
        f["finding_id"]: f.get(SEAL_KEY) for f in run.load_findings()
    }
    decisions_before = run.load_decisions()

    try:
        if kind == "take":
            payload = {k: v for k, v in document.items() if k != "camera_report_row"}
            payload.setdefault("note", "")
            payload.setdefault("visible_people", [])
            payload.setdefault("visible_assets", [])
            payload.setdefault("captured_at", "")
            take = Take(**payload)
            row_doc = document.get("camera_report_row") or {
                "take_id": take.take_id,
                "media_id": take.media_id,
                "lens_mm": take.lens_mm,
                "camera_roll": take.camera_roll,
            }
            row = CameraReportRow(**row_doc)
            amendment = {"kind": "take", "take": take.__dict__,
                         "camera_report_row": row.__dict__}
            event_type, event_payload = EventType.TAKE_CAPTURED, {
                "take_id": take.take_id, "beat_ids": list(take.beat_ids)}
        else:
            record = RightsRecord(**{**{"expires_on": None}, **document})
            amendment = {"kind": "rights_record", "record": record.__dict__}
            event_type, event_payload = EventType.RIGHTS_RECORD_UPDATED, {
                "subject_id": record.subject_id, "record_id": record.record_id}
    except TypeError as exc:
        raise ValueError(f"the document is not a valid {kind}: {exc}") from exc

    record_amendment(run.artifacts, run.run_id, amendment)
    package = apply_amendments(base_package(), load_amendments(run.artifacts, run.run_id))
    new_run = rebuild(run.run_id, package)
    event = new_run.build_event(event_type, event_payload)
    new_run.bus.publish(event)

    affected = list(affected_by(event))
    fresh = []
    if "coverage" in affected:
        fresh += coverage_check.run(package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
    if "continuity" in affected:
        fresh += continuity_check.run(package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
    if "metadata" in affected:
        fresh += metadata_check.run(package, new_run.run_id, policy.POLICY_VERSION)
    if "rights" in affected:
        fresh += rights_check.run(package, new_run.run_id, policy.POLICY_VERSION)
    new_run.store_findings(fresh)

    # Which approvals no longer apply, because the reading they were about has
    # been replaced. Derived by comparing digests, never asserted.
    after = {f["finding_id"]: f.get(SEAL_KEY) for f in new_run.load_findings()}
    withdrawn = [
        {
            "decision_id": d["decision_id"],
            "finding_id": d["finding_id"],
            "actor": d.get("actor"),
            "role": d.get("role"),
            "why": "the finding it was taken about has been read again since",
        }
        for d in decisions_before
        if d.get("finding_sha256")
        and d["finding_id"] in after
        and after[d["finding_id"]] != d["finding_sha256"]
    ]

    state = state_of(new_run)
    state["affected_checks"] = affected
    state["ingested"] = {"kind": kind, "amendments": len(load_amendments(run.artifacts, run.run_id))}
    state["withdrawn_decisions"] = withdrawn
    state["message"] = (
        f"Ingested one {kind.replace('_', ' ')}. {len(affected)} check(s) reran, because "
        f"that is which artifact digests moved, and {len(before)} finding(s) were on file "
        f"before. {len(withdrawn)} human decision(s) no longer apply."
    )
    return state


