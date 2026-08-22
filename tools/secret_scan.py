"""Scan tracked files for committed credentials.

Lives in a file rather than inline in the workflow for one reason: a scanner
written inline matches its own pattern definition and fails on itself, which
teaches everyone to ignore it. This file excludes exactly one path, its own,
and nothing else.

Run: python tools/secret_scan.py
"""

from __future__ import annotations

import re
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


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z"], text=True)
    return [Path(p) for p in out.split("\0") if p]


def main() -> int:
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
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                if re.search(pattern, line):
                    findings.append(f"{path}:{line_no}: {label}")

    if findings:
        print("possible credentials committed:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"secret scan clean over {len(tracked_files())} tracked file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
