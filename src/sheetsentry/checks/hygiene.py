"""Family SW - workbook hygiene.

Two kinds of check live here. Some state the boundaries of the analysis
honestly: staying quiet about what the tool cannot see is more dangerous than
not checking it at all, because the user would build trust on a false footing.
The rest catch structure that makes a sheet read differently to a human and
to a machine.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

from openpyxl.utils import get_column_letter, range_boundaries

from .. import formula as F
from ..finding import Finding, Severity
from ..text import n_plural
from ..workbook import Book, Cell
from . import check


@check(
    "SW001",
    "Hidden rows inside an aggregated range",
    Severity.WARNING,
    "The reader sees one set of addends and the formula counts another",
)
def sw001(book: Book) -> Iterator[Finding]:
    """Excel keeps hidden rows in SUM. Someone who hides a row to tidy up a
    printout does not always realise the total still includes it."""
    for sheet in book.sheets:
        if not sheet.hidden_rows:
            continue
        for cell in sorted(sheet.cells.values(), key=lambda c: (c.row, c.col)):
            if not cell.is_formula:
                continue
            hidden_inside: set[int] = set()
            for sheet_name, r1, c1, r2, c2 in F.aggregate_ranges(cell.formula):
                if sheet_name and sheet_name != sheet.name:
                    continue
                for row in range(r1, r2 + 1):
                    if row not in sheet.hidden_rows:
                        continue
                    if any(
                        (target := sheet.cell(row, col)) is not None and not target.is_empty
                        for col in range(c1, c2 + 1)
                    ):
                        hidden_inside.add(row)
            if not hidden_inside:
                continue
            rows = sorted(hidden_inside)
            yield Finding(
                rule="SW001",
                title="Hidden rows inside an aggregated range",
                severity=Severity.WARNING,
                message=(
                    f"The aggregate in {cell.coord} covers "
                    f"{n_plural(len(rows), 'row that is', 'rows that are')} hidden. Anyone "
                    "reading the sheet sees fewer addends than the total actually counts."
                ),
                sheet=sheet.name,
                cells=[cell.coord],
                evidence=f"{cell.formula}; hidden rows {', '.join(str(r) for r in rows[:5])}",
                count=len(rows),
            )


@check(
    "SW002",
    "Merged cells inside a data block",
    Severity.WARNING,
    "Merges break lookups, sorting and row-by-row import",
)
def sw002(book: Book) -> Iterator[Finding]:
    """Merges in a header row are ordinary formatting. Below the header they
    leave every cell but the first one empty, which is what the importer
    reads."""
    for sheet in book.sheets:
        header = sheet.header_row()
        first_data_row = (header + 1) if header else 1

        offenders: list[str] = []
        for reference in sheet.merged:
            try:
                min_col, min_row, max_col, max_row = range_boundaries(reference)
            except ValueError:  # pragma: no cover - openpyxl already validated these
                continue
            if max_row < first_data_row:
                continue  # a merged title or header cell
            offenders.append(reference)

        if not offenders:
            continue
        offenders.sort()
        yield Finding(
            rule="SW002",
            title="Merged cells inside a data block",
            severity=Severity.WARNING,
            message=(
                f"{n_plural(len(offenders), 'merged range sits', 'merged ranges sit')} in the "
                "data area. A merge fills only its top-left cell, so lookups, sorting and "
                "row-by-row import see blanks where the reader sees a value."
            ),
            sheet=sheet.name,
            cells=[reference.split(":")[0] for reference in offenders[:5]],
            evidence=", ".join(offenders[:5]),
            count=len(offenders),
        )


@check(
    "SW003",
    "Named range points nowhere",
    Severity.ERROR,
    "A defined name resolves to #REF! or to nothing",
)
def sw003(book: Book) -> Iterator[Finding]:
    for name, destination in sorted(book.named_ranges.items()):
        target = (destination or "").strip()
        broken = not target or "#REF!" in target.upper()
        if not broken:
            continue
        yield Finding(
            rule="SW003",
            title="Named range points nowhere",
            severity=Severity.ERROR,
            message=(
                f"The defined name '{name}' does not resolve. Every formula using it returns "
                "an error, and the name still autocompletes as if it worked."
            ),
            sheet="",
            cells=[],
            evidence=f"{name} -> {target or '(empty)'}",
        )


@check(
    "SW004",
    "Workbook contains macros",
    Severity.INFO,
    "The file carries VBA, whose contents are not analysed",
)
def sw004(book: Book) -> Iterator[Finding]:
    if not book.has_macros:
        return
    yield Finding(
        rule="SW004",
        title="Workbook contains macros",
        severity=Severity.INFO,
        message=(
            "This workbook contains VBA macros. SheetSentry does not read them, so no "
            "finding here accounts for what that code does on open or on recalculation."
        ),
        sheet="",
        cells=[],
    )


@check(
    "SW005",
    "Hidden sheet",
    Severity.INFO,
    "A sheet is hidden from the reader but still feeds the calculations",
)
def sw005(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        if not sheet.hidden:
            continue
        yield Finding(
            rule="SW005",
            title="Hidden sheet",
            severity=Severity.INFO,
            message=(
                f"Sheet '{sheet.name}' is hidden. Whoever opens the file will not see it, "
                "even though formulas on visible sheets may reference it."
            ),
            sheet=sheet.name,
            cells=[],
        )
