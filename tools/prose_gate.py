"""Fail the build when judge-facing prose reads as machine-written.

Lives in a file for the same reason the secret scanner does. Written inline in
the workflow, this check had to escape regular expressions through a YAML
literal block and a shell heredoc at once; one pass turned every `\\b` into a
literal backspace character and the workflow stopped parsing. A gate that is
hard to write correctly is a gate that ends up wrong.

Covers `README.md` and everything in `docs/`. The first version checked only
the README, so the assurance tables were written under no gate at all.

Run: python tools/prose_gate.py
"""

from __future__ import annotations

import pathlib
import re
import sys

#: Whole words, never prefixes. The banned item is the marketing adjective
#: "robust"; "robustness" is the title of EU AI Act Article 15, and citing a
#: regulation accurately is not a style problem.
BANNED_WORDS = ("leverage", "robust", "seamless", "comprehensive", "delve")

BANNED_PHRASES = ("in today's world",)

#: Not ours to claim. Whether a system meets a regulation is decided by an
#: assessment body, and writing either word would be us awarding it to
#: ourselves. This is the same rule as never letting a self-awarded score reach
#: a judge-facing document.
FORBIDDEN_CLAIMS = ("compliant", "conformity")

EM_DASH = "—"


def targets() -> list[pathlib.Path]:
    files = [pathlib.Path("README.md")]
    files += sorted(pathlib.Path("docs").glob("*.md"))
    return [f for f in files if f.is_file()]


def problems_in(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found: list[str] = []

    for index, line in enumerate(text.splitlines(), start=1):
        if EM_DASH in line:
            found.append(f"{path}:{index}: em dash")
        for word in BANNED_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", line, re.I):
                found.append(f"{path}:{index}: banned word {word!r}")
        for phrase in BANNED_PHRASES:
            if phrase in line.lower():
                found.append(f"{path}:{index}: banned phrase {phrase!r}")
        for word in FORBIDDEN_CLAIMS:
            if re.search(rf"\b{word}\b", line, re.I):
                found.append(f"{path}:{index}: forbidden claim {word!r}")
    return found


def main() -> int:
    files = targets()
    if not files:
        print("no judge-facing prose found, which is itself wrong")
        return 1

    found: list[str] = []
    for path in files:
        found.extend(problems_in(path))

    if found:
        print("judge-facing prose reads as generated:")
        for problem in found:
            print(f"  {problem}")
        return 1

    print(f"prose gate passed over {len(files)} file(s): " + ", ".join(str(f) for f in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
