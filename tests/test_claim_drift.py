"""CI-only checks for current claims, historical evidence and owner-gated media."""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_staleness_probe_measures_actual_gate_admission_without_overwriting_history(capsys):
    spec = importlib.util.spec_from_file_location("ablation_probe", ROOT / "tools/ablation.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    before = (ROOT / "docs/ablation.json").read_bytes()
    result = probe.staleness_check()
    assert result["carried_stale"] > 0
    assert result["actually_admitted_stale"] == 0
    assert "actual gate still discards" in result["without_the_rule"]
    assert probe.main() == 0
    assert '"actually_admitted_stale": 0' in capsys.readouterr().out
    assert (ROOT / "docs/ablation.json").read_bytes() == before


def test_video_preflight_is_explicit_and_before_any_provider_or_install():
    workflow = text(".github/workflows/submission-video.yml")
    assert "upgradedev/<REPO>" not in workflow and "ARCHON_" not in workflow
    assert "if: github.repository" not in workflow  # Wrong branch/repository must fail, not skip green.
    assert 'test "${GITHUB_REPOSITORY}" = "upgradedev/lasttake-aws"' in workflow
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert "NOT_CONFIGURED" in workflow and "READY_OWNER_VERIFIED" in workflow
    assert workflow.index("NOT_CONFIGURED") < workflow.index("Install ephemeral media tooling")
    assert workflow.index("NOT_CONFIGURED") < workflow.index("Generate measured narration")
    assert ".github/workflows/frontend-deploy.yml" in workflow and ".github/workflows/deploy.yml" in workflow
    assert "google-github-actions" not in workflow and "id-token: write" not in workflow
    assert "lasttake-demo.mp4" in workflow and "lasttake-demo.mp4" in text("video/build-video.py")
    for path in ("video/build-video.py", "video/generate-narration.py", "web/video/capture-production.mjs"):
        source = text(path)
        assert "ARCHON_" not in source and "LASTTAKE_VIDEO_ROOT" in source
        assert "video/upstream/" in source  # Mandatory provenance is not removed.
        if path.endswith(".py"):
            compile(source, path, "exec")  # Parse only, never execute media tooling.


@pytest.mark.parametrize("status", [None, "NOT_CONFIGURED", "READY", ""])
def test_narration_refuses_unconfigured_status_before_reaching_any_provider(status):
    tree = ast.parse(text("video/generate-narration.py"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    class Spec:
        def read_text(self, **_):
            return json.dumps({"recording_status": status})
    namespace = {"SPEC": Spec(), "json": json}
    # Only the function is loaded. No provider functions, credentials, filesystem roots or network exist here.
    exec(compile(ast.Module(body=[main], type_ignores=[]), "narration-preflight", "exec"), namespace)
    with pytest.raises(SystemExit, match="NOT_CONFIGURED"):
        namespace["main"]()
    assert json.loads(text("video/narration.json"))["recording_status"] == "NOT_CONFIGURED"


def test_current_docs_distinguish_live_demo_history_and_unknown_benefits():
    for path in ("README.md", "docs/assurance.md", "docs/BEDROCK_AGENTCORE_ARCHITECTURE.md"):
        first = text(path)[:2400]
        assert "https://d3kf6hquzlli8g.cloudfront.net/" in first
        assert "Strands" in first and "offline" in first.lower()
    assurance = text("docs/assurance.md")
    assert "---|---|---|" not in assurance.splitlines() and "under $0.01" not in assurance
    assert "Every component scales to zero" not in assurance
    assert "not truth" in text("README.md")
    assert "serialized records" in text("README.md")
    for name in ("measurement", "build_stories"):
        assert "Historical entries" in json.loads(text(f"docs/{name}.json"))["_current_scope"]["evidence_limits"]
    uat = json.loads(text("frontend/UAT.testbook.json"))["current_reliability_revision"]
    assert uat["status"] == "AUTOMATION_PASS" and uat["scope"] == "CI_REAL_HTTP_ONLY"
    assert uat["implementation_sha"] == "59844080b768993d67821fd6fb55db9049c998db"
    assert uat["ci_run_url"].endswith("/34377650942")
    assert uat["human_signoff"] == uat["live_aws_acceptance"] == "NOT_RUN"


def test_backend_release_preserves_real_model_and_process_boundary_proofs():
    workflow = text(".github/workflows/deploy.yml")
    for assertion in ("assert len(interpreted) == 34", '== {"coverage", "continuity"}',
                      '.startswith("bedrock:")', "assert c1 != c2", "assert required == 34",
                      "assert covered <= 31", "assert f[\"confidence\"] < 1.0",
                      "d['run_state_store']=='aurora-dsql'", "receipts[0]['status']=='accepted'"):
        assert assertion in workflow
    assert "under 0.01 USD" not in workflow


def test_archive_is_fixed_source_read_only_manual_opt_in_and_deduplicated():
    source = text(".github/workflows/frontend-ci.yml")
    archive = source.split("  archive-previous-acceptance:", 1)[1].split("  verify:", 1)[0]
    assert "github.event_name == 'workflow_dispatch' && inputs.archive_previous_acceptance == true" in archive
    assert "default: false" in source
    assert "run_id: 34359050749" in archive and "artifact_id: 10107569851" in archive
    assert "contents: read" in archive and "actions: read" in archive
    assert "previous.some" in archive and "overwrite: false" in archive
    assert "archive_sha256" in archive and "original_artifact_id" in archive
    assert "deleteArtifact" not in archive and "unzip" not in archive
    for name in ("frontend-ci", "frontend-deploy", "aws-uat", "aws-hosting-ci", "submission-video", "codeql", "live-surface"):
        workflow = text(f".github/workflows/{name}.yml")
        uploads = workflow.split("uses: actions/upload-artifact@")[1:]
        assert uploads
        for upload in uploads:
            assert "retention-days: 90" in upload.split("\n      - ", 1)[0]
