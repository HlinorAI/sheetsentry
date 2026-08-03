"""Family DF - differences between two versions of a file.

The guiding decision: **values are not diffed, structure is.** In a weekly
feed the numbers change every time, so reporting them is noise that buries
the signal. What changes rarely, and always deliberately, is the shape of
the file: which columns exist, in which order, and which cells hold formulas.

A known limitation follows from comparing by cell coordinate: inserting a
row shifts everything below it, and every shifted formula looks changed.
That is why the cell-level rules aggregate per sheet - a shifted sheet
produces one line with a count, not four hundred findings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterator

from .. import formula as F
from ..finding import Finding, Severity
from ..text import n_plural
from ..workbook import Book, Sheet
from . import diff_check

MAX_EXAMPLES = 5


def _paired_sheets(old: Book, new: Book) -> Iterator[tuple[Sheet, Sheet]]:
    """Sheets present in both workbooks, matched by name."""
    for new_sheet in new.sheets:
        old_sheet = old.sheet(new_sheet.name)
        if old_sheet is not None:
            yield old_sheet, new_sheet


def _headers(sheet: Sheet) -> dict[int, str]:
    """Column index to header name, when a header row is recognised."""
    row = sheet.header_row()
    if row is None:
        return {}
    result: dict[int, str] = {}
    for col in range(1, sheet.max_col + 1):
        cell = sheet.cell(row, col)
        if cell is not None and cell.is_text and str(cell.value).strip():
            result[col] = str(cell.value).strip()
    return result


def _letter(col: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(col)


def _aggregate(
    rule: str,
    title: str,
    severity: Severity,
    sheet: str,
    cells: list[str],
    message: str,
    evidence: str | None = None,
) -> Finding:
    return Finding(
        rule=rule,
        title=title,
        severity=severity,
        message=message,
        sheet=sheet,
        cells=cells[:MAX_EXAMPLES],
        evidence=evidence,
        count=len(cells),
    )


@diff_check(
    "DF010",
    "Schema drift",
    Severity.ERROR,
    "Columns reordered, renamed, added or removed between versions",
)
def df010(old: Book, new: Book) -> Iterator[Finding]:
    """The decisive check for the file-exchange scenario.

    A receiver that reads by column index does not notice a reordering: it
    keeps importing, writing prices into the quantity field. This is the
    failure that arrives most quietly, so reordering is an error even though
    every individual column still exists.
    """
    for old_sheet, new_sheet in _paired_sheets(old, new):
        old_map = _headers(old_sheet)
        new_map = _headers(new_sheet)
        if not old_map or not new_map:
            continue

        old_names = [old_map[c] for c in sorted(old_map)]
        new_names = [new_map[c] for c in sorted(new_map)]
        if old_names == new_names:
            continue

        # A column whose position kept a name that exists nowhere else is a
        # rename rather than an unrelated removal plus addition.
        renamed: list[tuple[int, str, str]] = []
        for col in sorted(set(old_map) & set(new_map)):
            was, now = old_map[col], new_map[col]
            if was != now and was not in new_names and now not in old_names:
                renamed.append((col, was, now))

        renamed_old = {was for _, was, _ in renamed}
        renamed_new = {now for _, _, now in renamed}
        removed = [n for n in old_names if n not in new_names and n not in renamed_old]
        added = [n for n in new_names if n not in old_names and n not in renamed_new]

        for col, was, now in renamed:
            yield Finding(
                rule="DF010",
                title="Schema drift",
                severity=Severity.ERROR,
                message=(
                    f"Column {_letter(col)} was renamed from '{was}' to '{now}'. "
                    "A receiver matching columns by name will stop finding this field."
                ),
                sheet=new_sheet.name,
                cells=[f"{_letter(col)}{new_sheet.header_row() or 1}"],
                evidence=f"'{was}' -> '{now}'",
            )

        if removed:
            yield Finding(
                rule="DF010",
                title="Schema drift",
                severity=Severity.ERROR,
                message=(
                    f"{n_plural(len(removed), 'column is', 'columns are')} gone from this "
                    "sheet compared with the previous version."
                ),
                sheet=new_sheet.name,
                cells=[],
                evidence="removed: " + ", ".join(f"'{n}'" for n in removed[:MAX_EXAMPLES]),
                count=len(removed),
            )

        if added:
            yield Finding(
                rule="DF010",
                title="Schema drift",
                severity=Severity.WARNING,
                message=(
                    f"{n_plural(len(added), 'column is', 'columns are')} new in this sheet. "
                    "A strict importer that pins the column count will reject the file."
                ),
                sheet=new_sheet.name,
                cells=[],
                evidence="added: " + ", ".join(f"'{n}'" for n in added[:MAX_EXAMPLES]),
                count=len(added),
            )

        # Reordering is judged on the columns that survived in both versions:
        # additions and removals shift positions on their own and would
        # otherwise make every file look reordered.
        common_old = [n for n in old_names if n in new_names]
        common_new = [n for n in new_names if n in old_names]
        if common_old != common_new and len(common_old) > 1:
            old_pos = {name: index for index, name in enumerate(common_old)}
            moved = [
                name for index, name in enumerate(common_new) if old_pos.get(name) != index
            ]
            new_col_of = {name: col for col, name in new_map.items()}
            old_col_of = {name: col for col, name in old_map.items()}
            detail = ", ".join(
                f"'{name}' {_letter(old_col_of[name])} -> {_letter(new_col_of[name])}"
                for name in moved[:MAX_EXAMPLES]
                if name in old_col_of and name in new_col_of
            )
            yield Finding(
                rule="DF010",
                title="Schema drift",
                severity=Severity.ERROR,
                message=(
                    f"{n_plural(len(moved), 'column changed', 'columns changed')} position. "
                    "An importer reading by column index will keep working and write the "
                    "wrong field."
                ),
                sheet=new_sheet.name,
                cells=[],
                evidence=detail or "column order changed",
                count=len(moved),
            )


@diff_check(
    "DF002",
    "Formula replaced by a constant",
    Severity.ERROR,
    "A cell that computed a value now holds a typed-in number",
)
def df002(old: Book, new: Book) -> Iterator[Finding]:
    for old_sheet, new_sheet in _paired_sheets(old, new):
        hits: list[str] = []
        evidence = None
        for key, old_cell in old_sheet.cells.items():
            new_cell = new_sheet.cells.get(key)
            if new_cell is None or not old_cell.is_formula:
                continue
            if new_cell.is_numeric_constant:
                hits.append(new_cell.coord)
                if evidence is None:
                    evidence = f"was {old_cell.formula}; now {new_cell.value!r}"
        if hits:
            hits.sort()
            yield _aggregate(
                "DF002",
                "Formula replaced by a constant",
                Severity.ERROR,
                new_sheet.name,
                hits,
                f"{n_plural(len(hits), 'cell that computed', 'cells that computed')} a value "
                "now holds a typed-in number.",
                evidence,
            )


@diff_check(
    "DF003",
    "Constant replaced by a formula",
    Severity.INFO,
    "A cell that held a number now computes it",
)
def df003(old: Book, new: Book) -> Iterator[Finding]:
    for old_sheet, new_sheet in _paired_sheets(old, new):
        hits: list[str] = []
        evidence = None
        for key, old_cell in old_sheet.cells.items():
            new_cell = new_sheet.cells.get(key)
            if new_cell is None or old_cell.is_formula or not old_cell.is_numeric_constant:
                continue
            if new_cell.is_formula:
                hits.append(new_cell.coord)
                if evidence is None:
                    evidence = f"was {old_cell.value!r}; now {new_cell.formula}"
        if hits:
            hits.sort()
            yield _aggregate(
                "DF003",
                "Constant replaced by a formula",
                Severity.INFO,
                new_sheet.name,
                hits,
                f"{n_plural(len(hits), 'cell now computes', 'cells now compute')} a value that "
                "used to be typed in.",
                evidence,
            )


@diff_check(
    "DF004",
    "Aggregate range changed",
    Severity.WARNING,
    "The span a SUM or AVERAGE covers is not what it was",
)
def df004(old: Book, new: Book) -> Iterator[Finding]:
    """Separated from DF001 on purpose: a shrinking SUM range silently drops
    rows from a total, which is a different kind of event from editing a
    formula's arithmetic."""
    for old_sheet, new_sheet in _paired_sheets(old, new):
        hits: list[str] = []
        evidence = None
        for key, old_cell in old_sheet.cells.items():
            new_cell = new_sheet.cells.get(key)
            if new_cell is None or not old_cell.is_formula or not new_cell.is_formula:
                continue
            was = F.aggregate_ranges(old_cell.formula)
            now = F.aggregate_ranges(new_cell.formula)
            if was and now and was != now:
                hits.append(new_cell.coord)
                if evidence is None:
                    evidence = f"was {old_cell.formula}; now {new_cell.formula}"
        if hits:
            hits.sort()
            yield _aggregate(
                "DF004",
                "Aggregate range changed",
                Severity.WARNING,
                new_sheet.name,
                hits,
                f"{n_plural(len(hits), 'aggregate covers', 'aggregates cover')} a different "
                "span than in the previous version.",
                evidence,
            )


