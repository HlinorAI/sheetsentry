"""Checks in family DF - what changed between two versions of a file.

DF010 is the reason this command exists, so it carries the most cases: a
reordering of columns is invisible to the reader and fatal to an importer
that reads by index.
"""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from sheetsentry import checks, load
from sheetsentry.finding import Severity


@pytest.fixture
def compare(build):
    """Build two workbooks and return the findings of comparing them."""

    def _compare(old_sheets: dict, new_sheets: dict, rule: str | None = None):
        old = build("old.xlsx", **old_sheets)
        new = build("new.xlsx", **new_sheets)
        result = checks.run_diff(load(old), load(new))
        if rule:
            result = [f for f in result if f.rule == rule]
        return result

    return _compare


class TestDF010SchemaDrift:
    def test_reordered_columns_are_an_error(self, compare):
        old_rows = [["SKU", "Name", "Price"]] + [[f"A{i}", "item", i * 10] for i in range(1, 6)]
        new_rows = [["SKU", "Price", "Name"]] + [[f"A{i}", i * 10, "item"] for i in range(1, 6)]
        found = compare({"Price": old_rows}, {"Price": new_rows}, "DF010")
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR
        assert "position" in found[0].message
        assert "'Name'" in found[0].evidence and "'Price'" in found[0].evidence

    def test_identical_schema_is_silent(self, compare):
        rows = [["SKU", "Name", "Price"]] + [[f"A{i}", "item", i * 10] for i in range(1, 6)]
        assert compare({"Price": rows}, {"Price": rows}, "DF010") == []

    def test_renamed_column_is_reported_as_a_rename(self, compare):
        old_rows = [["SKU", "Name", "Price"]] + [[f"A{i}", "item", i] for i in range(1, 6)]
        new_rows = [["SKU", "Title", "Price"]] + [[f"A{i}", "item", i] for i in range(1, 6)]
        found = compare({"Price": old_rows}, {"Price": new_rows}, "DF010")
        assert len(found) == 1
        assert "renamed" in found[0].message
        assert found[0].evidence == "'Name' -> 'Title'"

    def test_removed_column_is_an_error(self, compare):
        old_rows = [["SKU", "Name", "Price"]] + [[f"A{i}", "item", i] for i in range(1, 6)]
        new_rows = [["SKU", "Price"]] + [[f"A{i}", i] for i in range(1, 6)]
        found = compare({"Price": old_rows}, {"Price": new_rows}, "DF010")
        removed = [f for f in found if "gone" in f.message]
        assert len(removed) == 1
        assert removed[0].severity is Severity.ERROR
        assert "'Name'" in removed[0].evidence

    def test_added_column_is_only_a_warning(self, compare):
        old_rows = [["SKU", "Price"]] + [[f"A{i}", i] for i in range(1, 6)]
        new_rows = [["SKU", "Price", "Stock"]] + [[f"A{i}", i, 7] for i in range(1, 6)]
        found = compare({"Price": old_rows}, {"Price": new_rows}, "DF010")
        assert len(found) == 1
        assert found[0].severity is Severity.WARNING
        assert "'Stock'" in found[0].evidence

    def test_appending_a_column_does_not_look_like_a_reorder(self, compare):
        # Surviving columns kept their order, so only the addition is reported.
        old_rows = [["SKU", "Price"]] + [[f"A{i}", i] for i in range(1, 6)]
        new_rows = [["SKU", "Price", "Stock"]] + [[f"A{i}", i, 7] for i in range(1, 6)]
        found = compare({"Price": old_rows}, {"Price": new_rows}, "DF010")
        assert not any("position" in f.message for f in found)


