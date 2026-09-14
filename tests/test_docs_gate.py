"""The docs gate must refuse each structural fault it names, and pass the repository as it is.

Each fixture is the smallest page that shows one fault the way GitHub would show it to a reader.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("docs_gate", ROOT / "tools/docs_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def page(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_repository_passes():
    assert gate.problems(ROOT) == []


def test_a_clean_page_passes(tmp_path):
    page(tmp_path, "docs/infra.md", "# Infra\n\n## What is deployed, and what it costs\n")
    page(tmp_path, "docs/diagram.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
    page(tmp_path, "README.md", "\n".join([
        "# Title",
        "## What \"covered\" rests on",
        "## Notes",
        "## Notes",
        "[a](#what-covered-rests-on) [b](#notes-1) [c](docs/infra.md#what-is-deployed-and-what-it-costs)",
        '<img src="docs/diagram.svg" alt="x">',
        "| a | b |",
        "|---|---|",
        "| `x \\| y` | 2 |",
        "```mermaid",
        "%% comment",
        "flowchart LR",
        "  A --> B",
        "```",
        "<details><summary>More</summary>",
        "",
        "Hidden.",
        "",
        "</details>",
        "",
    ]))
    assert gate.problems(tmp_path) == []


def test_a_fence_that_never_closes_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n\n```bash\nlasttake checkpoint\n")
    assert any("code fence never closes" in p for p in gate.problems(tmp_path))


def test_an_anchor_no_heading_makes_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n\n[jump](#nowhere)\n")
    assert any("#nowhere" in p for p in gate.problems(tmp_path))


def test_a_link_to_a_missing_file_or_heading_is_refused(tmp_path):
    page(tmp_path, "docs/a.md", "# A\n")
    page(tmp_path, "README.md", "# T\n\n[x](docs/missing.md) [y](docs/a.md#no-such-section)\n")
    found = gate.problems(tmp_path)
    assert any("does not exist: docs/missing.md" in p for p in found)
    assert any("no heading that makes #no-such-section" in p for p in found)


def test_an_unescaped_pipe_inside_backticks_still_splits_a_cell(tmp_path):
    page(tmp_path, "README.md", "# T\n\n| a | b |\n|---|---|\n| `x | y` | 2 |\n")
    assert any("table row has 3 cells, header has 2" in p for p in gate.problems(tmp_path))


def test_a_delimiter_that_does_not_match_its_header_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n\n| a | b | c |\n|---|---|\n| 1 | 2 | 3 |\n")
    assert any("table delimiter has 2 cells, header has 3" in p for p in gate.problems(tmp_path))


def test_a_mermaid_block_without_a_diagram_type_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n\n```mermaid\nA --> B\n```\n")
    assert any("does not open with a diagram type" in p for p in gate.problems(tmp_path))


def test_an_unclosed_details_block_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n\n<details><summary>More</summary>\n\nHidden.\n")
    assert any("<details>" in p for p in gate.problems(tmp_path))


def test_markdown_in_a_docs_subfolder_is_refused(tmp_path):
    page(tmp_path, "README.md", "# T\n")
    page(tmp_path, "docs/deep/page.md", "# Deep\n")
    assert any("escapes tools/prose_gate.py" in p for p in gate.problems(tmp_path))


def test_links_inside_code_are_not_followed(tmp_path):
    page(tmp_path, "README.md", "# T\n\n`[x](missing.md)`\n\n```\n[y](#nowhere)\n```\n")
    assert gate.problems(tmp_path) == []
