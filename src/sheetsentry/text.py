"""Small text helpers for report messages.

A finding that reads "1 values are stored as text" undermines a tool whose
entire pitch is precision, so counts and their nouns agree everywhere.
"""

from __future__ import annotations


def plural(count: int, one: str, many: str) -> str:
    """Pick the form that agrees with `count`: 1 file, 2 files."""
    return one if abs(count) == 1 else many


def n_plural(count: int, one: str, many: str) -> str:
    """Same, with the number attached: "1 file", "5 files"."""
    return f"{count} {plural(count, one, many)}"
