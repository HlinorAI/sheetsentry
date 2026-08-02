"""Checks in family SF.

Every test comes in a pair: a broken file must produce a finding, and a
similar healthy file must produce none. The second half matters more - a tool
that fires on healthy files gets switched off on day one.
"""

from __future__ import annotations

from sheetsentry.finding import Severity


class TestSF001FormulaReplacedByConstant:
    def test_constant_among_formulas_is_reported(self, build, findings):
        path = build(
            Calc=[
                ["Qty", "Price", "Total"],
                [2, 10, "=A2*B2"],
                [3, 10, "=A3*B3"],
                [4, 10, 40],  # formula typed over
                [5, 10, "=A5*B5"],
                [6, 10, "=A6*B6"],
            ]
        )
        found = findings(path, "SF001")
        assert len(found) == 1
        assert found[0].cells == ["C4"]
        assert found[0].severity is Severity.ERROR

    def test_column_of_pure_constants_is_clean(self, build, findings):
        path = build(Data=[["Qty"], [1], [2], [3], [4], [5]])
        assert findings(path, "SF001") == []

    def test_mostly_constants_downgrades_to_warning(self, build, findings):
        path = build(
            Mixed=[
                ["Total"],
                ["=1+1"],
                ["=1+1"],
                ["=1+1"],
                [10],
                [20],
                [30],
                [40],
            ]
        )
        found = findings(path, "SF001")
        assert found and all(f.severity is Severity.WARNING for f in found)


class TestSF002FormulaOutOfPattern:
    def test_odd_formula_in_the_middle_is_reported(self, build, findings):
        path = build(
            Forecast=[
                ["Period", "Plan"],
                [1, "=A2*2"],
                [2, "=A3*2"],
                [3, "=A4*3"],  # different multiplier
                [4, "=A5*2"],
                [5, "=A6*2"],
                [6, "=A7*2"],
            ]
        )
        found = findings(path, "SF002")
        assert [f.cells[0] for f in found] == ["B4"]

    def test_identical_formulas_are_clean(self, build, findings):
        path = build(
            Forecast=[
                ["Period", "Plan"],
                [1, "=A2*2"],
                [2, "=A3*2"],
                [3, "=A4*2"],
                [4, "=A5*2"],
                [5, "=A6*2"],
            ]
        )
        assert findings(path, "SF002") == []

    def test_first_row_of_series_is_allowed_to_differ(self, build, findings):
        # The first period has no predecessor, so its formula legitimately differs.
        path = build(
            Growth=[
                ["Period", "Value"],
                [1, "=100"],
                [2, "=B2*1.1"],
                [3, "=B3*1.1"],
                [4, "=B4*1.1"],
                [5, "=B5*1.1"],
            ]
        )
        assert findings(path, "SF002") == []


class TestSF003AggregateCoverage:
    def test_sum_shorter_than_data_is_reported(self, build, findings):
        path = build(
            Budget=[
                ["Item", "Amount"],
                ["rent", 100],
                ["telecom", 200],
                ["software", 300],
                ["added later", 400],  # appended after the SUM was written
                ["Total", "=SUM(B2:B4)"],
            ]
        )
        found = findings(path, "SF003")
        assert len(found) == 1
        assert found[0].cells[0] == "B6"
        assert "B5" in found[0].cells

    def test_sum_covering_everything_is_clean(self, build, findings):
        path = build(
            Budget=[
                ["Item", "Amount"],
                ["rent", 100],
                ["telecom", 200],
                ["software", 300],
                ["Total", "=SUM(B2:B4)"],
            ]
        )
        assert findings(path, "SF003") == []


class TestSF004ErrorValues:
    def test_ref_error_in_formula_text_is_found_without_cache(self, build, findings):
        # openpyxl does not recalculate, so the cache is empty and the check
        # has to fall back on the formula text.
        path = build(Sheet=[["Total", "=SUM(#REF!)"]])
        found = findings(path, "SF004")
        assert any(f.severity is Severity.ERROR and "#REF!" in f.message for f in found)

    def test_empty_cache_is_announced_not_hidden(self, build, findings):
        path = build(Sheet=[["Total", "=1+1"]])
        notes = [f for f in findings(path, "SF004") if f.severity is Severity.INFO]
        assert notes and "never recalculated" in notes[0].message


class TestSF005HardcodedConstant:
    def test_repeated_rate_is_reported(self, build, findings):
        path = build(
            Vat=[
                ["Amount", "Gross"],
                [100, "=A2*1.21"],
                [200, "=A3*1.21"],
                [300, "=A4*1.21"],
            ]
        )
        found = findings(path, "SF005")
        assert len(found) == 1
        assert "1.21" in found[0].message
        assert found[0].severity is Severity.INFO

    def test_structural_numbers_are_not_reported(self, build, findings):
        path = build(
            Sheet=[
                ["Value", "Next"],
                [1, "=A2+1"],
                [2, "=A3+1"],
                [3, "=A4+1"],
            ]
        )
        assert findings(path, "SF005") == []
