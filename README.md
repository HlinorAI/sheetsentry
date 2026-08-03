# SheetSentry

**Spreadsheet checks for people who receive other companies' files.**

A supplier price list, a bank report, a template your client filled in, an export headed for your ERP. The file arrives every week, looks fine, and breaks the import. Or it does not break anything and quietly delivers wrong numbers.

```bash
sheetsentry audit supplier-feed.xlsx
```

No configuration. No signup. One file in, a list of findings with cell addresses out.

```
supplier-feed.xlsx

ERRORS (2)
  SD003  Price!A47 (+1)
      Column A 'SKU' looks like a key (named 'SKU') but holds 1 duplicated value.
      > 'A-1120' appears 2 times
  SF003  Budget!B58
      The formula in B58 aggregates column B 'Amount' up to row 55, but data
      continues to row 57. 2 values are left out of the total.
      > =SUM(B2:B55)

WARNINGS (1)
  SD001  Price!C12 (+3)
      Column C 'Price': 4 values are stored as text while 118 neighbours are
      a real number. Aggregates will not see these cells.
      > '1 250'

Total: 3 findings (2 errors, 1 warning)
```

---

## Install

```bash
pip install sheetsentry
```

One dependency, `openpyxl`. Nothing else comes along.

## Use

```bash
sheetsentry audit file.xlsx                  # check it
sheetsentry diff last-week.xlsx this-week.xlsx   # what changed in the new version
sheetsentry audit *.xlsx --format json       # for a script
sheetsentry audit file.xlsx --format sarif   # for GitHub code scanning
sheetsentry audit file.xlsx --select SD      # data checks only
sheetsentry audit file.xlsx --ignore SF005   # everything but hardcoded constants
sheetsentry rules                            # list every rule
```

### Comparing two versions

When the same file arrives every week, the question is not "what is in it" but "what moved". `diff` answers that, and deliberately ignores the numbers: values change every time, structure does not.

```
feed-w1.xlsx -> feed-w2.xlsx

ERRORS (3)
  DF002  Budget!C6
      1 cell that computed a value now holds a typed-in number.
      > was =B6*1.21; now 726
  DF010  Price
      2 columns changed position. An importer reading by column index will keep
      working and write the wrong field.
      > 'Price' C -> B, 'Name' B -> C
  DF010  Price!D1
      Column D was renamed from 'Stock' to 'Qty'. A receiver matching columns by
      name will stop finding this field.
      > 'Stock' -> 'Qty'

WARNINGS (1)
  DF004  Budget!B14
      1 aggregate covers a different span than in the previous version.
      > was =SUM(B2:B11); now =SUM(B2:B10)

Total: 4 findings (3 errors, 1 warning)
```

Exit codes: `0` clean, `1` findings at or above `--fail-on` (default `error`), `2` the file could not be opened.

### In CI

```yaml
- run: pip install sheetsentry
- run: sheetsentry audit data/*.xlsx --format sarif -o results.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: results.sarif
```

## What gets checked

**Data and exchange (`SD`)** - what breaks the receiving system:

| | |
|---|---|
| `SD001` | Numbers stored as text |
| `SD002` | Invisible characters: non-breaking spaces, edge whitespace |
| `SD003` | Duplicates in a key column |
| `SD004` | Mixed types in a column |
| `SD005` | Dates stored as text |

**Formulas (`SF`)** - what quietly corrupts a calculation:

| | |
|---|---|
| `SF001` | Formula replaced by a constant |
| `SF002` | Formula breaks the pattern |
| `SF003` | Aggregate range misses data |
| `SF004` | Error values `#REF!`, `#DIV/0!` |
| `SF005` | Constant hardcoded into a formula |

**Hygiene (`SW`)** - the boundaries of the analysis: macros, hidden sheets.

**Version differences (`DF`)** - what `sheetsentry diff` reports:

| | |
|---|---|
| `DF010` | Schema drift: columns reordered, renamed, added or removed |
| `DF002` | Formula replaced by a constant |
| `DF004` | Aggregate range changed |
| `DF011` | Column number format changed |
| `DF001` `DF003` `DF005` `DF006` | Formula edits, new sheets, named ranges |

Every check, including its false-positive risk, is described in [docs/CHECKS.md](docs/CHECKS.md).

## What this tool does not do

Better said up front than discovered the hard way.

- **It does not evaluate formulas.** It reads structure and the values cached by Excel's last recalculation. If a file has never been recalculated, the report says so on its own line rather than staying quiet.
- **It does not support** `.xls`, VBA, Power Query, external connections or add-ins.
- **It does not judge the business meaning of numbers.** "Margin is never above 100%" is one company's rule; those checks belong to `sheetsentry test` with a YAML config.
- **It does not edit your file.** It reports and proves; a human decides.

## Roadmap

| Version | Contents |
|---|---|
| **0.1** | `audit` - checks with no configuration, text/json/sarif, GitHub Action |
| **0.2** | `diff` - two-version comparison including column schema drift |
| **0.3** | `test` - YAML rules for business invariants |

`diff` has landed. Still open in 0.2: hidden rows inside aggregated ranges, merged cells in data blocks, broken named ranges, external workbook references.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest
```

A new check is one decorated function under `src/sheetsentry/checks/`: `@check` for a single-file rule, `@diff_check` for a two-version rule. Both registries and the `sheetsentry rules` listing build themselves. Each check needs two tests: a broken file produces a finding, a similar healthy file produces none.

## License

Apache-2.0
