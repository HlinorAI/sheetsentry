"""Command line interface.

argparse from the standard library only: a tool with one dependency installs
in seconds and conflicts with nobody's environment. For three commands that
is enough.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import checks, report
from .checks import REGISTRY
from .finding import Severity, at_least
from .workbook import load

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def cmd_audit(args: argparse.Namespace) -> int:
    threshold = Severity(args.fail_on) if args.fail_on != "never" else None
    outputs: list[str] = []
    worst_hit = False
    failed = False

    for name in args.files:
        path = Path(name)
        if not path.exists():
            print(f"sheetsentry: file not found: {path}", file=sys.stderr)
            failed = True
            continue
        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            print(
                f"sheetsentry: {path.name} - only .xlsx and .xlsm are supported",
                file=sys.stderr,
            )
            failed = True
            continue

        try:
            book = load(path)
        except Exception as exc:  # noqa: BLE001 - the user needs a reason, not a traceback
            print(f"sheetsentry: cannot open {path.name}: {exc}", file=sys.stderr)
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
    for rule in sorted(REGISTRY):
        meta = REGISTRY[rule]
        print(f"{meta.rule}  {meta.severity.value:<8} {meta.title}")
        print(f"          {meta.summary}")
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

    diff = sub.add_parser("diff", help="Compare two versions of a file (v0.2)")
    diff.add_argument("old", nargs="?")
    diff.add_argument("new", nargs="?")
    diff.set_defaults(func=_not_yet("diff", "0.2"))

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
