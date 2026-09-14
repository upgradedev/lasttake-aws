"""CI-only checks for current claims, historical evidence and owner-gated media."""
import ast
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

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
        assert "No pristine upstream" in source and "vendored here" in source
        assert "video/upstream/" not in source
        if path.endswith(".py"):
            compile(source, path, "exec")  # Parse only, never execute media tooling.
    assert "python3 scripts/verify_video_sync.py" in workflow
    assert workflow.index("video/build-video.py") < workflow.index("scripts/verify_video_sync.py")
    assert "actions/cache/restore@" in workflow and "actions/cache/save@" in workflow


def test_narration_preview_is_separate_and_cannot_capture_or_compose():
    workflow = text(".github/workflows/narration-preview.yml")
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert 'test "${GITHUB_SHA}" = "${LASTTAKE_RELEASE_SHA}"' in workflow
    assert "LASTTAKE_NARRATION_MODE: preview" in workflow
    assert "video/generate-narration.py" in workflow
    assert "capture-production" not in workflow and "build-video.py" not in workflow
    assert "actions/cache/restore@" in workflow and "actions/cache/save@" in workflow
    final = text(".github/workflows/submission-video.yml")
    cache_path = "${{ runner.temp }}/lasttake-submission-video/narration"
    cache_prefix = "${{ runner.os }}-lasttake-narration-v2-"
    assert cache_path in workflow and cache_path in final
    assert cache_prefix in workflow and cache_prefix in final


def test_narration_cache_key_changes_only_the_affected_text_or_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("LASTTAKE_VIDEO_ROOT", str(tmp_path))
    module_spec = importlib.util.spec_from_file_location(
        "generate_narration", ROOT / "video/generate-narration.py"
    )
    narration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(narration)
    voice = {
        "elevenLabs": {
            "voiceId": "pNInz6obpgDQGcFmaJgB",
            "modelId": "eleven_multilingual_v2",
        }
    }
    first = narration.cache_key("first beat", voice, "elevenlabs")
    assert first == narration.cache_key("first beat", voice, "elevenlabs")
    assert first != narration.cache_key("changed beat", voice, "elevenlabs")
    changed_voice = {
        "elevenLabs": {**voice["elevenLabs"], "voiceId": "abcdefghijklmnop"}
    }
    assert first != narration.cache_key("first beat", changed_voice, "elevenlabs")
    assert "audioSha256" in text("video/generate-narration.py")


