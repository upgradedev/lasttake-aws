"""CI-only cross-compiled Lambda ZIP. Never imports the target or contacts AWS."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_UNPACKED = 250 * 1024 * 1024
MAX_ZIP = 50 * 1024 * 1024
REQUIRED = ("strands", "pydantic", "psycopg", "boto3", "botocore")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def identity(root, env):
    sha = git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")) or sha != env["GITHUB_SHA"]:
        raise ValueError("Checkout must match the producing workflow SHA")
    if (git(root, "status", "--porcelain", "--untracked-files=no")
            or git(root, "status", "--porcelain", "--untracked-files=all", "--", "src", "corpus")):
        raise ValueError("Tracked checkout must be clean before packaging")
    return {
        "source_commit": sha, "source_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "backend_tree": git(root, "rev-parse", "HEAD:src/lasttake"),
        "corpus_tree": git(root, "rev-parse", "HEAD:corpus"),
        "run_url": f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}",
        "run_attempt": int(env["GITHUB_RUN_ATTEMPT"]),
    }


def files_under(root):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink is not a package file: {path.name}")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path.relative_to(root).as_posix(), path


def native_machine(name, path):
    with path.open("rb") as stream:
        header = stream.read(20)
    native_name = re.search(r"\.so(?:\.|$)", name)
    if header[:4] != b"\x7fELF":
        if native_name:
            raise ValueError(f"Native library is not ELF: {name}")
        return None
    # Every native dependency must be ELF64 little-endian AArch64, not the runner's x86.
    if len(header) != 20 or header[4:6] != b"\x02\x01" or int.from_bytes(header[18:20], "little") != 183:
        raise ValueError(f"Native dependency is not arm64: {name}")
    return 183


def package(root, dependencies, report, output, source):
    # New output only: no overwrite of a prior package or receipt.
    output.mkdir(parents=True, exist_ok=False)
    entries = dict(files_under(dependencies))
    for required in REQUIRED:
        if f"{required}/__init__.py" not in entries:
            raise ValueError(f"Missing runtime dependency: {required}")
    inputs = {f"lasttake/{name}": path for name, path in files_under(root / "src/lasttake")}
    inputs.update({f"corpus/{path.name}": path for path in sorted((root / "corpus").glob("*.json"))})
    if "lasttake/app/handler.py" not in inputs or "corpus/takes.json" not in inputs:
        raise ValueError("Missing source or corpus")
    if set(inputs) & set(entries) or "_lasttake_build.json" in entries:
        raise ValueError("Dependency collides with application identity")
    entries.update(inputs)
    natives = {name: machine for name, path in entries.items() if (machine := native_machine(name, path))}
    for required in ("pydantic_core/", "psycopg_binary/"):
        if not any(name.startswith(required) for name in natives):
            raise ValueError(f"Missing native runtime dependency: {required}")
    dependency_bytes = report.read_bytes()
    resolved = json.loads(dependency_bytes)
    build = {
        "schema": "lasttake/lambda-build/v1", **source,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "runtime": "python3.12", "architecture": "arm64", "wheel_platform": "manylinux2014_aarch64",
        "dependency_mode": "bundled-including-boto3-botocore-and-distribution-metadata",
        "dependencies": sorted(({"name": item["metadata"]["name"], "version": item["metadata"]["version"]}
                                for item in resolved["install"]), key=lambda item: item["name"]),
        "dependency_report_sha256": digest(dependency_bytes),
        "input_sha256": {name: digest(path.read_bytes()) for name, path in sorted(inputs.items())},
        "native_elf_machine": natives,
        "verification_scope": "SOURCE_ONLY_CROSS_COMPILED_NOT_EXECUTED_ON_ARM64_OR_AWS",
        "runtime_environment_commit": "NOT_OBSERVED_OR_CHANGED",
        "rollout_requirement": "Owner must verify code checksum and LASTTAKE_COMMIT_SHA separately; ZIP creation does not update the environment.",
    }
    manifest = json_bytes(build)
    unpacked = sum(path.stat().st_size for path in entries.values()) + len(manifest)
    if unpacked > MAX_UNPACKED:
        raise ValueError("Package exceeds the Lambda uncompressed byte bound")
    target = output / "lasttake.zip"
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            archive.write(path, name)
        archive.writestr("_lasttake_build.json", manifest)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    data = target.read_bytes()
    if len(data) > MAX_ZIP:
        raise ValueError("Package exceeds the direct-upload ZIP byte bound")
    receipt = {**build, "zip_sha256": digest(data),
               "lambda_code_sha256_base64": base64.b64encode(hashlib.sha256(data).digest()).decode(),
               "zip_bytes": len(data), "uncompressed_bytes": unpacked, "file_count": len(entries) + 1}
    (output / "build-receipt.json").write_bytes(json_bytes(receipt))
    (output / "dependency-report.json").write_bytes(dependency_bytes)
    print(json.dumps(receipt, sort_keys=True))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dependencies", "report", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    package(ROOT, args.dependencies, args.report, args.output, identity(ROOT, os.environ))
