"""Synthetic release-pair controls; no recording, provider or live API calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_proof", ROOT / "video/release_proof.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)

# Independent known release pair, not derived from the implementation's input.
FE = "7bc2490aede68bb3a001e811e70f1664e434e08d"
BE = "c1898bbc30d803e63d71b0ccef2bb258d59b7ba3"


@pytest.fixture
def evidence():
    return {
        "/release.json": {"commit": FE},
        "/healthz": {"ok": True, "commit": BE, "served_by": {"ignored": True}},
        "actions/runs/101": {"id": 101, "head_sha": FE, "status": "completed",
            "conclusion": "success", "path": ".github/workflows/frontend-deploy.yml", "run_attempt": 1},
        "actions/runs/202": {"id": 202, "head_sha": BE, "status": "completed",
            "conclusion": "success", "path": ".github/workflows/deploy.yml", "run_attempt": 2},
        "actions/runs/202/attempts/2/jobs?per_page=100": {"total_count": 1, "jobs": [
            {"name": "deploy", "status": "completed", "conclusion": "success", "steps": [
                {"name": "the URL answers, and it is the commit we just built", "conclusion": "success"},
                {"name": "the hero, on the deployed architecture", "conclusion": "success"},
                {"name": "the Strands to Bedrock path, actually run", "conclusion": "success"},
            ]},
        ]},
    }


def observe(evidence, hosted="101", governed="202"):
    return proof.observe(FE, hosted, governed, fetch=evidence.__getitem__, api=evidence.__getitem__)


def test_different_frontend_and_backend_revisions_are_a_valid_pair(evidence):
    result = observe(evidence)
    assert result["releaseSha"] == FE and result["backendSha"] == BE and FE != BE
    assert result["hostedProof"]["headSha"] == FE
    assert result["governedProof"]["headSha"] == BE
    assert result["governedProof"]["runAttempt"] == 2
    assert "served_by" not in json.dumps(result)


@pytest.mark.parametrize(("hosted", "governed"), [("", ""), ("101", ""), ("", "202")])
def test_proofs_remain_optional_without_losing_component_binding(evidence, hosted, governed):
    result = observe(evidence, hosted, governed)
    binding = proof.recording_binding(result, result, {"releaseSha": FE, "appOrigin": proof.ORIGIN},
                                      FE, hosted, governed)
    assert binding["backendSha"] == BE
    assert ("hostedRunId" in binding) == bool(hosted)
    assert ("governedRunId" in binding) == bool(governed)


@pytest.mark.parametrize(("path", "field", "value"), [
    ("/release.json", "commit", BE),
    ("/healthz", "commit", "c1898bbc"),
    ("/healthz", "commit", None),
    ("/healthz", "ok", False),
    ("actions/runs/101", "head_sha", BE),
    ("actions/runs/101", "path", ".github/workflows/deploy.yml"),
    ("actions/runs/101", "conclusion", "failure"),
    ("actions/runs/202", "head_sha", FE),
    ("actions/runs/202", "path", ".github/workflows/ci.yml"),
    ("actions/runs/202", "conclusion", "failure"),
    ("actions/runs/202", "conclusion", "cancelled"),
    ("actions/runs/202", "status", "in_progress"),
    ("actions/runs/202", "id", 303),
    ("actions/runs/202", "run_attempt", None),
])
def test_wrong_component_workflow_failed_or_unfinished_proof_is_rejected(evidence, path, field, value):
    evidence[path][field] = value
    with pytest.raises(ValueError):
        observe(evidence)


@pytest.mark.parametrize("mode", ["skipped", "lifecycle", "missing-step", "failed-step", "incomplete"])
def test_successful_workflow_without_actual_backend_proof_is_rejected(evidence, mode):
    jobs = evidence["actions/runs/202/attempts/2/jobs?per_page=100"]
    job = jobs["jobs"][0]
    if mode == "skipped":
        job["conclusion"] = "skipped"
    elif mode == "lifecycle":
        job["name"] = "lifecycle"
    elif mode == "missing-step":
        job["steps"].pop()
    elif mode == "failed-step":
        job["steps"][1]["conclusion"] = "failure"
    else:
        jobs["total_count"] = 2
    with pytest.raises(ValueError):
        observe(evidence)


@pytest.mark.parametrize("invalid", ["0", "-1", "202/attempts/1", " 202", "2e2"])
def test_invalid_proof_id_is_refused_before_io(invalid):
    def unexpected(_):
        pytest.fail("Invalid proof ID reached I/O")
    with pytest.raises(ValueError):
        proof.observe(FE, "", invalid, fetch=unexpected, api=unexpected)


@pytest.mark.parametrize("field", ["releaseSha", "backendSha", "governedProof", "hostedProof"])
def test_drift_during_recording_is_refused(evidence, field):
    before = observe(evidence)
    after = copy.deepcopy(before)
    after[field] = "changed"
    with pytest.raises(ValueError, match="changed"):
        proof.unchanged(before, after)


def test_cli_retains_drift_observation_and_never_overwrites_it(evidence, tmp_path, monkeypatch):
    before = observe(evidence)
    monkeypatch.setenv("LASTTAKE_VIDEO_ROOT", str(tmp_path))
    monkeypatch.setenv("LASTTAKE_RELEASE_SHA", FE)
    monkeypatch.setattr(proof, "observe", lambda *args: before)
    monkeypatch.setattr(sys, "argv", ["release_proof.py", "before"])
    proof.main()
    original = (tmp_path / "release-before.json").read_bytes()
    with pytest.raises(FileExistsError):
        proof.main()
    after = {**before, "backendSha": "d" * 40}
    monkeypatch.setattr(proof, "observe", lambda *args: after)
    monkeypatch.setattr(sys, "argv", ["release_proof.py", "after"])
    with pytest.raises(ValueError, match="backendSha"):
        proof.main()
    assert json.loads((tmp_path / "release-after.json").read_text())["backendSha"] == "d" * 40
    assert (tmp_path / "release-before.json").read_bytes() == original


@pytest.mark.parametrize("drift", [False, True])
def test_composer_binds_receipt_before_any_media_command(evidence, tmp_path, monkeypatch, drift):
    monkeypatch.setenv("LASTTAKE_VIDEO_ROOT", str(tmp_path))
    monkeypatch.setenv("LASTTAKE_RELEASE_SHA", FE)
    monkeypatch.setenv("LASTTAKE_HOSTED_RUN_ID", "101")
    monkeypatch.setenv("LASTTAKE_GOVERNED_RUN_ID", "202")
    monkeypatch.setenv("FFMPEG", "no-media-process-allowed")
    monkeypatch.setitem(sys.modules, "release_proof", proof)
    spec = importlib.util.spec_from_file_location("composer", ROOT / "video/build-video.py")
    composer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(composer)
    (tmp_path / "narration").mkdir()
    (tmp_path / "capture").mkdir()
    scene_ids = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
    scenes = []
    for index, scene_id in enumerate(scene_ids, start=1):
        audio = tmp_path / "narration" / f"{index:02d}-{scene_id}.mp3"
        audio.write_bytes(f"inert audio fixture {scene_id}".encode())
        scenes.append({
            "id": scene_id, "audio": audio.name,
            "startSeconds": (index - 1) * 14, "durationSeconds": 13.35,
            "holdSeconds": 14, "audioSha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        })
    (tmp_path / "narration/timing.json").write_text(json.dumps({
        "schemaVersion": "lasttake.submission-video-timing/v1",
        "mode": "final", "totalSeconds": 98,
        "narrationSourceSha256": hashlib.sha256(
            (ROOT / "video/narration.json").read_bytes()
        ).hexdigest(),
        "scenes": scenes,
    }))
    (tmp_path / "narration/captions.en.srt").write_text("synthetic captions")
    (tmp_path / "narration/caption-windows.json").write_text(json.dumps({
        "schemaVersion": "lasttake.submission-video-caption-windows/v1",
        "scenes": list(scene_ids), "windows": [],
    }))
    capture_bytes = b"inert raw capture fixture"
    (tmp_path / "capture/production.webm").write_bytes(capture_bytes)
    (tmp_path / "capture/capture-receipt.json").write_text(json.dumps({
        "releaseSha": FE, "appOrigin": proof.ORIGIN, "trimLeadSeconds": 0,
        "sceneCount": 7,
        "sceneTimings": [{"id": scene_id} for scene_id in scene_ids],
        "bytes": len(capture_bytes),
        "sha256": hashlib.sha256(capture_bytes).hexdigest(),
    }))
    before = observe(evidence)
    after = {**before, "backendSha": "d" * 40} if drift else before
    for phase, result in (("before", before), ("after", after)):
        (tmp_path / f"release-{phase}.json").write_text(json.dumps(result))

    def fake_media_command(_):
        assert not drift, "Drift reached the media command"
        # Inert fixture bytes, not a generated video or a real recording.
        (tmp_path / "output/lasttake-demo.mp4").write_bytes(b"inert receipt fixture")

    monkeypatch.setattr(composer, "run", fake_media_command)
    monkeypatch.setattr(composer, "probe", lambda _: {"format": {"duration": 98}, "streams": [
        {"codec_type": "video", "width": 1920, "height": 1080}, {"codec_type": "audio"}]})
    if drift:
        with pytest.raises(ValueError, match="backendSha"):
            composer.main()
        assert not (tmp_path / "output").exists()
    else:
        composer.main()
        receipt = json.loads((tmp_path / "output/video-receipt.json").read_text())
        assert receipt["schemaVersion"] == "lasttake.submission-video-receipt/v1"
        assert receipt["releaseSha"] == FE and receipt["backendSha"] == BE
        assert receipt["hostedRunId"] == 101 and receipt["governedRunId"] == 202


def test_workflow_preserves_exact_release_owner_gate_and_both_observations():
    workflow = (ROOT / ".github/workflows/submission-video.yml").read_text()
    assert 'test "${GITHUB_SHA}" = "${LASTTAKE_RELEASE_SHA}"' in workflow
    assert workflow.index("NOT_CONFIGURED") < workflow.index("video/release_proof.py before")
    assert workflow.index("video/release_proof.py before") < workflow.index("Generate measured narration")
    assert workflow.index("node video/capture-production.mjs") < workflow.index("video/release_proof.py after")
    assert workflow.index("video/release_proof.py after") < workflow.index("run: python3 video/build-video.py")
    assert workflow.index("run: python3 video/build-video.py") < workflow.index("scripts/verify_video_sync.py")
    assert "if: always() && steps.capture.outcome != 'skipped'" in workflow
    assert "Retain release observations even when recording fails" in workflow
    assert ".backendSha == $backend" in workflow
    assert "captureSha256" in workflow and "captionWindowsSha256" in workflow
    assert "narrationSourceSha256" in workflow
    assert "actions/cache/restore@" in workflow and "actions/cache/save@" in workflow
    assert "continue-on-error" not in workflow
    capture = (ROOT / "web/video/capture-production.mjs").read_text()
    assert "release.commit !== releaseSha" in capture and "after.commit !== releaseSha" in capture
