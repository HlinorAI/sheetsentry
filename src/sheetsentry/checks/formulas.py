"""Family SF - formula integrity.

No check here evaluates a formula: only structure and the value cache are
analysed. That is a deliberate v0.1 limit, see docs/CHECKS.md.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

from .. import formula as F
from ..finding import Finding, Severity
from ..text import n_plural
from ..workbook import ERROR_VALUES, Book, Cell
from . import check

MIN_RUN = 4
MIN_PATTERN_CELLS = 3


def _first_data_row(sheet) -> int:
    """Formula runs start at the first data row.

    Otherwise the header joins the run as its first element and eats the
    allowance made for the run's edges: the first period's formula, which
    legitimately differs from the rest, starts reporting as a false positive.
    """
    header = sheet.header_row()
    return (header + 1) if header else 1


def _patterns(cells: list[Cell]) -> dict[str, list[Cell]]:
    groups: dict[str, list[Cell]] = defaultdict(list)
    for cell in cells:
        if cell.is_formula:
            groups[F.normalize(cell.formula, cell.row, cell.col)].append(cell)
    return groups


@check(
    "SF001",
    "Formula replaced by a constant",
    Severity.ERROR,
    "A hand-typed number sits among cells that all share one formula",
)
def sf001(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        start = _first_data_row(sheet)
        for col in range(1, sheet.max_col + 1):
            for run in sheet.runs(col, start):
                if len(run) < MIN_RUN:
                    continue
                constants = [c for c in run if c.is_numeric_constant]
                if not constants:
                    continue

                groups = _patterns(run)
                if not groups:
                    continue
                _, members = max(groups.items(), key=lambda kv: len(kv[1]))
                if len(members) < MIN_PATTERN_CELLS:
                    continue

                # Signal strength is not the share of the run but how many
                # formulas agree against how many constants. A share breaks on
                # short runs: one overwritten formula among four is 20%, and
                # that canonical case was falling through to a warning.
                severity = (
                    Severity.ERROR if len(constants) < len(members) else Severity.WARNING
                )
                for constant in constants:
                    yield Finding(
                        rule="SF001",
                        title="Formula replaced by a constant",
                        severity=severity,
                        message=(
                            f"Cell {constant.coord} holds a number while "
                            f"{n_plural(len(members), 'neighbouring cell', 'neighbouring cells')} "
                            f"in column {sheet.column_label(col)} share one formula. "
                            "The formula was most likely typed over."
                        ),
                        sheet=sheet.name,
                        cells=[constant.coord],
                        evidence=f"value {constant.value!r}; neighbours use {members[0].formula}",
                    )


@check(
    "SF002",
    "Formula breaks the pattern",
    Severity.WARNING,
    "One formula differs structurally from its neighbours in the same range",
)
def sf002(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        start = _first_data_row(sheet)
        for col in range(1, sheet.max_col + 1):
            for run in sheet.runs(col, start):
                if len(run) < MIN_RUN:
                    continue
                groups = _patterns(run)
                if len(groups) < 2:
                    continue

                total = sum(len(v) for v in groups.values())
                dominant_pattern, dominant = max(groups.items(), key=lambda kv: len(kv[1]))
                if len(dominant) / total < 0.6 or len(dominant) < MIN_PATTERN_CELLS:
                    continue

                # The edges of a run are excused: the first period has no
                # predecessor and the last one has no successor.
                edges = {run[0].coord, run[-1].coord}

                for pattern, members in groups.items():
                    if pattern == dominant_pattern:
                        continue
                    for cell in members:
                        if cell.coord in edges:
                            continue
                        yield Finding(
                            rule="SF002",
                            title="Formula breaks the pattern",
                            severity=Severity.WARNING,
                            message=(
                                f"The formula in {cell.coord} differs structurally from the "
                                f"{n_plural(len(dominant), 'other formula', 'other formulas')} "
                                f"in this run of column {sheet.column_label(col)}."
                            ),
                            sheet=sheet.name,
                            cells=[cell.coord],
                            evidence=f"here {cell.formula}; most use {dominant[0].formula}",
                        )


@check(
    "SF003",
    "Aggregate range misses data",
    Severity.ERROR,
    "SUM stops short of where the column's data actually ends",
)
def sf003(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        covered: dict[int, set[int]] = defaultdict(set)
        aggregates: list[tuple[Cell, int, int, int]] = []

        for cell in sheet.cells.values():
            if not cell.is_formula:
                continue
            for sheet_name, r1, c1, r2, c2 in F.aggregate_ranges(cell.formula):
                if sheet_name and sheet_name != sheet.name:
                    continue
                if c1 != c2:
                    continue  # multi-column ranges are out of scope for v0.1
                for row in range(r1, r2 + 1):
                    covered[c1].add(row)
                aggregates.append((cell, c1, r1, r2))

        for agg_cell, col, _, last_row in aggregates:
            missed: list[Cell] = []
            row = last_row + 1
            while True:
                cell = sheet.cell(row, col)
                if cell is None or cell.is_empty:
                    break
                if (cell.row, cell.col) == (agg_cell.row, agg_cell.col):
                    break  # this is the total row itself
                if cell.is_formula or not cell.is_numeric_constant:
                    break
                if row in covered[col]:
                    break  # already counted by another aggregate: a subtotal
                missed.append(cell)
                row += 1

            if missed:
                yield Finding(
                    rule="SF003",
                    title="Aggregate range misses data",
                    severity=Severity.ERROR,
                    message=(
                        f"The formula in {agg_cell.coord} aggregates column "
                        f"{sheet.column_label(col)} up to row {last_row}, but data continues "
                        f"to row {missed[-1].row}. "
                        f"{n_plural(len(missed), 'value is', 'values are')} left out of the total."
                    ),
                    sheet=sheet.name,
                    cells=[agg_cell.coord] + [c.coord for c in missed[:4]],
                    evidence=agg_cell.formula,
                    count=len(missed) + 1,
                )


@check(
    "SF004",
    "Error values",
    Severity.ERROR,
    "#REF!, #DIV/0! and other errors sitting in cells",
)
def sf004(book: Book) -> Iterator[Finding]:
    if book.cache_is_empty:
        yield Finding(
            rule="SF004",
            title="Error values",
            severity=Severity.INFO,
            message=(
                "The workbook has formulas but no computed values at all: Excel has never "
                "recalculated this file. Computation errors cannot be detected here, only "
                "formula text is checked."
            ),
            sheet="",
            cells=[],
        )

    for sheet in book.sheets:
        by_kind: dict[str, list[Cell]] = defaultdict(list)
        for cell in sheet.cells.values():
            text = str(cell.value).strip().upper() if cell.value is not None else ""
            if text in ERROR_VALUES:
                by_kind[text].append(cell)
            elif cell.is_formula and F.has_ref_error(cell.formula):
                by_kind["#REF!"].append(cell)

        for kind, cells in by_kind.items():
            cells.sort(key=lambda c: (c.row, c.col))
            optional = kind == "#N/A"
            yield Finding(
                rule="SF004",
                title="Error values",
                severity=Severity.INFO if optional else Severity.ERROR,
                message=(
                    f"{n_plural(len(cells), 'cell holds', 'cells hold')} {kind}."
                    + (
                        " This is often a deliberate lookup placeholder, but worth confirming."
                        if optional
                        else " This file cannot be treated as computed."
                    )
                ),
                sheet=sheet.name,
                cells=[c.coord for c in cells[:5]],
                evidence=cells[0].formula or str(cells[0].value),
                count=len(cells),
            )


@check(
    "SF006",
    "Reference to another workbook",
    Severity.WARNING,
    "The file depends on a second file the recipient may not have",
)
def sf006(book: Book) -> Iterator[Finding]:
    """A file that reads from another file is only whole on the machine that
    built it. Sent onwards, it keeps the last cached numbers and gives no
    sign that they stopped updating."""
    for sheet in book.sheets:
        hits: list[Cell] = []
        targets: set[str] = set()
        for cell in sheet.cells.values():
            if not cell.is_formula:
                continue
            found = F.external_references(cell.formula)
            if found:
                hits.append(cell)
                targets.update(found)
        if not hits:
            continue
        hits.sort(key=lambda c: (c.row, c.col))
        yield Finding(
            rule="SF006",
            title="Reference to another workbook",
            severity=Severity.WARNING,
            message=(
                f"{n_plural(len(hits), 'formula reads', 'formulas read')} from another "
                "workbook. Away from the machine that built this file those values stop "
                "updating without any visible sign."
            ),
            sheet=sheet.name,
            cells=[c.coord for c in hits[:5]],
            evidence=f"{hits[0].formula} (targets: {', '.join(sorted(targets)[:3])})",
            count=len(hits),
        )


@check(
    "SF005",
    "Constant hardcoded into a formula",
    Severity.INFO,
    "A rate or FX factor inside the formula instead of a reference to a parameter cell",
)
def sf005(book: Book) -> Iterator[Finding]:
    for sheet in book.sheets:
        occurrences: dict[float, list[Cell]] = defaultdict(list)
        for cell in sheet.cells.values():
            if not cell.is_formula:
                continue
            for value in set(F.literals(cell.formula)):
                if value in F.STRUCTURAL_NUMBERS:
                    continue
                occurrences[value].append(cell)

        for value, cells in sorted(occurrences.items()):
            is_fraction = value != int(value)
            if not is_fraction and len(cells) < 3:
                continue
            cells.sort(key=lambda c: (c.row, c.col))
            yield Finding(
                rule="SF005",
                title="Constant hardcoded into a formula",
                severity=Severity.INFO,
                message=(
                    f"The number {value:g} appears literally in "
                    f"{n_plural(len(cells), 'formula', 'formulas')}. "
                    "If that is a rate, changing it means editing every one of them."
                ),
                sheet=sheet.name,
                cells=[c.coord for c in cells[:5]],
                evidence=cells[0].formula,
                count=len(cells),
            )
