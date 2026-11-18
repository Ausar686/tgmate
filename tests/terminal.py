"""Helpers for asserting on terminal output."""

import re

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Return `text` without ANSI styling, which Typer adds when it detects CI (e.g. `GITHUB_ACTIONS`)."""
    return ANSI_ESCAPE.sub("", text)
