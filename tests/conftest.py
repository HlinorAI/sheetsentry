"""Builder of broken spreadsheets for the test suite.

It doubles as week-zero tooling: measuring precision honestly needs files
whose breakage is known in advance. Each helper here produces one class of
error in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from sheetsentry import checks, load


@pytest.fixture
def build(tmp_path: Path):
    """Assemble a workbook from a sheet description and return its path."""

    def _build(name: str = "case.xlsx", **sheets: list[list]) -> Path:
        wb = Workbook()
        wb.remove(wb.active)
        for sheet_name, rows in sheets.items():
            ws = wb.create_sheet(title=sheet_name)
            for row in rows:
                ws.append(row)
        path = tmp_path / name
        wb.save(path)
        return path

    return _build


@pytest.fixture
def findings():
    """Run the checks and return the findings, optionally for one rule."""

    def _run(path: Path, rule: str | None = None):
        result = checks.run(load(path))
        if rule:
            result = [f for f in result if f.rule == rule]
        return result

    return _run
