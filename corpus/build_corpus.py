"""Build the synthetic shoot day.

Everything here is invented. THE LAST FERRY is not a production, nobody named
below exists, and no frame of footage is referenced or included. The takes
carry real-shaped slate, lens, sound roll, timecode and media identifiers
because reconciliation is the product and reconciliation against toy data
proves nothing, but the data itself is fiction and says so on its face.

The day is messy on purpose. Six things are wrong with it, planted so that
each one exercises a different part of the pipeline:

1. B-17 was added in the Blue revision and never made the shot list, so no
   camera ever rolled on it. This is the coverage gap.
2. Shot 42C plans for B-99, a beat cut in the Blue revision. An orphan.
3. T-031 and T-032 are both flagged preferred and the mug does not match
   between them. This is the continuity conflict that constrains the edit.
4. T-018's media identifier does not match the camera report row. This is the
   DIT's problem, and note that B-11 is still covered, by T-019.
5. BG-07 is visible in T-014 and has no release record.
6. T-041 does not exist yet. It arrives after the checkpoint, to prove the
   rerun is targeted.

Run with no arguments to regenerate the JSON documents in this directory. It
is deterministic: no clock, no randomness, so the digests are stable and a
diff means something changed.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

PRODUCTION_ID = "PROD-LASTFERRY-2026"
SCENE_ID = "SC-042"
REVISION = "Blue-2026-08-19"

DISCLAIMER = (
    "SYNTHETIC. THE LAST FERRY is a fictional production. Every person, place, "
    "identifier and record below is invented for demonstration. No real "
    "production data and no real footage is referenced."
)

# --- the scene, as the Blue revision has it -------------------------------

BEAT_SPECS = [
    ("B-01", "41", 3, "MARA reaches the empty ticket window", ["MARA"]),
    ("B-02", "41", 8, "She reads the cancelled sailings board", ["MARA"]),
    ("B-03", "41", 14, "Wind takes the timetable from her hand", ["MARA"]),
    ("B-04", "41", 19, "She catches it against the railing", ["MARA"]),
    ("B-05", "42", 2, "MARA turns her collar up", ["MARA"]),
    ("B-06", "42", 6, "She finds the torn pocket is empty", ["MARA"]),
    ("B-07", "42", 11, "DELPHINE watches from the cafe door", ["DELPHINE"]),
    ("B-08", "42", 16, "DELPHINE steps out into the rain", ["DELPHINE"]),
    ("B-09", "42", 21, "A deckhand passes between them", ["MARA", "DELPHINE"]),
    ("B-10", "43", 1, "DELPHINE offers the enamel mug", ["DELPHINE"]),
    ("B-11", "43", 5, "MARA refuses without looking up", ["MARA"]),
    ("B-12", "43", 9, "DELPHINE sets the mug on the bollard", ["DELPHINE"]),
    ("B-13", "43", 13, "Foghorn. Both look to the water", ["MARA", "DELPHINE"]),
    ("B-14", "43", 18, "MARA asks how long she has known", ["MARA"]),
    ("B-15", "44", 2, "DELPHINE does not answer", ["DELPHINE"]),
    ("B-16", "44", 6, "MARA repeats the question", ["MARA"]),
    ("B-17", "44", 10, "DELPHINE's reaction, held, before she speaks", ["DELPHINE"]),
    ("B-18", "44", 15, "DELPHINE says the ferry stopped running in March", ["DELPHINE"]),
    ("B-19", "44", 20, "MARA sits down on the wet bench", ["MARA"]),
    ("B-20", "45", 3, "She takes the mug after all", ["MARA"]),
    ("B-21", "45", 7, "DELPHINE sits at the far end of the bench", ["DELPHINE"]),
    ("B-22", "45", 12, "MARA holds the mug without drinking", ["MARA"]),
    ("B-23", "45", 17, "MARA drinks and puts the mug down", ["MARA"]),
    ("B-24", "46", 2, "DELPHINE says she waited every Thursday", ["DELPHINE"]),
    ("B-25", "46", 7, "MARA counts the Thursdays", ["MARA"]),
    ("B-26", "46", 12, "The harbour lights come on behind them", ["MARA", "DELPHINE"]),
    ("B-27", "46", 17, "DELPHINE stands", ["DELPHINE"]),
    ("B-28", "47", 2, "She checks her father's watch", ["DELPHINE"]),
    ("B-29", "47", 6, "MARA notices the watch", ["MARA"]),
    ("B-30", "47", 11, "DELPHINE walks to the end of the pier", ["DELPHINE"]),
    ("B-31", "47", 16, "MARA does not follow", ["MARA"]),
    ("B-32", "48", 2, "The last light goes out in the cafe", []),
    ("B-33", "48", 6, "MARA picks up the empty mug", ["MARA"]),
    ("B-34", "48", 11, "She carries it back towards the cafe", ["MARA"]),
]

#: Not required. Present so that "required beats" is a real filter over a real
#: script rather than a synonym for "every row in the file".
OPTIONAL_BEAT_SPECS = [
    ("B-35", "48", 15, "Insert: the cancelled sailings board, closer", []),
    ("B-36", "48", 18, "Insert: the mug left on the bollard", []),
]

CONTINUITY = [
    {
        "ref_id": "CR-01",
        "beat_ids": ["B-20", "B-22", "B-23"],
        "subject": "enamel mug, contents",
        "established_state": "half full, no steam, handle turned to camera left",
    },
    {
        "ref_id": "CR-02",
        "beat_ids": ["B-05", "B-06"],
        "subject": "MARA raincoat",
        "established_state": "collar up, left pocket torn at the seam",
    },
    {
        "ref_id": "CR-03",
        "beat_ids": ["B-28", "B-29"],
        "subject": "DELPHINE wristwatch",
        "established_state": "worn on the right wrist, face turned inward",
    },
]

#: Notes on the preferred take of every beat a continuity reference spans.
#: B-20, B-22 and B-23 belong to CR-01, the mug, and B-23's pair is overwritten
#: below with the two notes that disagree. Everything else matches its
#: established state, so exactly one conflict survives.
CONTINUITY_NOTES = {
    "B-05": "Collar up, left pocket torn at the seam.",
    "B-06": "Collar up, torn pocket, hand goes straight through.",
    "B-20": "Mug half full, no steam, handle to camera left.",
    "B-22": "Mug half full, handle still camera left.",
    "B-28": "Watch on the right wrist, face turned inward.",
    "B-29": "Watch on the right wrist, inward as established.",
}

RIGHTS = [
    ("REL-001", "MARA", "person", "performer release", "all media", "worldwide", None, "executed"),
    ("REL-002", "DELPHINE", "person", "performer release", "all media", "worldwide", None, "executed"),
    ("REL-003", "BG-01", "person", "background release", "all media", "worldwide", None, "executed"),
    ("REL-004", "BG-02", "person", "background release", "all media", "worldwide", None, "executed"),
    ("LIC-001", "PROP-ENAMEL-MUG", "asset", "property release", "all media", "worldwide", None, "executed"),
    ("LIC-002", "SIGN-HARBOUR-TIMETABLE", "asset", "location signage licence", "all media", "worldwide", "2031-01-01", "executed"),
    # BG-07 is absent on purpose. That absence is the finding.
]


#: One letter per camera setup, numbered within that setup. I and O are skipped
#: because on a slate they read as 1 and 0. A slate identifies exactly one take,
#: so a letter that cycled would put the same slate on takes shot hours apart,
#: which is the first thing a script supervisor would catch.
SLATE_LETTERS = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in ("I", "O")]


def _slate(setup_letter: str, take_number: int) -> str:
    return f"42{setup_letter}/{take_number}"


def _timecode(seconds: int) -> str:
    hh = 18 + seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:00"


def build_takes() -> tuple[list[dict], list[dict], dict[str, str]]:
    """Forty takes, the camera report rows, and where the problems were planted.

    Take numbers are assigned by walking the scene, so they are not knowable
    in advance. The planted problems are therefore located by *beat* and the
    resulting take identifiers are returned, rather than written down here and
    left to drift the first time the scene changes length.
    """
    takes: list[dict] = []
    rows: list[dict] = []
    shot_for_beat = {
        beat_id: shot["shot_id"]
        for shot in build_shots()
        for beat_id in shot["beat_ids"]
    }

    # Beats that get a second take. B-11 is doubled deliberately: its first
    # take carries the media identity mismatch, and its second is clean, so the
    # beat stays covered while the DIT still gets a real finding.
    doubled = {"B-03", "B-05", "B-11", "B-13", "B-23", "B-26", "B-31"}

    setup_order: list[str] = []
    setup_takes: dict[str, int] = {}

    take_number = 1
    clock = 0
    for index, (beat_id, _page, _line, _slug, characters) in enumerate(BEAT_SPECS):
        if beat_id == "B-17":
            continue  # never shot. This is the whole point of the demo.
        repeats = 2 if beat_id in doubled else 1
        setup = shot_for_beat.get(beat_id, "S-42-UNPLANNED")
        if setup not in setup_order:
            setup_order.append(setup)
        letter = SLATE_LETTERS[setup_order.index(setup)]
        for repeat in range(repeats):
            take_id = f"T-{take_number:03d}"
            setup_takes[setup] = setup_takes.get(setup, 0) + 1
            roll_index = index // 8
            camera_roll = f"A{roll_index + 1:03d}"
            media_id = f"{camera_roll}R2{chr(ord('A') + roll_index)}{take_number:02d}"
            people = list(characters)
            assets: list[str] = []
            if beat_id == "B-09":
                # The deckhand. No release record exists for BG-07.
                people = people + ["BG-07"]
            if beat_id in {"B-07", "B-08"}:
                people = people + ["BG-01"]
            if beat_id in {"B-26"}:
                people = people + ["BG-02"]
            if beat_id in {"B-10", "B-12", "B-20", "B-22", "B-23", "B-33"}:
                assets = assets + ["PROP-ENAMEL-MUG"]
            if beat_id in {"B-02", "B-03"}:
                assets = assets + ["SIGN-HARBOUR-TIMETABLE"]

            preferred = repeat == 0
            # A supervisor writes a note on any take that carries a continuity
            # reference. Where there is no note the check returns "unknown"
            # rather than reading silence as agreement, which is correct but
            # would bury the one conflict this corpus is built to show.
            note = CONTINUITY_NOTES.get(beat_id, "") if preferred else ""
            takes.append(
                {
                    "take_id": take_id,
                    "shot_id": setup,
                    "beat_ids": [beat_id],
                    "slate": _slate(letter, setup_takes[setup]),
                    "camera_roll": camera_roll,
                    "sound_roll": f"SR{roll_index + 1:02d}",
                    "timecode_in": _timecode(clock),
                    "timecode_out": _timecode(clock + 47),
                    "lens_mm": [27, 35, 50, 75][index % 4],
                    "media_id": media_id,
                    "preferred": preferred,
                    "usable": True,
                    "note": note,
                    "visible_people": people,
                    "visible_assets": assets,
                    "captured_at": f"2026-08-19T{18 + clock // 3600:02d}:{(clock % 3600) // 60:02d}:00Z",
                }
            )
            rows.append(
                {
                    "take_id": take_id,
                    "media_id": media_id,
                    "lens_mm": [27, 35, 50, 75][index % 4],
                    "camera_roll": camera_roll,
                }
            )
            take_number += 1
            clock += 213

    def takes_of(beat_id: str) -> list[dict]:
        return [t for t in takes if beat_id in t["beat_ids"]]

    # Planted problem 3: both takes of B-23 flagged preferred, and the mug does
    # not match between them. Neither can be dropped without a human choosing.
    mug_a, mug_b = takes_of("B-23")
    mug_a["preferred"] = True
    mug_b["preferred"] = True
    mug_a["note"] = "Circled. Mug half full, handle camera left. Good on the sit."
    mug_b["note"] = "Also circled by the director. Mug empty, handle camera right."

    # Planted problem 4: the card the camera department wrote down is not the
    # card in the sidecar. One character apart, which is how it actually happens.
    # It lands on the FIRST take of B-11, which has a second, clean take.
    bad_media = takes_of("B-11")[0]
    bad_media["note"] = "Camera flagged a card swap mid-roll. Check the report."
    for row in rows:
        if row["take_id"] == bad_media["take_id"]:
            row["media_id"] = row["media_id"][:-1] + "X"

    # Planted problem 5: the deckhand, visible and unreleased.
    deckhand = takes_of("B-09")[0]
    deckhand["note"] = "Deckhand walked through frame. Not on the background list."

    planted = {
        "continuity_conflict_takes": f"{mug_a['take_id']} and {mug_b['take_id']}",
        "media_mismatch_take": bad_media["take_id"],
        "unreleased_subject_take": deckhand["take_id"],
    }
    return takes, rows, planted


def build_shots() -> list[dict]:
    """Setups covering runs of consecutive beats, the way a plan is built.

    Four beats to a setup, which is why B-17 going missing is easy to miss on
    the day: the setup around it was shot, so the board looks complete.
    """
    shots: list[dict] = []
    planned = [
        (index, spec)
        for index, spec in enumerate(BEAT_SPECS)
        if spec[0] != "B-17"  # planted problem 1: added in Blue, never made the plan
    ]
    for group_index in range(0, len(planned), 4):
        group = planned[group_index : group_index + 4]
        first_slug = group[0][1][3]
        last_slug = group[-1][1][3]
        shots.append(
            {
                "shot_id": f"S-42-{group_index // 4 + 1:02d}",
                "setup": f"Setup {group_index // 4 + 1}",
                "lens_mm": [27, 35, 50, 75][(group_index // 4) % 4],
                "beat_ids": [spec[0] for _i, spec in group],
                "description": f"{first_slug} through {last_slug}",
            }
        )
    # Planted problem 2: a shot planned for a beat the Blue revision cut.
    shots.append(
        {
            "shot_id": "S-42C-ORPHAN",
            "setup": "Setup 7",
            "lens_mm": 100,
            "beat_ids": ["B-99"],
            "description": "MARA's phone call to the mainland. Cut in Blue.",
        }
    )
    return shots


def write(name: str, payload: dict) -> None:
    path = HERE / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path.name}")


def main() -> None:
    takes, rows, planted = build_takes()
    beats = [
        {
            "beat_id": beat_id,
            "page": page,
            "line": line,
            "slug": slug,
            "description": slug,
            "required": True,
            "characters": chars,
            "continuity_ref": next(
                (c["ref_id"] for c in CONTINUITY if beat_id in c["beat_ids"]), None
            ),
        }
        for beat_id, page, line, slug, chars in BEAT_SPECS
    ] + [
        {
            "beat_id": beat_id,
            "page": page,
            "line": line,
            "slug": slug,
            "description": slug,
            "required": False,
            "characters": chars,
            "continuity_ref": None,
        }
        for beat_id, page, line, slug, chars in OPTIONAL_BEAT_SPECS
    ]

    write(
        "script_revision",
        {
            "disclaimer": DISCLAIMER,
            "production_id": PRODUCTION_ID,
            "scene_id": SCENE_ID,
            "revision": REVISION,
            "revision_dated": "2026-08-19",
            "scene_heading": "EXT. HARBOUR TICKET OFFICE - DUSK",
            "beats": beats,
        },
    )
    write(
        "shot_plan",
        {
            "disclaimer": DISCLAIMER,
            "plan_id": "PLAN-SC042-WHITE",
            "prepared_against_revision": "White-2026-08-11",
            "shots": build_shots(),
        },
    )
    write("takes", {"disclaimer": DISCLAIMER, "takes": takes})
    write(
        "camera_report",
        {"disclaimer": DISCLAIMER, "report_id": "CR-SC042-A", "rows": rows},
    )
    write(
        "sound_report",
        {
            "disclaimer": DISCLAIMER,
            "report_id": "SR-SC042-A",
            "rolls": sorted({t["sound_roll"] for t in takes}),
        },
    )
    write("continuity_refs", {"disclaimer": DISCLAIMER, "references": CONTINUITY})
    write(
        "rights_ledger",
        {
            "disclaimer": DISCLAIMER,
            "records": [
                {
                    "record_id": rid,
                    "subject_id": sid,
                    "subject_kind": kind,
                    "document_type": doc,
                    "scope": scope,
                    "territory": territory,
                    "expires_on": expires,
                    "status": status,
                }
                for rid, sid, kind, doc, scope, territory, expires, status in RIGHTS
            ],
        },
    )
    write(
        "script_notes",
        {
            "disclaimer": DISCLAIMER,
            "notes": {
                take["take_id"]: take["note"] for take in takes if take["note"]
            }
            | {
                "general": (
                    "B-17 is new in Blue. It is not on the plan and I do not "
                    "believe we turned over on it."
                )
            },
        },
    )
    required = len([b for b in beats if b["required"]])
    print(f"\n{len(takes)} takes, {required} required beats")
    for key, value in planted.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
