"""Family SW - workbook hygiene.

In v0.1 this family only states the boundaries of the analysis honestly.
Staying quiet about what the tool cannot see is more dangerous than not
checking it at all: the user would build trust on a false footing.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Finding, Severity
from ..workbook import Book
from . import check


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
