"""The headline count, derived from evidence rather than asserted.

One rule decides everything on this page:

    A required beat is covered with evidence when at least one take covering it
    is usable, reconciles with the camera report, carries no unresolved
    continuity conflict, and every person and visible asset in it has a rights
    record.

Everything else is an exception, and the exception is named by whichever of
those four conditions failed. The rule is deliberately one sentence, because
the number it produces is the number a 1st AD acts on at 23:10 and a number
nobody can restate from memory is a number nobody should act on.

Note what the rule does not do. It does not mark a beat uncovered because
*some* take of it has a problem. Coverage is satisfied by one good take, and a
second take with a media identity mismatch is a real finding for the DIT
without being a coverage failure. Conflating the two would report a scene as
missing footage that is sitting on the card.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .findings import CheckType, Finding, TruthState
from .package import ScenePackage, Take


class EvidenceBasis(str, Enum):
    """On what a beat's outcome rests. Four different things, never conflated.

    "Covered" was one word doing four jobs, and the ambiguity showed up as a
    number nobody could explain: the same corpus read 31 of 34 through the
    offline lexical interpreter and 19 of 34 through Bedrock. Neither was wrong.
    They disagree about how many *declared* mappings a reader can corroborate
    from the evidence on file, and until now the interface reported only the
    total and called it coverage.

    ``DECLARED`` is the production's own record: a take names this beat. That is
    an assertion by the people who were there, and it is worth something, but it
    is not the same as a second reader agreeing.

    ``INTERPRETED`` is that assertion corroborated by whatever interpreter ran.
    It is the strongest thing this system can produce on its own.

    ``CONFIRMED`` is a named human with the authority saying so, and it outranks
    both, because that is the only judgement this product does not make.

    ``INSUFFICIENT`` is everything else, including a model that timed out, a
    model that could not tell, and no take at all. None of those is a pass.
    """

    DECLARED = "declared_by_the_production"
    INTERPRETED = "corroborated_by_the_interpreter"
    CONFIRMED = "confirmed_by_a_named_human"
    INSUFFICIENT = "insufficient_evidence"


class BeatStatus(str, Enum):
    COVERED = "covered_with_evidence"
    NO_COVERAGE = "no_viable_coverage"
    CONTINUITY_EXCEPTION = "continuity_exception"
    NO_RELEASE_RECORD = "no_release_record"
    MEDIA_EXCEPTION = "media_identity_exception"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class BeatOutcome:
    beat_id: str
    slug: str
    status: BeatStatus
    reason: str
    evidence_take_id: str | None
    blocking_finding_ids: tuple[str, ...]
    basis: EvidenceBasis = EvidenceBasis.INSUFFICIENT

    def to_dict(self) -> dict:
        return {
            "beat_id": self.beat_id,
            "slug": self.slug,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_take_id": self.evidence_take_id,
            "blocking_finding_ids": list(self.blocking_finding_ids),
            "basis": self.basis.value,
        }


class _Index:
    """Findings arranged the way the rule below wants to ask about them."""

    def __init__(self, findings: list[Finding]) -> None:
        self.metadata: dict[str, Finding] = {}
        self.rights: dict[str, Finding] = {}
        self.coverage: dict[str, Finding] = {}
        self.continuity_takes: dict[str, Finding] = {}
        for finding in findings:
            if finding.requirement_id is None:
                continue
            if finding.check_type is CheckType.METADATA:
                self.metadata[finding.requirement_id] = finding
            elif finding.check_type is CheckType.RIGHTS:
                self.rights[finding.requirement_id] = finding
            elif finding.check_type is CheckType.COVERAGE:
                self.coverage[finding.requirement_id] = finding
            elif finding.check_type is CheckType.CONTINUITY:
                # Any continuity result that is not verified takes its takes out
                # of evidence, not only a confident conflict.
                #
                # This used to read `is TruthState.CONFLICTING`, so a reference
                # the check could not answer left every take under it viable and
                # the beat read as covered. That is absent evidence counted as a
                # pass, in the one number a 1st AD acts on at 23:10. It was found
                # by `tools/ablation.py`: with the model unreachable the covered
                # count went *up*, from 31 to 32, because the unanswered conflict
                # stopped blocking anything.
                if finding.truth_state.is_exception:
                    # A continuity finding names the takes it is about. Those
                    # takes, and only those, stop being viable evidence.
                    for locator in finding.locators:
                        if locator.kind == "take":
                            self.continuity_takes[locator.value] = finding

    def blocks(self, take: Take) -> tuple[str, list[str]]:
        """Why this take cannot serve as evidence, or ``("", [])`` if it can."""
        if not take.usable:
            return "take marked unusable at capture", []

        meta = self.metadata.get(take.take_id)
        if meta is None:
            return "no current media identity result for this take", []
        if meta.truth_state is not TruthState.VERIFIED:
            return (
                f"media identity {meta.truth_state.value}",
                [meta.finding_id],
            )

        conflict = self.continuity_takes.get(take.take_id)
        if conflict is not None:
            return (
                f"continuity {conflict.truth_state.value} and cites this take",
                [conflict.finding_id],
            )

        for subject in list(take.visible_people) + list(take.visible_assets):
            rights = self.rights.get(subject)
            if rights is None:
                return (f"no current rights result for {subject}", [])
            if rights.truth_state is not TruthState.VERIFIED:
                return (
                    f"{subject}: rights record {rights.truth_state.value}",
                    [rights.finding_id],
                )
        return "", []


def _classify(reason: str) -> BeatStatus:
    if "rights record" in reason or "no current rights result" in reason:
        return BeatStatus.NO_RELEASE_RECORD
    if "continuity" in reason:
        return BeatStatus.CONTINUITY_EXCEPTION
    if "media identity" in reason:
        return BeatStatus.MEDIA_EXCEPTION
    return BeatStatus.NO_COVERAGE


def roll_up(
    package: ScenePackage,
    findings: list[Finding],
    decisions: list[dict] | None = None,
) -> list[BeatOutcome]:
    """One outcome per required beat, in script order, and what each rests on."""
    index = _Index(findings)
    confirmed = {
        d["finding_id"]
        for d in (decisions or [])
        if d.get("action") in ("confirm", "accept_exception")
    }
    outcomes: list[BeatOutcome] = []

    for beat in package.required_beats:
        candidates = package.takes_for_beat(beat.beat_id)
        if not candidates:
            coverage = index.coverage.get(beat.beat_id)
            outcomes.append(
                BeatOutcome(
                    beat_id=beat.beat_id,
                    slug=beat.slug,
                    status=BeatStatus.NO_COVERAGE,
                    reason="no take covers this beat",
                    evidence_take_id=None,
                    blocking_finding_ids=(coverage.finding_id,) if coverage else (),
                    basis=EvidenceBasis.INSUFFICIENT,
                )
            )
            continue

        blocked: list[tuple[str, list[str]]] = []
        clean: Take | None = None
        for take in candidates:
            reason, finding_ids = index.blocks(take)
            if not reason:
                clean = take
                break
            blocked.append((reason, finding_ids))

        # A take naming a beat is the production's own assertion that it
        # contains it. The coverage check is the second reading of that
        # assertion, and until now the rollup ignored it: a beat whose coverage
        # result was `unknown` still counted as covered, because a viable take
        # named it. The gate refused, so nothing unsafe shipped, but the number
        # on the page said covered while the check said it could not tell.
        # Found by `tools/ablation.py`, which removed the model and watched the
        # covered count refuse to move.
        coverage = index.coverage.get(beat.beat_id)
        if clean is not None and (
            coverage is None or coverage.truth_state is not TruthState.VERIFIED
        ):
            outcomes.append(
                BeatOutcome(
                    beat_id=beat.beat_id,
                    slug=beat.slug,
                    status=BeatStatus.NO_COVERAGE,
                    reason=(
                        "no current coverage result for this beat"
                        if coverage is None
                        else f"coverage {coverage.truth_state.value}: a take names this "
                        "beat, and the check could not establish that it contains it"
                    ),
                    evidence_take_id=None,
                    blocking_finding_ids=(coverage.finding_id,) if coverage else (),
                    # The production declared this mapping and no second reader
                    # could corroborate it. That is a weaker thing than nothing
                    # being shot, and a different thing, and the difference is
                    # the whole 31-against-19 gap between two interpreters.
                    basis=(
                        EvidenceBasis.DECLARED
                        if coverage is not None
                        else EvidenceBasis.INSUFFICIENT
                    ),
                )
            )
            continue

        if clean is not None:
            outcomes.append(
                BeatOutcome(
                    beat_id=beat.beat_id,
                    slug=beat.slug,
                    status=BeatStatus.COVERED,
                    reason=f"take {clean.take_id} is usable, reconciles and is cleared",
                    evidence_take_id=clean.take_id,
                    blocking_finding_ids=(),
                    basis=(
                        EvidenceBasis.CONFIRMED
                        if coverage.finding_id in confirmed
                        else EvidenceBasis.INTERPRETED
                    ),
                )
            )
            continue

        # Every candidate is blocked. Report the first reason, and gather every
        # finding that contributed, so the supervisor sees the whole picture
        # rather than one symptom of it.
        first_reason = blocked[0][0]
        all_ids: list[str] = []
        for _reason, ids in blocked:
            for fid in ids:
                if fid not in all_ids:
                    all_ids.append(fid)
        outcomes.append(
            BeatOutcome(
                beat_id=beat.beat_id,
                slug=beat.slug,
                status=_classify(first_reason),
                reason=first_reason,
                evidence_take_id=None,
                blocking_finding_ids=tuple(all_ids),
                # Something was shot against this beat and something else about
                # it is unresolved. The mapping is declared; the beat is not
                # covered.
                basis=EvidenceBasis.DECLARED,
            )
        )
    return outcomes


def headline(outcomes: list[BeatOutcome]) -> dict:
    """The five numbers a judge is told, produced by the pipeline that earned them."""
    counted = {status: 0 for status in BeatStatus}
    for outcome in outcomes:
        counted[outcome.status] += 1
    exceptions = (
        counted[BeatStatus.NO_COVERAGE]
        + counted[BeatStatus.CONTINUITY_EXCEPTION]
        + counted[BeatStatus.MEDIA_EXCEPTION]
    )
    by_basis = {basis: 0 for basis in EvidenceBasis}
    for outcome in outcomes:
        by_basis[outcome.basis] += 1
    return {
        "required_beats": len(outcomes),
        "covered_with_evidence": counted[BeatStatus.COVERED],
        "raising_exceptions": exceptions,
        "without_release_record": counted[BeatStatus.NO_RELEASE_RECORD],
        "not_assessed": counted[BeatStatus.NOT_ASSESSED],
        # The same beats, counted by what their outcome rests on rather than by
        # what it concluded. This is the breakdown that explains why two
        # interpreters reading one corpus report different coverage: they agree
        # on what the production declared and disagree on how much of it a second
        # reader can corroborate.
        "basis": {basis.value: by_basis[basis] for basis in EvidenceBasis},
    }


def sentence(outcomes: list[BeatOutcome]) -> str:
    """The count as the 1st AD hears it, built from the same numbers."""
    h = headline(outcomes)
    return (
        f"Of {h['required_beats']} required beats, "
        f"{h['covered_with_evidence']} covered with evidence, "
        f"{h['raising_exceptions']} raising exceptions with named sources, "
        f"{h['without_release_record']} with no release record and routed to production."
    )
