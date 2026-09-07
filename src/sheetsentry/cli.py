"""Command line interface.

argparse from the standard library only: a tool with one dependency installs
in seconds and conflicts with nobody's environment. For three commands that
is enough.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, report
from .checks import DIFF_REGISTRY, REGISTRY
from .finding import Severity, at_least
from .workbook import load
from .workflow import load_state, reconcile, render_text

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _load(name: str):
    """Open a workbook, or explain in one line why it could not be opened."""
    path = Path(name)
    if not path.exists():
        return None, f"sheetsentry: file not found: {path}"
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return None, f"sheetsentry: {path.name} - only .xlsx and .xlsm are supported"
    try:
        return load(path), None
    except Exception as exc:  # noqa: BLE001 - the user needs a reason, not a traceback
        return None, f"sheetsentry: cannot open {path.name}: {exc}"


def cmd_diff(args: argparse.Namespace) -> int:
    old_book, error = _load(args.old)
    if error:
        print(error, file=sys.stderr)
        return EXIT_ERROR
    new_book, error = _load(args.new)
    if error:
        print(error, file=sys.stderr)
        return EXIT_ERROR

    findings = checks.run_diff(
        old_book, new_book, select=_split(args.select), ignore=_split(args.ignore)
    )
    title = f"{Path(args.old).name} -> {Path(args.new).name}"
    body = report.render(args.format, Path(args.new), findings, title=title)

    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    else:
        print(body)

    if args.fail_on == "never":
        return EXIT_OK
    threshold = Severity(args.fail_on)
    return EXIT_FINDINGS if any(at_least(f.severity, threshold) for f in findings) else EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    threshold = Severity(args.fail_on) if args.fail_on != "never" else None
    outputs: list[str] = []
    worst_hit = False
    failed = False

    for name in args.files:
        path = Path(name)
        book, error = _load(name)
        if error:
            print(error, file=sys.stderr)
            failed = True
            continue

        findings = checks.run(book, select=_split(args.select), ignore=_split(args.ignore))
        outputs.append(report.render(args.format, path, findings))

        if threshold and any(at_least(f.severity, threshold) for f in findings):
            worst_hit = True

    body = "\n\n".join(outputs)
    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    else:
        print(body)

    if failed:
        return EXIT_ERROR
    return EXIT_FINDINGS if worst_hit else EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    for heading, registry in (("audit", REGISTRY), ("diff", DIFF_REGISTRY)):
        print(f"{heading}:")
        for rule in sorted(registry):
            meta = registry[rule]
            print(f"  {meta.rule}  {meta.severity.value:<8} {meta.title}")
            print(f"            {meta.summary}")
        print()
    return EXIT_OK


def cmd_review(args: argparse.Namespace) -> int:
    try:
        report_payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
        state = load_state(Path(args.state))
        result = reconcile(report_payload, state)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"sheetsentry: review failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    body = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_text(result)
    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    else:
        print(body)
    return EXIT_OK


def _not_yet(name: str, version: str):
    def handler(args: argparse.Namespace) -> int:
        print(
            f"sheetsentry: the '{name}' command arrives in version {version}.\n"
            f"Specification: docs/CHECKS.md",
            file=sys.stderr,
        )
        return EXIT_ERROR

    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheetsentry",
        description=(
            "Check .xlsx files for the breakage that stops imports "
            "and quietly corrupts calculations."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser(
        "audit",
        help="Check a file with no setup at all",
        description="Runs every check. No configuration required.",
    )
    audit.add_argument("files", nargs="+", metavar="FILE")
    audit.add_argument(
        "--format", choices=["text", "json", "sarif"], default="text", help="output format"
    )
    audit.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "never"],
        default="error",
        help="severity that makes the command exit 1 (default: error)",
    )
    audit.add_argument("--select", metavar="IDS", help="only these rules: SD001,SF or SD")
    audit.add_argument("--ignore", metavar="IDS", help="exclude these rules: SF005,SW")
    audit.add_argument("-o", "--output", metavar="PATH", help="write the report to a file")
    audit.set_defaults(func=cmd_audit)

    rules = sub.add_parser("rules", help="List every rule")
    rules.set_defaults(func=cmd_rules)

    review = sub.add_parser("review", help="Reconcile an audit report with a local review state")
    review.add_argument("report", metavar="REPORT.json")
    review.add_argument("--state", required=True, metavar="STATE.json")
    review.add_argument("--format", choices=["text", "json"], default="text")
    review.add_argument("-o", "--output", metavar="PATH", help="write the reconciliation to a file")
    review.set_defaults(func=cmd_review)

    diff = sub.add_parser(
        "diff",
        help="Compare two versions of the same file",
        description=(
            "Reports how the structure changed, not how the numbers changed. "
            "Values move every week; columns and formulas move rarely and on purpose."
        ),
    )
    diff.add_argument("old", metavar="OLD")
    diff.add_argument("new", metavar="NEW")
    diff.add_argument("--format", choices=["text", "json", "sarif"], default="text")
    diff.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "never"],
        default="error",
        help="severity that makes the command exit 1 (default: error)",
    )
    diff.add_argument("--select", metavar="IDS", help="only these rules: DF010 or DF")
    diff.add_argument("--ignore", metavar="IDS", help="exclude these rules: DF001")
    diff.add_argument("-o", "--output", metavar="PATH", help="write the report to a file")
    diff.set_defaults(func=cmd_diff)

    test = sub.add_parser("test", help="Check a file against YAML rules (v0.3)")
    test.add_argument("files", nargs="*")
    test.add_argument("-c", "--config")
    test.set_defaults(func=_not_yet("test", "0.3"))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
