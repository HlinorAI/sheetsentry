"""Family SD - data and exchange integrity.

This is what breaks the receiving system when a spreadsheet arrives from
another company. It is the first-class family: our first user hurts here.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterator

from ..finding import Finding, Severity
from ..text import n_plural
from ..workbook import Book, Cell, Sheet
from . import check

# Written as escapes on purpose. These characters are invisible by
# definition: as raw literals they cannot be reviewed, and one careless
# editor or formatter silently removes the very thing we detect.
INVISIBLE = {
    "\u00a0": "a non-breaking space",
    "\u202f": "a narrow non-breaking space",
    "\u200b": "a zero-width space",
    "\ufeff": "a byte order mark",
    "\t": "a tab",
}

_NUMERIC_TEXT_RE = re.compile(
    r"^[\s\u00a0\u202f]*[-+]?[\d\s\u00a0\u202f]{1,20}([.,]\d+)?[\s\u00a0\u202f]*%?[\s\u00a0\u202f]*$"
)
# dollar, euro, pound, rouble, yen
_CURRENCY_RE = re.compile("[$\u20ac\u00a3\u20bd\u00a5]")
_DATE_TEXT_RE = re.compile(
    r"^\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})\s*$"
)

MAX_EXAMPLES = 5


def _examples(cells: list[Cell]) -> list[str]:
    return [c.coord for c in cells[:MAX_EXAMPLES]]


def _data_columns(sheet: Sheet) -> Iterator[tuple[int, int, list[Cell]]]:
    """(column, first data row, non-empty cells) for every column."""
    header = sheet.header_row()
    start = (header + 1) if header else 1
    for col in range(1, sheet.max_col + 1):
        cells = [c for c in sheet.column_cells(col, start) if not c.is_empty]
        if cells:
            yield col, start, cells


def _looks_numeric(text: str) -> bool:
    stripped = _CURRENCY_RE.sub("", text).strip()
    if not stripped:
        return False
    digits = re.sub(r"[^\d]", "", stripped)
    if not digits:
        return False
    if digits.startswith("0") and len(digits) > 1:
        return False  # a part number like 00123 is legitimately text
    if len(digits) >= 11:
        return False  # phone number, tax id, barcode
    return bool(_NUMERIC_TEXT_RE.match(stripped))


@check(
    "SD001",
    "Numbers stored as text",
    Severity.WARNING,
    "A column holds numbers in text form: aggregates skip them, imports read zero",
)
def sd001(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        for col, _, cells in _data_columns(sheet):
            numeric = [c for c in cells if c.is_numeric_constant]
            if not numeric:
                continue  # an all-text column is a deliberate choice
            suspects = [c for c in cells if c.is_text and _looks_numeric(str(c.value))]
            if not suspects:
                continue
            yield Finding(
                rule="SD001",
                title="Numbers stored as text",
                severity=Severity.WARNING,
                message=(
                    f"Column {sheet.column_label(col)}: "
                    f"{n_plural(len(suspects), 'value is', 'values are')} stored as text "
                    f"while {n_plural(len(numeric), 'neighbour is', 'neighbours are')} "
                    "a real number. Aggregates will not see these cells."
                ),
                sheet=sheet.name,
                cells=_examples(suspects),
                evidence=repr(suspects[0].value),
                count=len(suspects),
            )


@check(
    "SD002",
    "Invisible characters in values",
    Severity.WARNING,
    "Edge whitespace and non-breaking spaces break key matching",
)
def sd002(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        for col, _, cells in _data_columns(sheet):
            dirty: dict[str, list[Cell]] = defaultdict(list)
            for cell in cells:
                if not cell.is_text:
                    continue
                text = str(cell.value)
                for char, name in INVISIBLE.items():
                    if char in text:
                        dirty[name].append(cell)
                if text != text.strip():
                    dirty["leading or trailing whitespace"].append(cell)
                if "\n" in text:
                    dirty["a line break"].append(cell)

            for problem, affected in dirty.items():
                newline_only = problem == "a line break"
                yield Finding(
                    rule="SD002",
                    title="Invisible characters in values",
                    severity=Severity.INFO if newline_only else Severity.WARNING,
                    message=(
                        f"Column {sheet.column_label(col)}: "
                        f"{n_plural(len(affected), 'value contains', 'values contain')} "
                        f"{problem}. "
                        + (
                            "Inside descriptions this is normal."
                            if newline_only
                            else "Such a value will not match an outwardly identical one."
                        )
                    ),
                    sheet=sheet.name,
                    cells=_examples(affected),
                    evidence=repr(affected[0].value),
                    count=len(affected),
                )


@check(
    "SD003",
    "Duplicates in a key column",
    Severity.ERROR,
    "Repeats in a key column: the receiver overwrites a row or creates a duplicate",
)
def sd003(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        for col, _, cells in _data_columns(sheet):
            values = [c for c in cells if not c.is_formula and not c.is_blank_marker]
            if len(values) < 20:
                continue

            counter = Counter(str(c.value).strip() for c in values)
            duplicates = {v: n for v, n in counter.items() if n > 1}
            if not duplicates:
                continue

            by_name = sheet.looks_like_key_column(col)
            unique_ratio = len(counter) / len(values)
            if not by_name and unique_ratio < 0.9:
                continue

            affected = [c for c in values if str(c.value).strip() in duplicates]
            reason = (
                f"named '{sheet.header_name(col)}'"
                if by_name
                else f"{unique_ratio:.0%} of values are unique, which is typical of a key"
            )
            worst = max(duplicates.items(), key=lambda kv: kv[1])
            yield Finding(
                rule="SD003",
                title="Duplicates in a key column",
                severity=Severity.ERROR if by_name else Severity.WARNING,
                message=(
                    f"Column {sheet.column_label(col)} looks like a key ({reason}) but holds "
                    f"{n_plural(len(duplicates), 'duplicated value', 'duplicated values')}."
                ),
                sheet=sheet.name,
                cells=_examples(affected),
                evidence=f"{worst[0]!r} appears {n_plural(worst[1], 'time', 'times')}",
                count=len(affected),
            )


@check(
    "SD004",
    "Mixed types in a column",
    Severity.WARNING,
    "A handful of foreign-typed cells among otherwise uniform data",
)
def sd004(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        for col, _, cells in _data_columns(sheet):
            meaningful = [c for c in cells if not c.is_formula and not c.is_blank_marker]
            if len(meaningful) < 10:
                continue

            def kind(cell: Cell) -> str:
                if cell.is_date:
                    return "date"
                if isinstance(cell.value, bool):
                    return "boolean"
                if isinstance(cell.value, (int, float)):
                    return "number"
                return "text"

            groups: dict[str, list[Cell]] = defaultdict(list)
            for cell in meaningful:
                groups[kind(cell)].append(cell)
            if len(groups) < 2:
                continue

            dominant = max(groups, key=lambda k: len(groups[k]))
            for name, affected in groups.items():
                if name == dominant:
                    continue
                share = len(affected) / len(meaningful)
                if not (0 < share <= 0.2):
                    continue  # a 40/60 split is a deliberately mixed column
                yield Finding(
                    rule="SD004",
                    title="Mixed types in a column",
                    severity=Severity.WARNING,
                    message=(
                        f"Column {sheet.column_label(col)} is mostly '{dominant}', but "
                        f"{n_plural(len(affected), 'cell is', 'cells are')} '{name}' "
                        f"({share:.0%})."
                    ),
                    sheet=sheet.name,
                    cells=_examples(affected),
                    evidence=repr(affected[0].value),
                    count=len(affected),
                )


@check(
    "SD005",
    "Dates stored as text",
    Severity.WARNING,
    "Dates as strings: the import either fails or swaps day and month",
)
def sd005(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        for col, _, cells in _data_columns(sheet):
            text_dates = [c for c in cells if c.is_text and _DATE_TEXT_RE.match(str(c.value))]
            if not text_dates:
                continue
            real_dates = [c for c in cells if c.is_date]

            ambiguous = True
            for cell in text_dates:
                parts = re.split(r"[./-]", str(cell.value).strip())
                if len(parts) == 3 and len(parts[0]) <= 2:
                    try:
                        if int(parts[0]) > 12:
                            ambiguous = False
                            break
                    except ValueError:
                        pass

            note = (
                " Day and month order cannot be told from this column, so the receiver "
                "may read them the other way round."
                if ambiguous
                else ""
            )
            mixed = (
                " The same column also holds "
                f"{n_plural(len(real_dates), 'cell', 'cells')} with real dates."
                if real_dates
                else ""
            )
            yield Finding(
                rule="SD005",
                title="Dates stored as text",
                severity=Severity.WARNING,
                message=(
                    f"Column {sheet.column_label(col)}: "
                    f"{n_plural(len(text_dates), 'date is', 'dates are')} stored as text."
                    f"{mixed}{note}"
                ),
                sheet=sheet.name,
                cells=_examples(text_dates),
                evidence=repr(text_dates[0].value),
                count=len(text_dates),
            )