@pytest.mark.parametrize("status", [None, "NOT_CONFIGURED", "READY", ""])
def test_narration_refuses_non_owner_verified_status_before_reaching_any_provider(status):
    tree = ast.parse(text("video/generate-narration.py"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    class Spec:
        def read_text(self, **_):
            return json.dumps({"recording_status": status})
    namespace = {"SPEC": Spec(), "json": json, "os": SimpleNamespace(environ={})}
    # Only the function is loaded. No provider functions, credentials, filesystem roots or network exist here.
    exec(compile(ast.Module(body=[main], type_ignores=[]), "narration-preflight", "exec"), namespace)
    with pytest.raises(SystemExit, match="NOT_CONFIGURED"):
        namespace["main"]()
    narration = json.loads(text("video/narration.json"))
    assert narration["recording_status"] == "READY_OWNER_VERIFIED"
    assert "preview 34906235283" in narration["_comment"]
    assert "5777be505a14e7c91484d5ba451a302c5601924f" in narration["_comment"]


def test_narration_preview_can_measure_not_configured_source_before_owner_activation():
    tree = ast.parse(text("video/generate-narration.py"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    class Spec:
        def read_text(self, **_):
            return json.dumps({"recording_status": "NOT_CONFIGURED"})
    namespace = {
        "SPEC": Spec(), "json": json,
        "os": SimpleNamespace(environ={"LASTTAKE_NARRATION_MODE": "preview"}),
    }
    exec(compile(ast.Module(body=[main], type_ignores=[]), "narration-preview", "exec"), namespace)
    with pytest.raises(SystemExit, match="narration contract is invalid"):
        namespace["main"]()


def test_current_docs_distinguish_live_demo_history_and_unknown_benefits():
    for path in ("README.md", "docs/assurance.md", "docs/BEDROCK_AGENTCORE_ARCHITECTURE.md"):
        first = text(path)[:2400]
        link_targets = re.findall(r"\]\((https?://[^)\s]+)\)", first)
        assert any(target == "https://d3kf6hquzlli8g.cloudfront.net/" for target in link_targets)
        assert "Strands" in first and "offline" in first.lower()
    assurance = text("docs/assurance.md")
    assert "---|---|---|" not in assurance.splitlines() and "under $0.01" not in assurance
    assert "Every component scales to zero" not in assurance
    assert "not truth" in text("README.md")
    assert "serialized record" in text("README.md")
    for name in ("measurement", "build_stories"):
        assert "Historical entries" in json.loads(text(f"docs/{name}.json"))["_current_scope"]["evidence_limits"]
    uat = json.loads(text("frontend/UAT.testbook.json"))["current_reliability_revision"]
    assert uat["status"] == "AUTOMATION_PASS" and uat["scope"] == "CI_REAL_HTTP_ONLY"
    assert uat["implementation_sha"] == "59844080b768993d67821fd6fb55db9049c998db"
    assert uat["ci_run_url"] == "https://github.com/upgradedev/lasttake-aws/actions/runs/34377650942"
    assert uat["human_signoff"] == uat["live_aws_acceptance"] == "NOT_RUN"


def test_submission_surfaces_match_bounded_offline_and_terminal_subscriber_truth():
    paths = (
        "frontend/src/Landing.tsx",
        "src/lasttake/app/static/index.html",
        "video/narration.json",
        "docs/submission_description.json",
    )
    for path in paths:
        source = text(path).lower()
        assert "fifteen minutes" not in source, path
        assert "a pickup day" not in source, path

    narration = json.loads(text("video/narration.json"))
    topology = next(segment for segment in narration["segments"] if segment["id"] == "surface")
    assert "One Strands orchestrator Agent calls eight tools" in topology["captionText"]
    assert "four evidence checks" in topology["captionText"]
    assert "two ToolContext interrupt transitions" in topology["captionText"]
    assert "two scoped interpreter Agents" in topology["captionText"]
    assert "this public browser uses the lexical interpreter" in topology["captionText"]
    assert "AgentCore is not deployed" in topology["captionText"]

    trigger = next(segment for segment in narration["segments"] if segment["id"] == "trigger")
    assert "starts Strands synchronously" in trigger["captionText"]
    assert "EventBridge never starts or resumes it" in trigger["captionText"]
    assert "terminal delivery recorder" in trigger["captionText"]
    assert "not that editorial acted" in trigger["captionText"]

    offline = next(segment for segment in narration["segments"] if segment["id"] == "sponsor")
    assert "one tab-scoped, read-only confirmed snapshot" in offline["captionText"]
    assert "never queues a mutation" in offline["captionText"]
    assert "Reconnect reads the authoritative revision" in offline["captionText"]
    assert "explicit review" in offline["captionText"]
    assert "save the draft exactly once" in offline["captionText"]

    authority = next(segment for segment in narration["segments"] if segment["id"] == "evidence")
    assert "Demo roles are not authenticated staff" in authority["captionText"]

    description = json.loads(text("docs/submission_description.json"))
    assert "one Strands orchestrator Agent" in description["what_it_does"]
    assert "eight @tool functions" in description["what_it_does"]
    assert "two separate ToolContext.interrupt" in description["what_it_does"]
    assert "S3 persists each interrupted Strands session" in description["what_it_does"]
    assert "terminal delivery-recorder Lambda" in description["what_it_does"]
    assert "never starts or resumes the workflow" in description["what_it_does"]
    assert "two scoped interpreter Agents" in description["how_we_built_it"]
    assert "Bedrock is not active in the public browser" in description["how_we_built_it"]
    assert "AgentCore is not deployed" in description["how_we_built_it"]
    assert "Demo-role selection is not staff authentication" in description["how_we_built_it"]
    assert "no API response, approval or mutation is queued or replayed" in description["how_we_built_it"]

    tools = text("src/lasttake/agents/tools.py")
    assert len(re.findall(r"^\s*@tool(?:\(context=True\))?\s*$", tools, re.MULTILINE)) == 8
    assert tools.count("tool_context.interrupt(") == 1  # Shared helper reached by two approval tools.
    assert len(re.findall(r"^\s*@tool\(context=True\)\s*$", tools, re.MULTILINE)) == 2
    bedrock = text("src/lasttake/adapters/aws/bedrock_interpreter.py")
    assert len(re.findall(r"self\._(?:coverage|continuity) = Agent\(", bedrock)) == 2
    subscriber = text("src/lasttake/adapters/aws/event_consumer.py")
    assert "deliberately a terminal consumer" in subscriber
    assert "it never publishes an event or starts the" in subscriber

    uat = json.loads(text("frontend/UAT.testbook.json"))
    offline_case = next(row for row in uat["cases"] if row["id"] == "LT-OFFLINE")
    subscriber_case = next(row for row in uat["cases"] if row["id"] == "LT-EVENT-SUBSCRIBER")
    assert "one tab-scoped" in offline_case["requirement"].lower()
    assert "never queues or replays" in offline_case["expected_outcome"]
    assert offline_case["human_signoff"] == subscriber_case["human_signoff"] == "NOT_RUN"
    assert "terminal delivery-recorder" in subscriber_case["requirement"]
    assert "not editorial action" in subscriber_case["expected_outcome"]


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