class TestCellLevelDifferences:
    def test_formula_replaced_by_constant_is_an_error(self, compare):
        old_rows = [["Qty", "Total"], [1, "=A2*2"], [2, "=A3*2"], [3, "=A4*2"]]
        new_rows = [["Qty", "Total"], [1, "=A2*2"], [2, 4], [3, "=A4*2"]]
        found = compare({"Calc": old_rows}, {"Calc": new_rows}, "DF002")
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR
        assert found[0].cells == ["B3"]
        assert "was =A3*2" in found[0].evidence

    def test_constant_replaced_by_formula_is_only_a_note(self, compare):
        old_rows = [["Qty", "Total"], [1, 2], [2, 4]]
        new_rows = [["Qty", "Total"], [1, "=A2*2"], [2, 4]]
        found = compare({"Calc": old_rows}, {"Calc": new_rows}, "DF003")
        assert len(found) == 1
        assert found[0].severity is Severity.INFO

    def test_shrinking_a_sum_range_is_its_own_finding(self, compare):
        old_rows = [["Item", "Amount"], ["a", 1], ["b", 2], ["c", 3], ["Total", "=SUM(B2:B4)"]]
        new_rows = [["Item", "Amount"], ["a", 1], ["b", 2], ["c", 3], ["Total", "=SUM(B2:B3)"]]
        found = compare({"Budget": old_rows}, {"Budget": new_rows}, "DF004")
        assert len(found) == 1
        assert found[0].cells == ["B5"]
        assert "B2:B4" in found[0].evidence and "B2:B3" in found[0].evidence

    def test_range_change_is_not_double_reported_as_a_formula_change(self, compare):
        old_rows = [["Item", "Amount"], ["a", 1], ["b", 2], ["c", 3], ["Total", "=SUM(B2:B4)"]]
        new_rows = [["Item", "Amount"], ["a", 1], ["b", 2], ["c", 3], ["Total", "=SUM(B2:B3)"]]
        assert compare({"Budget": old_rows}, {"Budget": new_rows}, "DF001") == []

    def test_formula_edit_is_a_note(self, compare):
        old_rows = [["Qty", "Total"], [1, "=A2*2"], [2, "=A3*2"]]
        new_rows = [["Qty", "Total"], [1, "=A2*3"], [2, "=A3*2"]]
        found = compare({"Calc": old_rows}, {"Calc": new_rows}, "DF001")
        assert len(found) == 1
        assert found[0].severity is Severity.INFO
        assert found[0].cells == ["B2"]

    def test_unchanged_file_produces_nothing(self, compare):
        rows = [["Item", "Amount"], ["a", 1], ["b", 2], ["Total", "=SUM(B2:B3)"]]
        assert compare({"Budget": rows}, {"Budget": rows}) == []


class TestDF005Sheets:
    def test_removed_sheet_is_reported(self, compare):
        rows = [["a", 1]]
        found = compare({"Keep": rows, "Drop": rows}, {"Keep": rows}, "DF005")
        assert len(found) == 1
        assert "'Drop'" in found[0].evidence

    def test_one_in_one_out_hints_at_a_rename(self, compare):
        rows = [["a", 1]]
        found = compare({"Old": rows}, {"New": rows}, "DF005")
        assert len(found) == 2
        assert all("may be a rename" in f.message for f in found)


class TestDF011NumberFormat:
    """Built with openpyxl directly: the shared builder does not set formats."""

    @staticmethod
    def _margins(path, number_format: str):
        wb = Workbook()
        ws = wb.active
        ws.title = "Margins"
        ws.append(["Product", "Margin"])
        for row in range(2, 9):
            ws.append([f"item {row}", 0.2])
            ws.cell(row=row, column=2).number_format = number_format
        wb.save(path)
        return path

    def _compare(self, tmp_path, old_format: str, new_format: str):
        old = self._margins(tmp_path / "old.xlsx", old_format)
        new = self._margins(tmp_path / "new.xlsx", new_format)
        return [f for f in checks.run_diff(load(old), load(new)) if f.rule == "DF011"]

    def test_percent_flip_is_an_error(self, tmp_path):
        found = self._compare(tmp_path, "0.00%", "0.00")
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR
        assert "factor of 100" in found[0].message
        assert found[0].evidence == "was '0.00%'; now '0.00'"

    def test_cosmetic_format_change_is_only_a_warning(self, tmp_path):
        found = self._compare(tmp_path, "0.00", "#,##0.000")
        assert len(found) == 1
        assert found[0].severity is Severity.WARNING
        assert "factor of 100" not in found[0].message

    def test_same_format_is_silent(self, tmp_path):
        assert self._compare(tmp_path, "0.00%", "0.00%") == []
