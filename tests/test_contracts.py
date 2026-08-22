"""Contracts: sealing, the finding contract, and the boundary the domain keeps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lasttake.domain import sealing
from lasttake.domain.findings import (
    CheckType,
    Finding,
    FindingContractError,
    Locator,
    Role,
    Severity,
    Source,
    TruthState,
    validate,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "lasttake"

DIGEST = "a" * 64


def _finding(**overrides) -> Finding:
    base = dict(
        finding_id="f1",
        run_id="r1",
        scene_id="SC-042",
        requirement_id="B-01",
        check_type=CheckType.COVERAGE,
        truth_state=TruthState.VERIFIED,
        severity=Severity.CRITICAL,
        observation="something was observed",
        sources=[Source("takes", DIGEST, "takes")],
        locators=[Locator("take", "T-001")],
        required_role=Role.SCRIPT_SUPERVISOR,
        agent_version="test/1",
        policy_version="1.0.0",
        package_revision="rev",
    )
    base.update(overrides)
    return Finding(**base)


# -- sealing ---------------------------------------------------------------


def test_a_seal_survives_key_reordering():
    a = sealing.seal({"x": 1, "y": [1, 2], "z": {"b": 2, "a": 1}})
    b = sealing.seal({"z": {"a": 1, "b": 2}, "y": [1, 2], "x": 1})
    assert a[sealing.SEAL_KEY] == b[sealing.SEAL_KEY]


def test_a_seal_detects_a_changed_value():
    record = sealing.seal({"counts": {"covered": 31}})
    assert sealing.verify_seal(record)
    record["counts"]["covered"] = 32
    assert not sealing.verify_seal(record)


def test_an_unsealed_record_does_not_verify():
    """Absent evidence is a finding. That rule applies to our own records first."""
    assert sealing.verify_seal({"counts": {"covered": 31}}) is False


def test_a_removed_seal_does_not_verify():
    record = sealing.seal({"a": 1})
    del record[sealing.SEAL_KEY]
    assert sealing.verify_seal(record) is False


# -- the finding contract --------------------------------------------------


def test_a_finding_with_no_source_is_rejected():
    with pytest.raises(FindingContractError, match="no sources"):
        validate(_finding(sources=[]))


def test_a_finding_with_an_unusable_digest_is_rejected():
    with pytest.raises(FindingContractError, match="no usable digest"):
        validate(_finding(sources=[Source("takes", "short", "takes")]))


def test_a_verified_finding_must_point_at_something():
    with pytest.raises(FindingContractError, match="Nothing to open"):
        validate(_finding(locators=[]))


def test_an_exception_may_lack_a_locator():
    """The whole complaint can be that there is nothing to point at."""
    validate(_finding(truth_state=TruthState.MISSING, locators=[]))


def test_a_model_inference_may_not_claim_certainty():
    with pytest.raises(FindingContractError, match="may not claim certainty"):
        validate(_finding(inference="I think so", confidence=1.0))


def test_every_state_but_verified_is_an_exception():
    assert TruthState.VERIFIED.is_exception is False
    for state in (TruthState.MISSING, TruthState.CONFLICTING, TruthState.UNKNOWN):
        assert state.is_exception is True


def test_there_is_no_pass_state():
    values = {state.value for state in TruthState}
    assert values == {"verified", "missing", "conflicting", "unknown"}
    assert not values & {"pass", "clear", "safe", "ok"}


def test_a_finding_round_trips_through_storage():
    from lasttake.domain.findings import from_dict

    original = _finding()
    assert from_dict(original.to_dict()).to_dict() == original.to_dict()


# -- the boundary ----------------------------------------------------------


def test_the_domain_and_checks_import_no_sdk():
    """Gate A5, enforced rather than asserted in a README table."""
    offenders = []
    for directory in ("domain", "checks", "ports"):
        for path in (SRC / directory).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("import boto3", "from boto3", "import strands", "from strands"):
                if banned in text:
                    offenders.append(f"{path.relative_to(SRC)}: {banned}")
    assert not offenders, "domain, checks and ports must not import an SDK: " + str(offenders)


def test_the_domain_imports_cleanly_with_no_sdk_installed():
    """Proof the boundary is real: import the domain in a stripped interpreter."""
    script = (
        "import sys\n"
        "for name in list(sys.modules):\n"
        "    pass\n"
        "sys.modules['strands'] = None\n"
        "sys.modules['boto3'] = None\n"
        "import lasttake.domain.policy, lasttake.domain.rollup, lasttake.checks.coverage\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(SRC.parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_no_source_file_is_over_800_lines():
    """Gate A1. A 2,269-line component is a finding; so is a 900-line one."""
    too_long = []
    for path in SRC.rglob("*.py"):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 800:
            too_long.append(f"{path.relative_to(SRC)}: {lines}")
    assert not too_long, too_long
