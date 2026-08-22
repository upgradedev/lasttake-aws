"""A deterministic, offline stand-in for the language model.

This exists for two reasons and only two. Tests must run with no network and no
credential, and a unit on a location with no signal must still get an answer.

It is not pretending to be the model. ``model_id`` says
``offline-lexical/1.0.0`` and that string is written onto every finding it
touches, so a reader of the turnover packet can always tell which interpreter
produced an inference. A demo that quietly falls back to this and reports the
result as a model output would be exactly the kind of claim this product
exists to catch.

What it actually does is shallow and honest: token overlap, plus a small list
of phrases a script supervisor writes when a take is not usable and when a
physical state has changed. Nothing here is machine learning.
"""

from __future__ import annotations

import re

from ...ports.interpreter import BeatMatch, ContinuityOpinion

MODEL_ID = "offline-lexical/1.0.0"

#: Phrases that mean the take did not get the beat. Written the way a
#: supervisor writes them at speed, not the way a schema would like them.
#: Matched on word boundaries, never as bare substrings. ``ng`` is the
#: supervisor's shorthand for "no good" and it also sits inside "single",
#: "wrong" and "strong"; a substring match reads "Clean single" as a failed
#: take, which is precisely the false positive that gets a tool switched off.
NEGATIVE_MARKERS = (
    "false start",
    "no good",
    "ng",
    "cut early",
    "camera cut",
    "out of frame",
    "did not get",
    "incomplete",
    "boom in shot",
)

#: State words that appear in continuity notes. Two notes that pick different
#: words from the same opposed pair are describing different states.
OPPOSED_PAIRS = (
    ("full", "empty"),
    ("half full", "empty"),
    ("open", "closed"),
    ("up", "down"),
    ("left", "right"),
    ("on", "off"),
    ("wet", "dry"),
    ("lit", "unlit"),
)

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "of", "to", "in", "on", "at", "she", "he", "her",
    "his", "they", "it", "is", "was", "with", "from", "for", "through", "into",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class OfflineInterpreter:
    """Implements :class:`lasttake.ports.interpreter.Interpreter`."""

    @property
    def model_id(self) -> str:
        return MODEL_ID

    def match_beat_to_take(
        self, beat_description: str, take_slate: str, take_note: str, shot_description: str
    ) -> BeatMatch:
        note = (take_note or "").lower()
        for marker in NEGATIVE_MARKERS:
            if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", note):
                return BeatMatch(
                    covers=False,
                    confidence=0.9,
                    rationale=(
                        f"The take note says {marker!r}, which reads as the beat not "
                        "having been captured on this take."
                    ),
                )

        # The take already names the beat; the question is whether anything in
        # the written record argues against it. Nothing does, so the match
        # stands, with confidence lifted by how well the setup description
        # matches the beat.
        support = _overlap(beat_description, shot_description)
        confidence = min(0.95, 0.72 + support * 0.5)
        return BeatMatch(
            covers=True,
            confidence=confidence,
            rationale=(
                f"The take is slated {take_slate} against a setup described as "
                f"{shot_description!r}, and no note contradicts the beat. Lexical "
                f"support between beat and setup is {support:.2f}."
            ),
        )

    def compare_continuity(
        self, subject: str, established_state: str, note_a: str, note_b: str
    ) -> ContinuityOpinion:
        a, b = (note_a or "").lower(), (note_b or "").lower()
        if not a or not b:
            return ContinuityOpinion(
                states_agree=False,
                possibly_intentional=False,
                confidence=0.35,
                rationale=(
                    "One of the two preferred takes has no continuity note, so the "
                    "states cannot be compared. This is insufficient evidence, not "
                    "agreement."
                ),
            )

        differences = []
        for left, right in OPPOSED_PAIRS:
            in_a = (left in a, right in a)
            in_b = (left in b, right in b)
            if in_a[0] and in_b[1] and not in_a[1]:
                differences.append(f"{left} against {right}")
            elif in_a[1] and in_b[0] and not in_a[0]:
                differences.append(f"{right} against {left}")

        if not differences:
            return ContinuityOpinion(
                states_agree=True,
                possibly_intentional=False,
                confidence=0.8,
                rationale=(
                    f"Both notes describe {subject} without picking opposed states, "
                    f"and neither departs from the established reference."
                ),
            )

        established = established_state.lower()
        # If one of the takes matches the established reference and the other
        # does not, that reads as drift. If neither matches, it reads more like
        # a deliberate change that was never written back to the reference.
        a_matches = _overlap(established, a) > 0.15
        b_matches = _overlap(established, b) > 0.15
        return ContinuityOpinion(
            states_agree=False,
            possibly_intentional=not (a_matches or b_matches),
            confidence=0.78,
            rationale=(
                f"The two notes for {subject} pick opposed states: "
                + "; ".join(differences)
                + f". Established reference is {established_state!r}."
            ),
        )
