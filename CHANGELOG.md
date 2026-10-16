# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed

- The repository is public. The README no longer asks for private-repository
  access or a contents-read token; another repository uses the Action directly
  as `HlinorAI/sheetsentry@<commit-sha>`.

### Fixed

- The composite GitHub Action installs SheetSentry from the action's own
  checked-out source (`github.action_path`, passed through a step environment
  variable and a quoted shell argument) instead of `pip install sheetsentry`,
  which targeted a PyPI package that does not exist and always failed.
- Aggregate SARIF (multi-file or failed audits) is valid against the official
  OASIS SARIF 2.1.0 schema: tool execution notifications moved from the run
  level into `run.invocations[0]` with an `executionSuccessful` flag (the run
  object forbids additional properties). CI validates every generated SARIF
  document against the pinned official schema, including a negative control
  that must reject the old layout.
- Auditing several files with `--format json` or `--format sarif` now writes
  one valid document instead of concatenated per-file documents. The JSON
  multi-file shape is an envelope `{"reports": [...], "errors": [...]}` whose
  entries keep the single-file payload; `errors` lists unreadable files. The
  multi-file SARIF document has one run with deduplicated rule descriptors,
  results carrying the original workbook path (directories included, spaces
  URI-encoded) and an `artifacts` list that includes clean workbooks;
  unreadable files become tool execution notifications. A single-file audit
  keeps the original shapes. Exit priority is unchanged: clean 0, findings at
  or above the threshold 1, unreadable input 2 even with `--fail-on never`.
- `review` given a multi-file JSON envelope now exits 2 with an explanation
  instead of failing on reconciliation.
- The Action `files` input accepts one literal path containing spaces (used
  as-is when it names exactly one existing file); glob/list behavior is
  otherwise unchanged.

### Changed

- SARIF `informationUri` now points at the real source repository
  (https://github.com/HlinorAI/sheetsentry).

### Added

- CI runs an `action-smoke` job that executes the real composite action from a
  separate checkout in a synthetic consumer workspace: asserts SheetSentry is
  not preinstalled, generates workbooks including a filename with spaces and
  distinct per-file findings, exercises the default recursive pattern, a
  literal spaced path and a JSON envelope, validates the SARIF report, the
  envelope mapping and the installed-source metadata (`direct_url.json`). The
  3 OS x 4 Python test matrix is unchanged.
- `README.md` documents source-only installation (private repo, Python
  3.10+), the composite Action (same-repo and cross-repo private patterns
  with a contents-read token placeholder), the `files` input semantics, and
  the multi-file output shapes with the single-file `review` limitation.

### History note

No dependency, version, or CLI flag changes in this update; the 0.1.0
package remains unpublished.