@diff_check(
    "DF001",
    "Formula changed",
    Severity.INFO,
    "Formula text differs from the previous version",
)
def df001(old: Book, new: Book) -> Iterator[Finding]:
    for old_sheet, new_sheet in _paired_sheets(old, new):
        hits: list[str] = []
        evidence = None
        for key, old_cell in old_sheet.cells.items():
            new_cell = new_sheet.cells.get(key)
            if new_cell is None or not old_cell.is_formula or not new_cell.is_formula:
                continue
            if F.aggregate_ranges(old_cell.formula) != F.aggregate_ranges(new_cell.formula):
                continue  # already reported, with a sharper meaning, by DF004
            was = F.normalize(old_cell.formula, old_cell.row, old_cell.col)
            now = F.normalize(new_cell.formula, new_cell.row, new_cell.col)
            if was != now:
                hits.append(new_cell.coord)
                if evidence is None:
                    evidence = f"was {old_cell.formula}; now {new_cell.formula}"
        if hits:
            hits.sort()
            yield _aggregate(
                "DF001",
                "Formula changed",
                Severity.INFO,
                new_sheet.name,
                hits,
                f"{n_plural(len(hits), 'formula differs', 'formulas differ')} from the "
                "previous version. Inserting a row shifts every formula below it, so a large "
                "count here often means the sheet moved rather than that the logic changed.",
                evidence,
            )


