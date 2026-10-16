# PROJECT_PLAN — SheetSentry

Checks and code review for business-critical `.xlsx` files crossing a company
boundary: 17 audit rules, 8 diff rules, a finding-review workflow, and SARIF
output for GitHub code scanning. One runtime dependency (`openpyxl`);
everything else is the standard library. Python 3.10+.

## Current state (2026-10-16)

- Public repository (Apache-2.0) since 2026-10-16, version `0.1.0`,
  **not published** to PyPI.
- Full test suite: 107 tests, CI matrix 3 OS x 4 Python versions.
- Composite GitHub Action (`action.yml`) runs the CLI on the caller's
  workbooks and installs SheetSentry **from the action's own checked-out
  source** (`github.action_path`) — not from PyPI, where no package exists.

## Current work (SHEETSENTRY-001)

- `action.yml`: installation step now installs the exact checked-out action
  source via a step environment variable; no PyPI lookup.
- `ci.yml`: an `action-smoke` job runs the real composite action from a
  separate checkout in a synthetic consumer workspace, starting from a
  clean environment (asserts SheetSentry is not preinstalled), validates the
  SARIF report and the installed-source metadata (`direct_url.json`).
- `README.md`: Install / In CI sections document source installation only and
  the Python 3.10+ prerequisite.
- No version bump, no dependency changes, no release in this change.

## Multi-file output (SHEETSENTRY-002)

- `audit` over several files emits one JSON envelope `{"reports": [...],
  "errors": [...]}` (per-file payloads keep the single-file shape; unreadable
  files are listed under `errors`) and one SARIF 2.1.0 document with a single
  run: deduplicated rules, results carrying the original workbook path with
  spaces URI-encoded, `artifacts` including clean workbooks, unreadable files
  as tool execution notifications. Single-file audits keep the original
  shapes. Exit priority: 0 clean / 1 findings / 2 unreadable input (even with
  `--fail-on never`).
- `review` is single-file by design; a multi-file envelope exits 2 with an
  explanation instead of mixing finding IDs across files.
- The Action `files` input takes a glob, a list, or one literal path
  (spaces supported when it names exactly one existing file).

## Governance

This repository is governed by the portfolio agent contract and coordination
workflow, which live outside this repository (shared workspace, not published
here). Product decisions and Git operations follow that contract: bounded
implementation tasks, independent review, explicit Owner acceptance, Git-only
remote stages.
