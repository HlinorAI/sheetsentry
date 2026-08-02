"""Formula parsing without evaluation.

We deliberately do not compute formulas (see docs/CHECKS.md, principle 2):
openpyxl hands back either the formula text or the value cached by the last
recalculation. Everything here is structural: R1C1 normalisation, reference
extraction, literal extraction.

R1C1 normalisation is the foundation of SF001 and SF002. Two formulas filled
down a column differ as text (`=B2*C2` and `=B3*C3`) but become identical
once relative references turn into offsets. That is what makes the one cell
that breaks the pattern visible.
"""

from __future__ import annotations

import re

from openpyxl.utils import column_index_from_string

# String literals are masked before any other parsing: anything at all can
# live inside quotes, including text that looks like a reference.
_STRING_RE = re.compile(r'"(?:[^"]|"")*"')

_REF_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_.])                                  # not mid-word
    (?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?
    (?P<col_abs>\$?)(?P<col>[A-Z]{1,3})
    (?P<row_abs>\$?)(?P<row>\d{1,7})
    (?![A-Za-z0-9_(])                                   # not LOG10( or A1B2
    """,
    re.VERBOSE,
)

_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.\]])(\d+\.\d+|\.\d+|\d+)(?![A-Za-z0-9_.])")

AGGREGATE_FUNCTIONS = {
    "SUM",
    "AVERAGE",
    "COUNT",
    "COUNTA",
    "MIN",
    "MAX",
    "MEDIAN",
    "PRODUCT",
    "STDEV",
    "STDEV.S",
    "STDEV.P",
    "STDEVP",
    "SUMPRODUCT",
    "VAR",
    "SUBTOTAL",
}

_AGG_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_.])("
    + "|".join(sorted((re.escape(f) for f in AGGREGATE_FUNCTIONS), key=len, reverse=True))
    + r")\s*\(",
    re.IGNORECASE,
)

_RANGE_RE = re.compile(
    r"""
    (?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?
    \$?(?P<c1>[A-Z]{1,3})\$?(?P<r1>\d{1,7})
    :
    \$?(?P<c2>[A-Z]{1,3})\$?(?P<r2>\d{1,7})
    """,
    re.VERBOSE,
)

# Numbers that are almost always part of the formula's construction rather
# than a business parameter someone hardcoded.
STRUCTURAL_NUMBERS = {0.0, 1.0, 2.0, -1.0, 100.0, 12.0, 365.0}


def _tag(index: int) -> str:
    """Placeholder for a masked string literal.

    The placeholder must contain no digits, otherwise `literals()` would read
    them as numeric constants and `"price 2024"` would become the constant
    2024. Encoding the index in letters keeps reference and number parsing
    clear of it.
    """
    letters = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"\x00{letters}\x00"


def _mask_strings(formula: str) -> tuple[str, list[str]]:
    """Replace string literals with digit-free placeholders."""
    stored: list[str] = []

    def repl(match: re.Match) -> str:
        stored.append(match.group(0))
        return _tag(len(stored) - 1)

    return _STRING_RE.sub(repl, formula), stored


def _unmask_strings(text: str, stored: list[str]) -> str:
    for index, literal in enumerate(stored):
        text = text.replace(_tag(index), literal)
    return text


def normalize(formula: str, row: int, col: int) -> str:
    """Rewrite a formula in R1C1 form relative to cell (row, col).

    Absolute references (`$B$2`) stay absolute: that is a meaningful
    difference, not noise. A reference to a parameter cell is not supposed
    to drift.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return str(formula)

    masked, stored = _mask_strings(formula)

    def repl(match: re.Match) -> str:
        sheet = match.group("sheet") or ""
        target_col = column_index_from_string(match.group("col"))
        target_row = int(match.group("row"))
        col_part = f"C{target_col}" if match.group("col_abs") else f"C[{target_col - col}]"
        row_part = f"R{target_row}" if match.group("row_abs") else f"R[{target_row - row}]"
        return f"{sheet}{row_part}{col_part}"

    normalized = _REF_RE.sub(repl, masked).upper()
    # String literals are restored verbatim: two formulas differing only in a
    # text constant really are different and must compare as different.
    return _unmask_strings(normalized, stored)


def literals(formula: str) -> list[float]:
    """Numeric constants inside a formula, excluding row numbers of refs."""
    if not isinstance(formula, str) or not formula.startswith("="):
        return []

    masked, _ = _mask_strings(formula)
    without_refs = _REF_RE.sub("\x01", masked)
    values: list[float] = []
    for raw in _NUMBER_RE.findall(without_refs):
        try:
            values.append(float(raw))
        except ValueError:  # pragma: no cover - the regex already guarantees the format
            continue
    return values


def aggregate_ranges(formula: str) -> list[tuple[str, int, int, int, int]]:
    """Ranges passed to aggregate functions.

    Returns tuples of (sheet, first_row, first_col, last_row, last_col).
    Sheet is empty when the reference is local to the same sheet.

    The parse is deliberately simple: we take the arguments of an aggregate
    call up to the matching closing parenthesis and look for ranges in them.
    Nested calls inside the aggregate land in the same slice, which is fine:
    a false SF003 is suppressed by checking the actual data below the range.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return []

    masked, _ = _mask_strings(formula)
    found: list[tuple[str, int, int, int, int]] = []

    for call in _AGG_CALL_RE.finditer(masked):
        start = call.end()  # right after the opening parenthesis
        depth = 1
        index = start
        while index < len(masked) and depth > 0:
            char = masked[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        arguments = masked[start : index - 1 if depth == 0 else len(masked)]

        for match in _RANGE_RE.finditer(arguments):
            sheet = (match.group("sheet") or "").rstrip("!").strip("'").replace("''", "'")
            found.append(
                (
                    sheet,
                    int(match.group("r1")),
                    column_index_from_string(match.group("c1")),
                    int(match.group("r2")),
                    column_index_from_string(match.group("c2")),
                )
            )

    return found


def has_ref_error(formula: str) -> bool:
    """`#REF!` in the formula text survives sheet deletion and an empty cache."""
    return isinstance(formula, str) and "#REF!" in formula.upper()
