"""The only door a language model is allowed through.

Two questions, both bounded, both returning a structured opinion that a
deterministic rule then judges. The model never sees a truth state, never sees
the policy, and never returns one. It answers "do these two descriptions
describe the same beat" and "do these two notes describe the same physical
state", which are language questions, and language is what it is for.

Everything it is bad at is kept away from it: timecode arithmetic, checksum
comparison, identifier equality, counting. Those are in the deterministic
checks, where being right is cheap.

The confidence a model returns is recorded on the finding and is never allowed
to change a truth state. Under wrap pressure, a system that can be talked into
a pass by a confident-sounding sentence is worse than no system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class BeatMatch:
    """Whether a take plausibly contains a beat, in the model's reading."""

    covers: bool
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ContinuityOpinion:
    """Whether two recorded states describe the same physical continuity.

    ``possibly_intentional`` exists because a change between takes is very
    often a deliberate choice by the director, and a system that calls every
    difference an error gets muted inside one shoot day.
    """

    states_agree: bool
    possibly_intentional: bool
    confidence: float
    rationale: str


@runtime_checkable
class Interpreter(Protocol):
    """Bounded language interpretation. Implementations must not raise on
    ambiguity; they return low confidence instead, and the caller turns that
    into ``unknown``, which is an exception, not a pass."""

    @property
    def model_id(self) -> str: ...

    def match_beat_to_take(
        self, beat_description: str, take_slate: str, take_note: str, shot_description: str
    ) -> BeatMatch: ...

    def compare_continuity(
        self, subject: str, established_state: str, note_a: str, note_b: str
    ) -> ContinuityOpinion: ...
