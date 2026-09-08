"""Fail the build when judge-facing prose reads as machine-written.

Lives in a file for the same reason the secret scanner does. Written inline in
the workflow, this check had to escape regular expressions through a YAML
literal block and a shell heredoc at once; one pass turned every `\\b` into a
literal backspace character and the workflow stopped parsing. A gate that is
hard to write correctly is a gate that ends up wrong.

Covers `README.md`, everything in `docs/`, and the single page the live URL
serves. The first version checked only the README, so the assurance tables were
written under no gate at all; the second still skipped the page, and an em dash
sat in its `<title>` where every judge's browser tab would show it.

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

#: Sentences this product must never print, from the boundaries in CLAUDE.md:
#: it may not declare a scene legally cleared, safe or creatively complete, and
#: it may never infer a pass from absent evidence.
#:
#: This list exists because a feature shipped to the live URL printing
#: "CLEAR TO SHOOT. All labor, turnaround, and technical rules verified." from
#: three hardcoded conditionals in the browser. It called no API and involved no
#: agent, and it sat there for six days behind a green uptime check, because
#: that check speaks to the API and never reads what the page says.
FORBIDDEN_VERDICTS = (
    "clear to shoot",
    "cleared to shoot",
    "all rules verified",
    "rules verified",
    "no issues found",
    "safe to wrap",
    "legally cleared",
)

EM_DASH = "—"


#: The same words appear legitimately when the document is saying the product
#: does *not* do this, or asking the question a supervisor asks. "is this scene
#: safe to wrap" is the job; "safe to wrap" as an assertion is the failure. The
#: rule is about assertions, so a line that disclaims or asks is not one.
#: Written as a plain tuple and matched with `in`, never as a regular
#: expression. This file already carries one trap about a `\b` that became a
#: literal backspace when it passed through a shell, and writing this rule
#: reproduced it: the pattern compiled, matched nothing, and the gate went
#: quietly green. A check that cannot fail is worse than no check.
DISCLAIMERS = (
    "never", "not", "cannot", "refus", "withhold", "forbid", "is this",
    "whether", "would be",
)


def _disclaimed(line: str, text: str, index: int) -> bool:
    """True when the line is disclaiming the clearance rather than giving it.

    "is this scene safe to wrap" is the question a supervisor asks and the
    job this product does. "safe to wrap" as an assertion is the failure.
    The rule is about assertions, so a line that asks or denies is not one.
    """
    lines = text.splitlines()
    window = [line.lower()]
    if index >= 2:
        window.append(lines[index - 2].lower())
    return any(word in candidate for candidate in window for word in DISCLAIMERS)


def targets() -> list[pathlib.Path]:
    files = [pathlib.Path("README.md")]
    files += sorted(pathlib.Path("docs").glob("*.md"))
    files += sorted(pathlib.Path("src/lasttake/app/static").glob("*.html"))
    return [f for f in files if f.is_file()]


def problems_in(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found: list[str] = []

    # The page is prose plus code. A banned marketing word inside a CSS
    # property or a JavaScript identifier is not prose, so the word checks skip
    # anything that is not visible text; the em dash check does not, because an
    # em dash has no business anywhere in this repository.
    markup = path.suffix == ".html"

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
        for verdict in FORBIDDEN_VERDICTS:
            if verdict in line.lower() and not _disclaimed(line, text, index):
                found.append(
                    f"{path}:{index}: {verdict!r} is a clearance this product may "
                    "never give. Absent evidence is a finding, never a pass"
                )
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
