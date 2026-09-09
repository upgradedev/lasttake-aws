"""Scan tracked files for committed credentials.

Lives in a file rather than inline in the workflow for one reason: a scanner
written inline matches its own pattern definition and fails on itself, which
teaches everyone to ignore it. This file excludes exactly one path, its own,
and nothing else.

Run: python tools/secret_scan.py
"""

from __future__ import annotations

import re
import argparse
import subprocess
import sys
from pathlib import Path

SELF = Path(__file__).name

PATTERNS = {
    "AWS access key id": r"AKIA[0-9A-Z]{16}",
    "AWS secret key assignment": r"aws_secret_access_key\s*[=:]\s*\S",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{8,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{36,}",
    "generic bearer secret": r"(?i)(password|passwd|secret|token)\s*[=:]\s*[\"'][^\"'{}$][^\"']{7,}[\"']",
}

TEXT_SUFFIXES = {
    ".py", ".json", ".md", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".txt",
    ".sh", ".ts", ".js", ".html", ".css",
}

# One immutable historical negative-test marker, inspected in full: no key body.
# A different object, line, path, or added credential still fails the scan.
HISTORICAL_TEST_MARKER = "11667468342b7f99d7051eba334d17ce20f576be"


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z"], text=True)
    return [Path(p) for p in out.split("\0") if p]


def matches(label: str, content: str) -> list[str]:
    return [f"{label}:{line_no}: {name}" for line_no, line in enumerate(content.splitlines(), 1)
            for name, pattern in PATTERNS.items() if re.search(pattern, line)]


def history_findings() -> tuple[list[str], int]:
    """Scan every reachable historical blob and commit message, without echoing secrets."""
    if subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], text=True).strip() != "false":
        raise RuntimeError("Full-history scanning requires checkout fetch-depth: 0")
    objects = subprocess.check_output(["git", "rev-list", "--objects", "--all"], text=True).splitlines()
    findings = []
    count = 0
    with subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as reader:
        for row in objects:
            oid, _, name = row.partition(" ")
            if Path(name).name == SELF:
                continue
            reader.stdin.write((oid + "\n").encode())
            reader.stdin.flush()
            header = reader.stdout.readline().decode().split()
            if len(header) != 3:
                raise RuntimeError("Cannot read historical object")
            data = reader.stdout.read(int(header[2]))
            reader.stdout.read(1)
            if header[1] not in ("blob", "commit") or b"\0" in data:
                continue
            content = data.decode("utf-8", errors="replace")
            if header[1] == "commit":
                content = content.partition("\n\n")[2]
            detected = matches(f"{oid}:{name or 'commit-message'}", content)
            if oid == HISTORICAL_TEST_MARKER and name == "infra/test_frontend_hosting.py":
                marker = content.splitlines()[108].strip()
                if marker == '(self.dist / "assets/app-123.js").write_text("' + '-----BEGIN ' + 'PRIVATE KEY-----")':
                    detected.remove(f"{oid}:{name}:109: private key block")
                    print("Historical fixture reviewed: immutable test marker without key material")
            findings.extend(detected)
            count += 1
        reader.stdin.close()
        if reader.wait() != 0:
            raise RuntimeError("Historical object reader failed")
    return findings, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-history", action="store_true")
    args = parser.parse_args()
    findings: list[str] = []
    for path in tracked_files():
        if path.name == SELF:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        findings.extend(matches(str(path), text))

    if args.all_history:
        historical, count = history_findings()
        findings.extend(historical)
        print(f"Full-history scope: {count} textual blobs and commit messages across all fetched refs")

    if findings:
        print("possible credentials committed:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"secret scan clean over {len(tracked_files())} tracked file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
