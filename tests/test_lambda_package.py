"""CI-only fixtures validate package identity without installing target wheels."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lambda_package", ROOT / "tools/package_lambda.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def candidate(tmp_path):
    root, deps = tmp_path / "source", tmp_path / "deps"
    put(root, "src/lasttake/app/handler.py", b"# exact source\n")
    put(root, "corpus/takes.json", b'[{"take_id":"T-source"}]')
    for name in P.REQUIRED:
        put(deps, f"{name}/__init__.py", b"# fixture only\n")
    elf = b"\x7fELF\x02\x01" + b"\0" * 12 + (183).to_bytes(2, "little")
    put(deps, "pydantic_core/core.so", elf)
    put(deps, "psycopg_binary/pq.so", elf)
    put(deps, "strands_agents-1.0.dist-info/METADATA", b"Name: strands-agents\nVersion: 1.0\n")
    put(deps, "strands/__pycache__/cached.pyc", b"excluded")
    report = put(tmp_path, "report.json", b'{"install":[{"metadata":{"name":"strands-agents","version":"1.0"}}]}')
    source = {"source_commit": "a" * 40, "backend_tree": "b" * 40, "corpus_tree": "c" * 40}
    return root, deps, report, tmp_path / "artifact", source


def test_zip_preserves_exact_source_corpus_native_deps_and_truthful_receipt(candidate):
    receipt = P.package(*candidate)
    root, _, report, output, source = candidate
    data = (output / "lasttake.zip").read_bytes()
    assert receipt["zip_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["lambda_code_sha256_base64"] == base64.b64encode(hashlib.sha256(data).digest()).decode()
    assert receipt["source_commit"] == source["source_commit"]
    assert receipt["dependency_report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert (output / "dependency-report.json").read_bytes() == report.read_bytes()
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    with zipfile.ZipFile(output / "lasttake.zip") as archive:
        assert archive.read("lasttake/app/handler.py") == (root / "src/lasttake/app/handler.py").read_bytes()
        assert archive.read("corpus/takes.json") == (root / "corpus/takes.json").read_bytes()
        assert "strands_agents-1.0.dist-info/METADATA" in archive.namelist()
        assert "boto3/__init__.py" in archive.namelist() and "botocore/__init__.py" in archive.namelist()
        assert not any("__pycache__" in name for name in archive.namelist())
        embedded = json.loads(archive.read("_lasttake_build.json"))
        assert embedded["source_commit"] == receipt["source_commit"]
        assert embedded["runtime_environment_commit"] == "NOT_OBSERVED_OR_CHANGED"
        assert embedded["verification_scope"] == "SOURCE_ONLY_CROSS_COMPILED_NOT_EXECUTED_ON_ARM64_OR_AWS"
        assert set(embedded["native_elf_machine"].values()) == {183}
        assert receipt["uncompressed_bytes"] == sum(item.file_size for item in archive.infolist())
        for name, expected in receipt["input_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
    with pytest.raises(FileExistsError):
        P.package(*candidate)


@pytest.mark.parametrize("bad", [b"not ELF", b"\x7fELF\x02\x01" + b"\0" * 12 + (62).to_bytes(2, "little")])
def test_wrong_or_fake_native_library_refuses_upload_candidate(candidate, bad):
    put(candidate[1], "psycopg_binary/pq.so", bad)
    with pytest.raises(ValueError, match="Native"):
        P.package(*candidate)


@pytest.mark.parametrize("kind", ["collision", "missing-runtime", "missing-native", "unpacked", "zip"])
def test_missing_ambiguous_or_oversize_package_fails_closed(candidate, monkeypatch, kind):
    if kind == "collision":
        put(candidate[1], "lasttake/app/handler.py", b"old code")
    elif kind == "missing-runtime":
        (candidate[1] / "boto3/__init__.py").unlink()
    elif kind == "missing-native":
        (candidate[1] / "psycopg_binary/pq.so").unlink()
    else:
        monkeypatch.setattr(P, "MAX_UNPACKED" if kind == "unpacked" else "MAX_ZIP", 1)
    with pytest.raises(ValueError):
        P.package(*candidate)
    assert not (candidate[3] / "build-receipt.json").exists()


@pytest.mark.parametrize("mismatch,dirty", [(True, False), (False, True), (False, False)])
def test_ci_identity_is_observed_not_assumed(monkeypatch, mismatch, dirty):
    def git(_, *args):
        return (" M source.py" if dirty else "") if args[0] == "status" else "a" * 40
    monkeypatch.setattr(P, "git", git)
    env = {"GITHUB_SHA": ("b" if mismatch else "a") * 40, "GITHUB_RUN_ID": "123",
           "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_REPOSITORY": "upgradedev/lasttake-aws"}
    if mismatch or dirty:
        with pytest.raises(ValueError):
            P.identity(ROOT, env)
    else:
        assert P.identity(ROOT, env)["run_attempt"] == 2


def test_package_job_is_branch_only_read_only_and_never_invokes_release():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    # Stop at ANY sibling job, not a formerly adjacent job name. A separate
    # manually gated supervisor must not be mistaken for package-job authority.
    job = re.split(r"\n  [A-Za-z_][A-Za-z0-9_-]*:\n",
                   workflow.split("  lambda-package:\n", 1)[1], maxsplit=1)[0]
    assert "needs: [test, hero]" in job
    assert "github.ref == 'refs/heads/codex/security-boundaries-20260910'" in job
    assert "github.ref == 'refs/heads/codex/history-pagination-20260910'" in job
    assert "contents: read" in job and "persist-credentials: false" in job
    assert "contents: write" not in job
    assert "manylinux2014_aarch64" in job and "--only-binary=:all:" in job
    assert "tools/package_lambda.py" in job and "actions/upload-artifact@v4" in job
    assert "retention-days: 90" in job and "overwrite: false" in job
    for forbidden in ("secrets.", "id-token:", "aws-actions/", "aws ", "deploy.yml", "lasttake checkpoint"):
        assert forbidden not in job