@diff_check(
    "DF005",
    "Sheet added or removed",
    Severity.WARNING,
    "The set of sheets in the workbook is not what it was",
)
def df005(old: Book, new: Book) -> Iterator[Finding]:
    old_names = [s.name for s in old.sheets]
    new_names = [s.name for s in new.sheets]
    removed = [n for n in old_names if n not in new_names]
    added = [n for n in new_names if n not in old_names]

    # One in, one out is more likely a rename than two unrelated edits, and
    # saying so saves the reader from comparing the lists by hand.
    hint = (
        " With one sheet gone and one new, this may be a rename."
        if len(removed) == 1 and len(added) == 1
        else ""
    )

    if removed:
        yield Finding(
            rule="DF005",
            title="Sheet added or removed",
            severity=Severity.WARNING,
            message=f"{n_plural(len(removed), 'sheet is', 'sheets are')} gone.{hint}",
            sheet="",
            cells=[],
            evidence="removed: " + ", ".join(f"'{n}'" for n in removed[:MAX_EXAMPLES]),
            count=len(removed),
        )
    if added:
        yield Finding(
            rule="DF005",
            title="Sheet added or removed",
            severity=Severity.WARNING,
            message=f"{n_plural(len(added), 'sheet is', 'sheets are')} new.{hint}",
            sheet="",
            cells=[],
            evidence="added: " + ", ".join(f"'{n}'" for n in added[:MAX_EXAMPLES]),
            count=len(added),
        )


@diff_check(
    "DF006",
    "Named range changed",
    Severity.WARNING,
    "A defined name was added, removed or repointed",
)
def df006(old: Book, new: Book) -> Iterator[Finding]:
    for name, was in sorted(old.named_ranges.items()):
        if name not in new.named_ranges:
            yield Finding(
                rule="DF006",
                title="Named range changed",
                severity=Severity.WARNING,
                message=(
                    f"The defined name '{name}' no longer exists. Formulas that used it "
                    "resolve to an error."
                ),
                sheet="",
                cells=[],
                evidence=f"was {was}",
            )
        elif new.named_ranges[name] != was:
            yield Finding(
                rule="DF006",
                title="Named range changed",
                severity=Severity.WARNING,
                message=(
                    f"The defined name '{name}' points somewhere else now. Every formula "
                    "using it changed meaning without changing text."
                ),
                sheet="",
                cells=[],
                evidence=f"was {was}; now {new.named_ranges[name]}",
            )


@diff_check(
    "DF011",
    "Column number format changed",
    Severity.WARNING,
    "A column switched between percent, currency or plain number",
)
def df011(old: Book, new: Book) -> Iterator[Finding]:
    """Percent against plain is the dangerous pair: the stored value differs
    by a factor of one hundred while the sheet looks almost the same."""
    for old_sheet, new_sheet in _paired_sheets(old, new):
        old_formats = _dominant_formats(old_sheet)
        new_formats = _dominant_formats(new_sheet)
        headers = _headers(new_sheet)

        for col in sorted(set(old_formats) & set(new_formats)):
            was, now = old_formats[col], new_formats[col]
            if was == now:
                continue
            percent_flip = ("%" in was) != ("%" in now)
            label = f"{_letter(col)} '{headers[col]}'" if col in headers else _letter(col)
            yield Finding(
                rule="DF011",
                title="Column number format changed",
                severity=Severity.ERROR if percent_flip else Severity.WARNING,
                message=(
                    f"Column {label} changed number format."
                    + (
                        " One of the two versions is a percent and the other is not, so the "
                        "stored values differ by a factor of 100."
                        if percent_flip
                        else ""
                    )
                ),
                sheet=new_sheet.name,
                cells=[],
                evidence=f"was '{was}'; now '{now}'",
            )


def _dominant_formats(sheet: Sheet) -> dict[int, str]:
    """The most common number format among numeric cells of each column."""
    header = sheet.header_row()
    start = (header + 1) if header else 1
    formats: dict[int, Counter] = defaultdict(Counter)
    for (row, col), cell in sheet.cells.items():
        if row < start or cell.is_empty:
            continue
        if cell.is_numeric_constant or cell.is_formula:
            formats[col][cell.number_format] += 1
    return {col: counter.most_common(1)[0][0] for col, counter in formats.items() if counter}
