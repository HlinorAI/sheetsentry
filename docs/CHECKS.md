# SheetSentry check specification

> Document version 0.1

This document is the source of truth for the implementation. Each check is described so that code, a test and a README line can be written from it without any further decisions.

---

## Principles

**1. Zero configuration on entry.** `sheetsentry audit file.xlsx` must produce something useful without a single line of setup. YAML rules are step two, for people who reached CI; they are not the price of admission.

**2. No check that requires evaluating formulas, in v0.1.** openpyxl does not compute formulas: it returns either the formula text or the value cached by the last recalculation. A real engine (headless LibreOffice, or `pycel`) is a project of its own with its own function compatibility matrix. Every check below works on structure and on the cache, except where explicitly marked.

**3. Every finding carries proof.** Sheet, cell address, the formula text or value, and a human explanation. A finding without an address is not a finding.

**4. A false positive costs more than a miss.** A tool that shouts at healthy files gets switched off within a day. So every check documents its false-positive risk and how that risk is reduced, and doubtful checks default to `info`.

---

## Check families

| Prefix | Family | Who cares |
|---|---|---|
| `SD` | Data and exchange integrity | The engineer whose import breaks on someone else's file |
| `SF` | Formula integrity | The analyst and the owner of a calculation model |
| `SW` | Workbook hygiene | Both |
| `DF` | Version differences (`diff`) | Whoever reviews the change |

**`SD` is the first-class family.** Our first user is the one receiving other companies' spreadsheets: supplier feeds, bank reports, client-filled templates, exports headed for an ERP. These checks catch what breaks the receiving system. `SF` provides the depth that makes the product defensible, but it comes second.

---

## Severity levels

| Level | Meaning | SARIF | Effect on exit code |
|---|---|---|---|
| `error` | The file is almost certainly broken, or will break the receiver | `error` | 1 with `--fail-on error` (default) |
| `warning` | Looks like a mistake, a human should look | `warning` | 1 with `--fail-on warning` |
| `info` | An observation, frequently legitimate | `note` | only with `--fail-on info` |

---

# SD - data and exchange integrity

### SD001 - Numbers stored as text

**Level:** `warning` - **Status:** v0.1

**What it catches.** A cell is typed as a string but holds a number: `"1234"`, `"1 234.56"`, `"$1,234"`, `"12%"`. The classic reason an import writes a zero or fails on a type cast, and the reason `SUM` silently skips those cells.

**How it is detected.** `cell.data_type == 's'` and the value, after normalisation (stripping whitespace, non-breaking spaces, thousands separators and currency symbols), parses as a number. Findings aggregate per column: one result per column with a count and the first five addresses.

**False-positive risk.** Low. Part numbers like `00123` and phone numbers are legitimately text. Mitigation: values with leading zeros and values of 11 or more digits without separators are not flagged; a column is not flagged when such values make up 100% of it, only when they are mixed in with real numbers.

---

### SD002 - Invisible characters in values

**Level:** `warning` - **Status:** v0.1

**What it catches.** Leading and trailing whitespace, non-breaking space, narrow non-breaking space, zero-width space, byte order mark, tab and embedded line breaks. The key `"ABC-123 "` does not match `"ABC-123"`, and the join on the receiving side falls apart without raising a single error.

**How it is detected.** Character-level scan of string values against a set of suspicious code points, plus `value != value.strip()`. Aggregated per column.

**False-positive risk.** Very low. A line break inside a description field is legitimate, so `\n` yields `info` while the rest yields `warning`.

---

### SD003 - Duplicates in a key column

**Level:** `error` - **Status:** v0.1

**What it catches.** Repeated values in a column that looks like a key. In a supplier feed this means the receiver either overwrites a row or creates a duplicate product.

**How it is detected.** A column counts as a key when either
- the header matches `id|code|sku|key|ean|gtin|upc|isbn|no|num|number|ref|barcode|part|serial|slug`, or
- at least 90% of values are unique across 20 or more filled cells.

Then repeats are located. Empty cells do not participate.

**False-positive risk.** Moderate for the uniqueness heuristic. Mitigation: when the column qualified by heuristic rather than by header name, severity drops to `warning` and the finding text states exactly why the column was treated as a key.

---

### SD004 - Mixed types in a column

**Level:** `warning` - **Status:** v0.1

