"""Count agreement is part of report quality, not cosmetics."""

from __future__ import annotations

import pytest

from sheetsentry.text import n_plural, plural


@pytest.mark.parametrize(
    "count,expected",
    [(0, "findings"), (1, "finding"), (2, "findings"), (11, "findings"), (21, "findings")],
)
def test_plural_forms(count, expected):
    assert plural(count, "finding", "findings") == expected


def test_n_plural_includes_the_number():
    assert n_plural(3, "file", "files") == "3 files"


def test_n_plural_agrees_with_a_verb():
    assert n_plural(1, "value is", "values are") == "1 value is"
    assert n_plural(4, "value is", "values are") == "4 values are"
