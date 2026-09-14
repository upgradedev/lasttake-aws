"""Fail the build when the README or a docs page would render broken on GitHub.

Covers README.md and every docs/*.md, the files tools/prose_gate.py reads. It does not judge
wording. Each check is a structural fault a reader would actually hit:

- a code fence that never closes swallows the rest of the page
- a link to #anchor that no heading on that page produces goes nowhere
- a relative link or image whose file does not exist is a 404 in the repository view
- a table whose delimiter row does not match its header is not rendered as a table, and a body
  row with a different cell count loses or pads cells (GitHub splits cells on every unescaped
  pipe, even inside backticks)
- a mermaid block that does not open with a diagram type shows an error box instead of a diagram
- a <details> without its </details> hides everything after it
- a markdown page in a docs subfolder escapes the prose gate, whose glob is flat

Mermaid syntax past the diagram type needs a browser to parse, so it is not checked here.

Run: python tools/docs_gate.py
"""

from __future__ import annotations

import pathlib
import re
import sys

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
LINK = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_REF = re.compile(r"<(?:img|a|source)\b[^>]*?\b(?:src|href|srcset)=\"([^\"]+)\"", re.I)
HTML_ID = re.compile(r"\b(?:id|name)=\"([^\"]+)\"")
DELIMITER_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")
MERMAID_TYPES = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2",
    "erDiagram", "gantt", "pie", "journey", "gitGraph", "mindmap", "timeline", "quadrantChart",
    "requirementDiagram", "C4Context", "sankey-beta", "xychart-beta", "block-beta",
)


def slug(heading: str) -> str:
    """GitHub's heading anchor: link text kept, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def cells(row: str) -> int:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return len(re.split(r"(?<!\\)\|", body))


def outside_fences(lines: list[str]) -> list[tuple[int, str, bool]]:
    """Each line with its number and whether it sits inside a fenced block."""
    marked, fence = [], None
    for number, line in enumerate(lines, start=1):
        match = FENCE.match(line)
        if fence is None and match:
            fence = (match.group(1)[0], len(match.group(1)), number)
            marked.append((number, line, True))
            continue
        if fence and match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
            fence = None
            marked.append((number, line, True))
            continue
        marked.append((number, line, fence is not None))
    return marked


def anchors_of(text: str) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for _, line, fenced in outside_fences(text.splitlines()):
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            base = slug(match.group(2))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
        found.update(HTML_ID.findall(line))
    return found


def problems_in(path: pathlib.Path, root: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    name = path.relative_to(root).as_posix()
    found: list[str] = []
    marked = outside_fences(lines)
    own_anchors = anchors_of(text)

    # Fences: the last opener with no closer.
    fence = None
    for number, line in enumerate(lines, start=1):
        match = FENCE.match(line)
        if fence is None and match:
            fence = (match.group(1)[0], len(match.group(1)), number, match.group(2).strip())
            continue
        if fence and match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
            fence = None
    if fence:
        found.append(f"{name}:{fence[2]}: code fence never closes")

    # Mermaid blocks must open with a diagram type.
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if match and match.group(2).strip().lower() == "mermaid":
            body = [l.strip() for l in lines[index + 1:] if not FENCE.match(l)][:40]
            first = next((l for l in body if l and not l.startswith("%%")), "")
            if not first.startswith(MERMAID_TYPES):
                found.append(f"{name}:{index + 1}: mermaid block does not open with a diagram type")

    details_open = details_close = 0
    table_header: tuple[int, int] | None = None
    for number, line, fenced in marked:
        if fenced:
            table_header = None
            continue
        scan = re.sub(r"`[^`]*`", "", line)
        details_open += len(re.findall(r"<details\b", scan, re.I))
        details_close += len(re.findall(r"</details>", scan, re.I))

        for target in LINK.findall(scan) + HTML_REF.findall(scan):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            file_part, _, anchor = target.partition("#")
            if not file_part:
                if anchor and anchor not in own_anchors:
                    found.append(f"{name}:{number}: no heading on this page makes #{anchor}")
                continue
            resolved = (path.parent / file_part).resolve()
            if not resolved.exists():
                found.append(f"{name}:{number}: link target does not exist: {file_part}")
            elif anchor and resolved.suffix == ".md" and anchor not in anchors_of(resolved.read_text(encoding="utf-8")):
                found.append(f"{name}:{number}: {file_part} has no heading that makes #{anchor}")

        # Tables: header row, then a delimiter row with the same cell count, then body rows.
        stripped = line.strip()
        previous = lines[number - 2] if number >= 2 else ""
        if "|" in stripped and all(DELIMITER_CELL.match(c) for c in re.split(r"(?<!\\)\|", stripped.strip("|"))) and "-" in stripped:
            if "|" in previous:
                header = cells(previous)
                if cells(stripped) != header:
                    found.append(f"{name}:{number}: table delimiter has {cells(stripped)} cells, header has {header}")
                table_header = (number, header)
            continue
        if table_header and stripped and "|" in stripped:
            if cells(stripped) != table_header[1]:
                found.append(f"{name}:{number}: table row has {cells(stripped)} cells, header has {table_header[1]}")
        elif not stripped or "|" not in stripped:
            table_header = None

    if details_open != details_close:
        found.append(f"{name}: {details_open} <details> but {details_close} </details>")
    return found


def targets(root: pathlib.Path) -> list[pathlib.Path]:
    files = [root / "README.md"]
    files += sorted((root / "docs").glob("*.md"))
    return [f for f in files if f.is_file()]


def problems(root: pathlib.Path) -> list[str]:
    found: list[str] = []
    for nested in sorted((root / "docs").glob("*/**/*.md")):
        found.append(f"{nested.relative_to(root).as_posix()}: markdown in a docs subfolder escapes tools/prose_gate.py; keep docs flat")
    for path in targets(root):
        found.extend(problems_in(path, root))
    return found


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    files = targets(root)
    if not files:
        print("no README or docs pages found, which is itself wrong")
        return 1
    found = problems(root)
    if found:
        print("README or docs would render broken:")
        for problem in found:
            print(f"  {problem}")
        return 1
    print(f"docs gate passed over {len(files)} file(s): " + ", ".join(f.relative_to(root).as_posix() for f in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
