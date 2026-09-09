"""The scene package: everything a wrap decision has to reconcile.

On a real set these live in seven different applications owned by five
different departments. Here they are seven JSON documents, each content
addressed, so that a finding can name the exact bytes it was derived from.

The package is immutable once registered. A new take or a new release record
produces a new *revision*, and findings written against an older revision are
stale by definition. The gate rejects stale findings rather than reusing them,
because a reused finding is the one way a fixed problem can stay fixed on the
screen while being broken on the set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .sealing import digest_of, sha256_bytes


@dataclass(frozen=True)
class Artifact:
    """One immutable document, with the digest of the bytes as read."""

    artifact_id: str
    kind: str
    sha256: str
    payload: dict

    @staticmethod
    def from_bytes(artifact_id: str, kind: str, raw: bytes) -> "Artifact":
        return Artifact(
            artifact_id=artifact_id,
            kind=kind,
            sha256=sha256_bytes(raw),
            payload=json.loads(raw.decode("utf-8")),
        )

    @staticmethod
    def from_file(path: Path, kind: str) -> "Artifact":
        raw = path.read_bytes()
        return Artifact.from_bytes(path.stem, kind, raw)


@dataclass(frozen=True)
class Beat:
    """A required story beat from the current script revision.

    ``required`` distinguishes a beat the scene cannot be delivered without
    from one that is nice to have. Only required beats gate a wrap.
    """

    beat_id: str
    page: str
    line: int
    slug: str
    description: str
    required: bool
    characters: list[str] = field(default_factory=list)
    continuity_ref: Optional[str] = None


@dataclass(frozen=True)
class Shot:
    shot_id: str
    setup: str
    lens_mm: int
    beat_ids: list[str]
    description: str


@dataclass(frozen=True)
class Take:
    """One captured take, as the camera and sound departments recorded it."""

    take_id: str
    shot_id: str
    beat_ids: list[str]
    slate: str
    camera_roll: str
    sound_roll: str
    timecode_in: str
    timecode_out: str
    lens_mm: int
    media_id: str
    preferred: bool
    usable: bool
    note: str
    visible_people: list[str] = field(default_factory=list)
    visible_assets: list[str] = field(default_factory=list)
    captured_at: str = ""


@dataclass(frozen=True)
class CameraReportRow:
    """The camera department's own record of what was written to the card.

    Where this disagrees with the take's sidecar, the disagreement is the
    finding. This module does not decide which one is right; a DIT does.
    """

    take_id: str
    media_id: str
    lens_mm: int
    camera_roll: str


@dataclass(frozen=True)
class ContinuityReference:
    """The established state of a thing that must not change mid-scene."""

    ref_id: str
    beat_ids: list[str]
    subject: str
    established_state: str


@dataclass(frozen=True)
class RightsRecord:
    """A release or licence covering one person or one visible asset."""

    record_id: str
    subject_id: str
    subject_kind: str
    document_type: str
    scope: str
    territory: str
    expires_on: Optional[str]
    status: str


@dataclass
class ScenePackage:
    """The whole reconciliation surface for one scene, at one revision."""

    production_id: str
    scene_id: str
    revision: str
    beats: list[Beat]
    shots: list[Shot]
    takes: list[Take]
    camera_report: list[CameraReportRow]
    continuity_refs: list[ContinuityReference]
    rights_records: list[RightsRecord]
    script_notes: dict[str, str]
    artifacts: dict[str, Artifact]

    # -- lookups the checks need, kept here so no check re-implements them ---

    @property
    def required_beats(self) -> list[Beat]:
        return [b for b in self.beats if b.required]

    def takes_for_beat(self, beat_id: str) -> list[Take]:
        return [t for t in self.takes if beat_id in t.beat_ids]

    def shots_for_beat(self, beat_id: str) -> list[Shot]:
        return [s for s in self.shots if beat_id in s.beat_ids]

    def take(self, take_id: str) -> Optional[Take]:
        return next((t for t in self.takes if t.take_id == take_id), None)

    def beat(self, beat_id: str) -> Optional[Beat]:
        return next((b for b in self.beats if b.beat_id == beat_id), None)

    def camera_row(self, take_id: str) -> Optional[CameraReportRow]:
        return next((r for r in self.camera_report if r.take_id == take_id), None)

    def rights_for(self, subject_id: str) -> list[RightsRecord]:
        return [r for r in self.rights_records if r.subject_id == subject_id]

    def subjects_in_scene(self) -> list[tuple[str, str]]:
        """Every person and visible asset that appears in any usable take.

        Returned sorted so a rerun produces the same order, because an
        unstable order makes two identical runs look different in a diff.
        """
        seen: set[tuple[str, str]] = set()
        for take in self.takes:
            if not take.usable:
                continue
            for person in take.visible_people:
                seen.add((person, "person"))
            for asset in take.visible_assets:
                seen.add((asset, "asset"))
        return sorted(seen)

    def artifact_source(self, artifact_id: str) -> Artifact:
        return self.artifacts[artifact_id]

    def revision_digest(self) -> str:
        """One digest covering every artifact in the package.

        This is what makes a finding stale. Add a take, and this changes, and
        every finding written against the old value is no longer current.
        """
        return digest_of(
            {aid: art.sha256 for aid, art in sorted(self.artifacts.items())}
        )


def _as_list(payload: dict, key: str) -> Iterable[dict]:
    return payload.get(key, [])


def load_package(directory: Path) -> ScenePackage:
    """Read a scene package from a directory of JSON documents."""
    kinds = {
        "script_revision": "script",
        "shot_plan": "plan",
        "takes": "takes",
        "camera_report": "report",
        "sound_report": "report",
        "continuity_refs": "reference",
        "rights_ledger": "ledger",
        "script_notes": "notes",
    }
    artifacts: dict[str, Artifact] = {}
    for name, kind in kinds.items():
        path = directory / f"{name}.json"
        if path.exists():
            artifacts[name] = Artifact.from_file(path, kind)

    script = artifacts["script_revision"].payload
    plan = artifacts["shot_plan"].payload
    takes_doc = artifacts["takes"].payload
    report = artifacts["camera_report"].payload
    refs = artifacts["continuity_refs"].payload
    ledger = artifacts["rights_ledger"].payload
    notes = artifacts["script_notes"].payload

    return ScenePackage(
        production_id=script["production_id"],
        scene_id=script["scene_id"],
        revision=script["revision"],
        beats=[Beat(**b) for b in _as_list(script, "beats")],
        shots=[Shot(**s) for s in _as_list(plan, "shots")],
        takes=[Take(**t) for t in _as_list(takes_doc, "takes")],
        camera_report=[CameraReportRow(**r) for r in _as_list(report, "rows")],
        continuity_refs=[ContinuityReference(**c) for c in _as_list(refs, "references")],
        rights_records=[RightsRecord(**r) for r in _as_list(ledger, "records")],
        script_notes=notes.get("notes", {}),
        artifacts=artifacts,
    )


def with_extra_take(package: ScenePackage, take: Take, row: Optional[CameraReportRow] = None) -> ScenePackage:
    """Return a new package revision that includes one late take.

    Used by the targeted rerun path. It builds a *new* package rather than
    mutating the old one, so the previous revision, and every finding written
    against it, stays exactly as it was for the audit.
    """
    takes_doc = dict(package.artifacts["takes"].payload)
    takes_doc["takes"] = takes_doc["takes"] + [take.__dict__]
    report_doc = dict(package.artifacts["camera_report"].payload)
    if row is not None:
        report_doc["rows"] = report_doc["rows"] + [row.__dict__]

    artifacts = dict(package.artifacts)
    artifacts["takes"] = Artifact.from_bytes(
        "takes", "takes", json.dumps(takes_doc, sort_keys=True).encode("utf-8")
    )
    if row is not None:
        artifacts["camera_report"] = Artifact.from_bytes(
            "camera_report", "report", json.dumps(report_doc, sort_keys=True).encode("utf-8")
        )
    return ScenePackage(
        production_id=package.production_id,
        scene_id=package.scene_id,
        revision=package.revision + "+late",
        beats=list(package.beats),
        shots=list(package.shots),
        takes=list(package.takes) + [take],
        camera_report=list(package.camera_report) + ([row] if row is not None else []),
        continuity_refs=list(package.continuity_refs),
        rights_records=list(package.rights_records),
        script_notes=dict(package.script_notes),
        artifacts=artifacts,
    )


def with_rights_record(package: ScenePackage, record: RightsRecord) -> ScenePackage:
    """Return a new package revision that includes one supplied release."""
    ledger_doc = dict(package.artifacts["rights_ledger"].payload)
    ledger_doc["records"] = ledger_doc["records"] + [record.__dict__]
    artifacts = dict(package.artifacts)
    artifacts["rights_ledger"] = Artifact.from_bytes(
        "rights_ledger", "ledger", json.dumps(ledger_doc, sort_keys=True).encode("utf-8")
    )
    return ScenePackage(
        production_id=package.production_id,
        scene_id=package.scene_id,
        revision=package.revision + "+rights",
        beats=list(package.beats),
        shots=list(package.shots),
        takes=list(package.takes),
        camera_report=list(package.camera_report),
        continuity_refs=list(package.continuity_refs),
        rights_records=list(package.rights_records) + [record],
        script_notes=dict(package.script_notes),
        artifacts=artifacts,
    )
