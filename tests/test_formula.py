"""Formula parsing is the foundation of SF001/SF002/SF003, so it is tested alone."""

from __future__ import annotations

import pytest

from sheetsentry import formula as F


class TestNormalize:
    def test_copied_formulas_collapse_to_one_pattern(self):
        # =B2*C2 on row 2 and =B3*C3 on row 3 are the same formula filled down
        # a column. After normalisation they must match.
        assert F.normalize("=B2*C2", row=2, col=4) == F.normalize("=B3*C3", row=3, col=4)

    def test_shifted_reference_gives_different_pattern(self):
        # =B3 on row 3 points at itself, =B2 on row 3 points one row up.
        assert F.normalize("=B3", row=3, col=4) != F.normalize("=B2", row=3, col=4)

    def test_absolute_reference_is_not_relative(self):
        assert "R2C2" in F.normalize("=$B$2", row=5, col=3)
        assert "R[-3]C[-1]" in F.normalize("=B2", row=5, col=3)

    def test_function_case_is_normalized(self):
        assert F.normalize("=sum(A1:A5)", 6, 1) == F.normalize("=SUM(A1:A5)", 6, 1)

    def test_string_literals_survive_and_differentiate(self):
        left = F.normalize('=A1&" pcs"', 1, 2)
        right = F.normalize('=A1&" kg"', 1, 2)
        assert left != right
        assert " pcs" in left

    def test_function_names_with_digits_are_not_references(self):
        # LOG10( must not be read as column LOG, row 10.
        assert F.normalize("=LOG10(A1)", 1, 2) == "=LOG10(R[0]C[-1])"


class TestLiterals:
    def test_extracts_rate_but_not_row_numbers(self):
        assert F.literals("=B2*1.21") == [1.21]

    def test_ignores_digits_inside_references(self):
        assert F.literals("=SUM(A12:A99)") == []

    def test_ignores_digits_inside_strings(self):
        assert F.literals('=IF(A1="price 2024",B1,0)') == [0.0]


class TestAggregateRanges:
    def test_simple_sum(self):
        assert F.aggregate_ranges("=SUM(B2:B41)") == [("", 2, 2, 41, 2)]

    def test_nested_call_does_not_break_parsing(self):
        found = F.aggregate_ranges("=SUM(B2:B41)/MAX(C1:C9)")
        assert ("", 2, 2, 41, 2) in found
        assert ("", 1, 3, 9, 3) in found

    def test_non_aggregate_function_is_ignored(self):
        assert F.aggregate_ranges("=VLOOKUP(A1,Sheet2!B2:C99,2,FALSE)") == []

    @pytest.mark.parametrize("text", ["", "not a formula", "=A1"])
    def test_no_ranges(self, text):
        assert F.aggregate_ranges(text) == []