**What it catches.** Numbers next to text, or dates next to strings, in a data column. A sign that some rows were typed by hand over an export.

**How it is detected.** For each column below the header row, the distribution of `cell.data_type` is counted. When the minority type holds between 1 and 20% of non-empty cells, that is a finding listing the outliers. A fully mixed column (40/60) is not flagged: it is most likely heterogeneous by design.

**False-positive risk.** Moderate. Mitigation: not applied to columns with fewer than 10 filled cells; explicit gap markers such as `n/a`, `-`, `none`, `tbd` are ignored.

---

### SD005 - Dates stored as text

**Level:** `warning` - **Status:** v0.1

**What it catches.** Dates written as strings (`"01.02.2026"`, `"2026-02-01"`), especially mixed with real dates. Separately, the `01.02` vs `02.01` ambiguity: if the column contains any value whose first component exceeds 12, day/month order is determined; if not, the order is undecidable and the finding says so outright.

**How it is detected.** Regular expressions for common formats against string cells, compared with the presence of `is_date` cells in the same column.

**False-positive risk.** Low. Mitigation: the finding describes the problem instead of prescribing a "correct" format.

---

### SD006 - Blank rows and columns inside a table

**Level:** `info` - **Status:** v0.2

A fully blank row in the middle of a data block: most parsers treat it as the end of the table and silently drop the tail.

---

### SD007 - Schema drift against the previous version

**Level:** `error` - **Status:** v0.2 (via `diff`)

**What it catches.** Columns renamed, reordered, added or removed in the new version of a feed. For a receiver that reads by column index, a reordering is a silent catastrophe.

**Why it lives in `diff`.** Without a second file or a declared schema there is no such thing as a "correct" column order. See `DF010`.

---

# SF - formula integrity

### SF001 - Formula replaced by a constant

**Level:** `error` - **Status:** v0.1

**What it catches.** Within a vertical run of cells where the rest are formulas of one shape, one or more hold a hand-typed number. The most frequent and most expensive breakage in calculation spreadsheets.

**How it is detected.** Inside a contiguous run of filled cells in a column, cells are classified as formulas or constants. If three or more formulas normalise to the same R1C1 pattern and the run also holds numeric constants, each constant yields a finding.

**False-positive risk.** Moderate: overriding a forecast with an actual figure by hand is legitimate practice. Mitigation: level is `error` when constants are fewer than the formulas that agree with each other, otherwise `warning`. A share of the run length does not work here - one overwritten formula among four is 20% and would have fallen through to a warning, though that is precisely the canonical case. The finding text quotes the neighbours' formula pattern.

---

### SF002 - Formula breaks the pattern

**Level:** `warning` - **Status:** v0.1

**What it catches.** Every cell in a run is a formula, but one differs structurally from its neighbours.

**How it is detected.** Each formula is normalised to R1C1 (relative references become offsets, absolute ones stay as they are), the run is grouped by pattern, and minority groups are flagged.

**False-positive risk.** Moderate. Mitigation: the first and last cells of a run are excluded by default - the first period legitimately has no predecessor.

---

### SF003 - Aggregate range misses data

**Level:** `error` - **Status:** v0.1

**What it catches.** `=SUM(B2:B41)` while column `B` holds data down to `B45`. Rows were added and the total stopped seeing them.

**How it is detected.** Ranges inside aggregate functions (`SUM`, `AVERAGE`, `COUNT`, `COUNTA`, `MIN`, `MAX`, `MEDIAN`, `PRODUCT`, `STDEV*`, `SUMPRODUCT`) are extracted from the formula. For a single-column range `X{r1}:X{r2}`, the check looks for non-empty numeric cells immediately after `r2` in that column that are not formulas and are not the aggregate cell itself.

**False-positive risk.** Moderate: subtotals inside a column are a normal construct. Mitigation: the finding is suppressed when the trailing cells are themselves covered by another aggregate over the same column.

---

### SF004 - Error values

**Level:** `error` - **Status:** v0.1

**What it catches.** `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#NULL!`, `#NUM!` in the value cache or in the formula text.

**How it is detected.** A second read of the workbook with `data_only=True`, comparing values against the error markers, plus a search for `#REF!` in formula text, which survives sheet deletion.

**False-positive risk.** None, except for `#N/A`, which is frequently a meaningful lookup placeholder and is therefore split out as a separate `info` finding.

