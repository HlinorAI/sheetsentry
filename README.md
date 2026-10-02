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

SheetSentry is not on PyPI. Install from a checkout of this repository
(requires access to this private repo and Python 3.10+):

```bash
git clone https://github.com/HlinorAI/sheetsentry.git
cd sheetsentry
pip install .
```

or straight from the repository URL:

```bash
pip install git+https://github.com/HlinorAI/sheetsentry.git
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
sheetsentry review audit-report.json --state review-state.json  # recheck findings locally
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

The repository ships a composite GitHub Action that installs SheetSentry from
the action's own checked-out source — nothing is fetched from PyPI, because
there is no SheetSentry package there. The consumer workflow needs Python
3.10+ set up first (the action installs with `pip`), and access to this
private repository.

Same repository:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
- uses: ./ # this repo's action.yml
  with:
    files: data/*.xlsx
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: sheetsentry.sarif
```

Another (private) repository: check out the consumer repo first, then the
action source, using a token that has **contents: read** on this repository
(create the token yourself; the examples below only reference it):

```yaml
- uses: actions/checkout@v4            # the consumer repository
- uses: actions/checkout@v4            # the action's source
  with:
    repository: HlinorAI/sheetsentry
    token: ${{ secrets.SHEETSSENTRY_SOURCE_READ }}
    path: sheetsentry-action
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
- uses: ./sheetsentry-action
  with:
    files: data/*.xlsx
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: sheetsentry.sarif
```

`files` accepts a glob (`data/*.xlsx`, recursive with `**`), several
space-separated patterns, or one literal path — a path containing spaces
works when it names exactly one existing file:

```yaml
- uses: ./sheetsentry-action
  with:
    files: reports/final report.xlsx
```

#### Multi-file output

Auditing several files at once produces **one** JSON document or **one**
SARIF document, not a concatenation:

- JSON is an envelope `{"reports": [...], "errors": [...]}` where each entry
  of `reports` has the same shape as a single-file report (`file`, `subject`,
  `summary`, `findings`); `errors` lists files that could not be opened.
  A single-file audit keeps the original root shape.
- SARIF 2.1.0 has one run; results carry the original workbook path
  (directories included, spaces URI-encoded), rule descriptors are
  deduplicated, and every successfully processed workbook — clean ones too —
  is listed under `artifacts`. Unreadable files become tool execution
  notifications instead of silently disappearing.
- The `review` command works on a single-file JSON report. Given a multi-file
  envelope it exits with code 2 and an explanation instead of mixing findings
  from different files; extract the entry you need from `reports` first.

## What gets checked

**Data and exchange (`SD`)** - what breaks the receiving system:

| | |
|---|---|
| `SD001` | Numbers stored as text |
| `SD002` | Invisible characters: non-breaking spaces, edge whitespace |
| `SD003` | Duplicates in a key column |
| `SD004` | Mixed types in a column |
| `SD005` | Dates stored as text |
| `SD006` | Blank row inside a table |

**Formulas (`SF`)** - what quietly corrupts a calculation:

| | |
|---|---|
| `SF001` | Formula replaced by a constant |
| `SF002` | Formula breaks the pattern |
| `SF003` | Aggregate range misses data |
| `SF004` | Error values `#REF!`, `#DIV/0!` |
| `SF005` | Constant hardcoded into a formula |
| `SF006` | Reference to another workbook |

**Hygiene (`SW`)** - structure that reads differently to a human and to a machine, plus the boundaries of the analysis:

| | |
|---|---|
| `SW001` | Hidden rows inside an aggregated range |
| `SW002` | Merged cells inside a data block |
| `SW003` | Named range points nowhere |
| `SW004` `SW005` | Macros present, hidden sheets |

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

For the downstream review loop, JSON reports include a stable `finding_id`.
Keep a local `review-state.json` with `status` (`open`, `correction_required`,
`accepted-risk`, or `resolved`), `owner` and `next_action`, then reconcile a
later audit without editing the workbook:

```bash
sheetsentry review audit-report.json --state review-state.json --format text
```

When a correction-required finding is absent from the later audit it is shown
as `resolved`; a resolved finding that remains is shown as `reopened`. The
review command does not modify the state file or the spreadsheet.

## Roadmap

| Version | Contents |
|---|---|
| **0.1** | `audit` - checks with no configuration, text/json/sarif, GitHub Action |
| **0.2** | `diff` - two-version comparison including column schema drift |
| **0.3** | `test` - YAML rules for business invariants |

0.1 and 0.2 are complete: 25 checks, 17 in `audit` and 8 in `diff`.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest
```

A new check is one decorated function under `src/sheetsentry/checks/`: `@check` for a single-file rule, `@diff_check` for a two-version rule. Both registries and the `sheetsentry rules` listing build themselves. Each check needs two tests: a broken file produces a finding, a similar healthy file produces none.

## License

Apache-2.0
