"""The shared options must work where the README says they work.

This file exists because of a real defect. `--bedrock` was declared only on the
top-level parser, so `lasttake checkpoint --bedrock` failed with "unrecognized
arguments" while the README documented exactly that command. Every test passed,
because every test used the other order.

That is a G1 discrepancy: the documentation and the program disagreed, and
nothing was watching the seam between them. These tests watch it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lasttake import cli

README = Path(__file__).resolve().parents[1] / "README.md"


def _parser_accepts(argv: list[str]) -> bool:
    """True when argparse accepts the arguments, without running the command."""
    import argparse
    import contextlib
    import io

    parser = cli.build_parser()
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            parser.parse_args(argv)
        except SystemExit:
            return False
    return True


SUBCOMMANDS = ["checkpoint", "approve", "late-take", "resolve", "doctor", "events"]


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_bedrock_is_accepted_after_the_subcommand(command):
    """The form a person types, and the form the README documents."""
    argv = [command, "rights"] if command == "resolve" else [command]
    assert _parser_accepts(argv + ["--bedrock"]), (
        f"`lasttake {command} --bedrock` is rejected, but that is the documented form"
    )


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_bedrock_is_still_accepted_before_the_subcommand(command):
    """The older form. Both work, so neither set of muscle memory is punished."""
    argv = [command, "rights"] if command == "resolve" else [command]
    assert _parser_accepts(["--bedrock"] + argv)


def test_an_option_before_the_subcommand_is_not_erased_by_the_default_after_it():
    """The argparse trap this design exists to avoid.

    Declaring the same option on both parsers is the obvious fix and the wrong
    one: the subparser's default fires when the flag is absent after the
    subcommand and overwrites the value given before it. `SUPPRESS` is what
    makes the pair safe, and this asserts it rather than trusting it.
    """
    parser = cli.build_parser()
    args = parser.parse_args(["--bedrock", "--workdir", "/tmp/w", "checkpoint"])
    assert args.bedrock is True, "the value given before the subcommand was erased"
    assert args.workdir == "/tmp/w"


def test_the_later_of_the_two_positions_wins_when_both_are_given():
    parser = cli.build_parser()
    args = parser.parse_args(["--workdir", "/tmp/before", "checkpoint", "--workdir", "/tmp/after"])
    assert args.workdir == "/tmp/after"


def test_defaults_survive_when_the_option_is_given_in_neither_position():
    parser = cli.build_parser()
    args = parser.parse_args(["checkpoint"])
    assert args.bedrock is False
    assert args.corpus == str(cli.DEFAULT_CORPUS)
    assert args.workdir == str(cli.DEFAULT_WORK)


def test_every_lasttake_command_in_the_readme_actually_parses():
    """Gate G1, enforced at the seam where it actually broke.

    Any ``lasttake ...`` line in a fenced block of the README has to be a
    command this program accepts. Otherwise the quickstart is fiction and the
    first thing a judge does is hit an error.
    """
    text = README.read_text(encoding="utf-8")
    commands = re.findall(r"^lasttake (.+)$", text, re.MULTILINE)
    assert commands, "expected the README to document some commands"

    failures = []
    for command in commands:
        argv = command.split()
        # Placeholders a reader is meant to substitute; parsing them is not the
        # point and would assert the wrong thing.
        argv = [a for a in argv if not a.startswith("<")]
        if not _parser_accepts(argv):
            failures.append(command)
    assert not failures, f"the README documents commands this program rejects: {failures}"