**Limitation.** If the workbook has never been recalculated by Excel (for instance it was generated by a library), the cache is empty and the check sees only `#REF!` in text. This is reported as its own line in the report rather than passed over in silence.

---

### SF005 - Constant hardcoded into a formula

**Level:** `info` - **Status:** v0.1

**What it catches.** `=B2*1.21`, `=C5*0.87` - a tax rate or FX factor typed into the formula instead of referencing a parameter cell. When the rate changes, the edit has to happen in a hundred places.

**How it is detected.** Numeric literals are extracted from the formula text after string literals have been masked. `0`, `1`, `2`, `-1`, `100`, `12`, `365` are ignored. Non-integer literals are flagged, as are literals repeated across three or more formulas.

**False-positive risk.** High by nature - hence the `info` level and aggregation: one finding per constant value, listing where it occurs.

---

### SF006 - Reference to an external workbook

**Level:** `warning` - **Status:** v0.2

Formulas of the form `[1]Price!B2`: the file depends on another file the recipient does not have.

---

### SF007 - Circular references

**Level:** `error` - **Status:** v0.3

A cycle in the dependency graph. Requires building the full reference graph; the level drops to `info` when the workbook has iterative calculation enabled.

---

### SF010 - Cache disagrees with recomputation

**Level:** `error` - **Status:** v0.3 - **requires an evaluator**

**What it catches.** A cached value that does not match the result of recomputation. It means the file was edited without recalculating, and the recipient is reading stale numbers.

**How it is detected.** A conservative mini-evaluator over a whitelist: arithmetic, `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT` over ranges of numeric constants. Anything outside the whitelist is skipped silently. A finding appears only when we are certain the expression was evaluated in full.

**Why it matters.** This is the one check that seeds a future formula engine while staying safe: an incomplete evaluator produces misses, never false positives.

---

# SW - workbook hygiene

### SW001 - Hidden rows inside an aggregated range

**Level:** `warning` - **Status:** v0.2

The reader sees one set of addends; the formula counts another.

### SW002 - Merged cells inside a data block

**Level:** `warning` - **Status:** v0.2

They break `VLOOKUP`, sorting and row-wise import. Merges in the header row are not flagged.

### SW003 - Named range points nowhere

**Level:** `error` - **Status:** v0.2

### SW004 - Workbook contains VBA macros

**Level:** `info` - **Status:** v0.1

Not a problem in itself, but an honest statement of where the analysis stops: macro contents are not inspected, and no finding accounts for what that code does.

### SW005 - Hidden sheet

**Level:** `info` - **Status:** v0.1

Whoever opens the file will not see it, though visible sheets may reference it.

---

# DF - version differences

The `sheetsentry diff old.xlsx new.xlsx` command. The point is code review for spreadsheets: show changes in structure rather than in values, because values change constantly while structure changes rarely and deliberately.

| ID | Finding | Level |
|---|---|---|
| `DF001` | Formula changed | `info` |
| `DF002` | Formula replaced by a constant | `error` |
| `DF003` | Constant replaced by a formula | `info` |
| `DF004` | Range boundaries in a formula changed | `warning` |
| `DF005` | Sheet added, removed or renamed | `warning` |
| `DF006` | Named range changed or deleted | `warning` |
| `DF010` | Schema drift: columns reordered, renamed, added or removed | `error` |
| `DF011` | Column number format changed (percent vs fraction, currency) | `warning` |

`DF010` is the decisive check for the file-exchange scenario: a reordering of columns in a weekly feed is the failure that arrives most quietly.

---

## Deliberately out of scope

- **The business meaning of numbers is not judged.** "Margin cannot exceed 100%" is one company's rule and belongs in a `sheetsentry test` YAML config, not in the default set.
- **`.xls`, VBA, Power Query, external connections and add-ins are not supported** in v0.1. The boundary is stated in the README rather than discovered by experiment.
- **The file is never repaired.** The tool reports and proves; a human edits.

---

## Implementation order

| Version | Contents |
|---|---|
| **0.1** | `audit`: SD001-SD005, SF001-SF005, SW004-SW005. text/json/sarif reports, exit codes, GitHub Action |
| **0.2** | `diff`: DF001-DF006, DF010-DF011. Checks SD006, SF006, SW001-SW003 |
| **0.3** | `test` with YAML rules. SF007, SF010 (mini-evaluator). Google Sheets monitoring, already part of the paid tier |
