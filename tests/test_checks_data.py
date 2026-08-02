"""Checks in family SD - what breaks the receiving system."""

from __future__ import annotations

from sheetsentry.finding import Severity


def feed(rows: list[list], header=("SKU", "Name", "Price")) -> list[list]:
    return [list(header)] + rows


class TestSD001NumbersAsText:
    def test_text_numbers_among_real_numbers(self, build, findings):
        rows = [[f"A{i}", "item", i * 10] for i in range(1, 12)]
        rows[3][2] = "1 250"  # price arrived as a string
        path = build(Price=feed(rows))
        found = findings(path, "SD001")
        assert len(found) == 1
        assert found[0].cells == ["C5"]

    def test_fully_textual_column_is_not_flagged(self, build, findings):
        rows = [[f"A{i}", "item", str(i)] for i in range(1, 12)]
        path = build(Price=feed(rows))
        assert findings(path, "SD001") == []

    def test_part_number_with_leading_zero_is_not_a_number(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 12)]
        rows[2][0] = "00123"
        path = build(Price=feed(rows))
        assert findings(path, "SD001") == []


class TestSD002InvisibleCharacters:
    def test_trailing_space_in_key_is_reported(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 12)]
        rows[5][0] = "A6 "
        path = build(Price=feed(rows))
        found = findings(path, "SD002")
        assert len(found) == 1
        assert found[0].cells == ["A7"]
        assert found[0].severity is Severity.WARNING

    def test_non_breaking_space_is_reported(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 12)]
        rows[1][1] = "special\xa0item"
        path = build(Price=feed(rows))
        assert any("non-breaking" in f.message for f in findings(path, "SD002"))

    def test_clean_feed_is_silent(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 12)]
        path = build(Price=feed(rows))
        assert findings(path, "SD002") == []


class TestSD003DuplicateKeys:
    def test_duplicate_sku_is_an_error(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 25)]
        rows[10][0] = "A1"  # duplicated part number
        path = build(Price=feed(rows))
        found = findings(path, "SD003")
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR
        assert "A1" in found[0].evidence

    def test_unique_keys_are_silent(self, build, findings):
        rows = [[f"A{i}", "item", i] for i in range(1, 25)]
        path = build(Price=feed(rows))
        assert findings(path, "SD003") == []

    def test_short_column_is_not_judged(self, build, findings):
        rows = [["A1", "item", 1], ["A1", "item", 2]]
        path = build(Price=feed(rows))
        assert findings(path, "SD003") == []


class TestSD004MixedTypes:
    def test_single_text_cell_among_numbers(self, build, findings):
        rows = [[f"A{i}", "item", i * 10] for i in range(1, 15)]
        rows[6][2] = "on request"
        path = build(Price=feed(rows))
        found = findings(path, "SD004")
        assert len(found) == 1
        assert found[0].cells == ["C8"]

    def test_explicit_blank_marker_is_not_a_type_conflict(self, build, findings):
        rows = [[f"A{i}", "item", i * 10] for i in range(1, 15)]
        rows[6][2] = "n/a"
        path = build(Price=feed(rows))
        assert findings(path, "SD004") == []


class TestSD005TextDates:
    def test_text_dates_are_reported_with_ambiguity_note(self, build, findings):
        rows = [[f"A{i}", "01.02.2026", i] for i in range(1, 12)]
        path = build(Shipments=feed(rows, header=("SKU", "Date", "Qty")))
        found = findings(path, "SD005")
        assert len(found) == 1
        assert "cannot be told" in found[0].message

    def test_unambiguous_dates_omit_the_note(self, build, findings):
        rows = [[f"A{i}", "25.02.2026", i] for i in range(1, 12)]
        path = build(Shipments=feed(rows, header=("SKU", "Date", "Qty")))
        found = findings(path, "SD005")
        assert len(found) == 1
        assert "cannot be told" not in found[0].message
