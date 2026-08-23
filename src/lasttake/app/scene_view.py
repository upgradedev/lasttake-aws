"""The scene as a script supervisor holds it: the lined script.

This is the surface a supervisor recognises before anyone explains the product
to them. Beats down the page in script order, and beside each one the takes that
were actually shot against it. It carries no judgement: no status, no verdict,
no colour. The findings arrive separately and land on top of it.

It reads only the package, so it needs no model and no SDK, and it returns while
the checkpoint behind it is still working. That ordering is the point. A visitor
sees a real scene immediately and watches the verdict fill in, rather than
looking at an empty page with a button on it.
"""

from __future__ import annotations

from ..domain import policy
from ..domain.package import ScenePackage


def scene_view(package: ScenePackage) -> dict:
    by_beat: dict[str, list[dict]] = {}
    for take in package.takes:
        row = {
            "take_id": take.take_id,
            "slate": take.slate,
            "shot_id": take.shot_id,
            "lens_mm": take.lens_mm,
            "camera_roll": take.camera_roll,
            "sound_roll": take.sound_roll,
            "timecode_in": take.timecode_in,
            "media_id": take.media_id,
            "preferred": take.preferred,
            "usable": take.usable,
            "note": take.note or package.script_notes.get(take.take_id, ""),
            "visible_people": list(take.visible_people),
            "visible_assets": list(take.visible_assets),
        }
        for beat_id in take.beat_ids:
            by_beat.setdefault(beat_id, []).append(row)

    planned = {
        beat_id: shot.shot_id for shot in package.shots for beat_id in shot.beat_ids
    }
    released = {r.subject_id for r in package.rights_records if r.status == "executed"}
    subjects = sorted(
        {p for take in package.takes for p in take.visible_people}
        | {a for take in package.takes for a in take.visible_assets}
    )
    # A finding names what it is about by requirement id, and that is a beat for
    # coverage, a continuity reference for continuity, a take for metadata and a
    # subject for rights. The interface has to say "page 44, line 10" for all
    # four, so the package resolves each id to a place a person can turn to.
    beat_at = {
        b.beat_id: f"Page {b.page}, line {b.line} · {b.slug}" for b in package.beats
    }
    locations: dict[str, str] = dict(beat_at)
    for ref in package.continuity_refs:
        first = next((beat_at[b] for b in ref.beat_ids if b in beat_at), "")
        locations[ref.ref_id] = f"{ref.subject} · {first}" if first else ref.subject
    for take in package.takes:
        first = next((beat_at[b] for b in take.beat_ids if b in beat_at), "")
        locations[take.take_id] = f"Slate {take.slate} · {first}" if first else f"Slate {take.slate}"
    for subject in subjects:
        slates = [t.slate for t in package.takes
                  if subject in t.visible_people or subject in t.visible_assets]
        if slates:
            shown = ", ".join(slates[:4]) + ("…" if len(slates) > 4 else "")
            noun = "take" if len(slates) == 1 else "takes"
            locations[subject] = f"{subject}, visible on {len(slates)} {noun}: {shown}"

    script = package.artifacts["script_revision"].payload
    plan = package.artifacts["shot_plan"].payload

    return {
        "production_id": package.production_id,
        "scene_id": package.scene_id,
        "scene_heading": script.get("scene_heading", ""),
        "revision": package.revision,
        "shot_plan_revision": plan.get("prepared_against_revision", ""),
        "take_count": len(package.takes),
        "required_beats": sum(1 for b in package.beats if b.required),
        "beats": [
            {
                "beat_id": b.beat_id,
                "page": b.page,
                "line": b.line,
                "slug": b.slug,
                "description": b.description,
                "characters": list(b.characters),
                "required": b.required,
                "continuity_ref": b.continuity_ref,
                "planned_shot": planned.get(b.beat_id),
                "takes": by_beat.get(b.beat_id, []),
            }
            for b in package.beats
        ],
        "subjects": [{"subject_id": s, "released": s in released} for s in subjects],
        "locations": locations,
        # Who may act is read out of the policy tables, not written into the
        # page. When the interface declines to offer a control it is because the
        # policy withholds it, and the same table is what the gate enforces.
        "authority": {
            check.value: {
                "may_confirm": sorted(r.value for r in policy.AUTHORITY.get(check, set())),
                "may_accept": sorted(
                    r.value for r in policy.MAY_ACCEPT_EXCEPTION.get(check, set())
                ),
            }
            for check in policy.AUTHORITY
        },
        "policy_version": policy.POLICY_VERSION,
        "disclaimer": script.get("disclaimer", ""),
    }
