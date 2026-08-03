"""Check registry.

A check is a `Book -> Iterator[Finding]` function registered with the
`@check` decorator. Adding a new check touches no file but its own: the
registry and the `sheetsentry rules` listing are built from the decorators.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from ..finding import Finding, Severity
from ..workbook import Book

CheckFn = Callable[[Book], Iterator[Finding]]
DiffFn = Callable[[Book, Book], Iterator[Finding]]


@dataclass(frozen=True)
class CheckMeta:
    rule: str
    title: str
    severity: Severity
    """Default level. An individual finding may raise or lower it."""
    summary: str
    fn: CheckFn | DiffFn


REGISTRY: dict[str, CheckMeta] = {}
"""Single-file checks, run by `sheetsentry audit`."""

DIFF_REGISTRY: dict[str, CheckMeta] = {}
"""Two-file checks, run by `sheetsentry diff`."""


def _register(target: dict[str, CheckMeta], rule, title, severity, summary):
    def decorator(fn):
        if rule in REGISTRY or rule in DIFF_REGISTRY:
            raise ValueError(f"Rule {rule} is already registered")
        target[rule] = CheckMeta(rule, title, severity, summary, fn)
        return fn

    return decorator


def check(rule: str, title: str, severity: Severity, summary: str):
    return _register(REGISTRY, rule, title, severity, summary)


def diff_check(rule: str, title: str, severity: Severity, summary: str):
    return _register(DIFF_REGISTRY, rule, title, severity, summary)


def _select(
    registry: dict[str, CheckMeta], select: list[str] | None, ignore: list[str] | None
) -> list[str]:
    """Select rules by exact id or by family prefix (`SD`)."""
    rules = sorted(registry)

    def matches(rule: str, patterns: list[str]) -> bool:
        return any(rule == p.upper() or rule.startswith(p.upper()) for p in patterns)

    if select:
        rules = [r for r in rules if matches(r, select)]
    if ignore:
        rules = [r for r in rules if not matches(r, ignore)]
    return rules


def selected_rules(select: list[str] | None, ignore: list[str] | None) -> list[str]:
    return _select(REGISTRY, select, ignore)


_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _sorted(findings: list[Finding]) -> list[Finding]:
    findings.sort(key=lambda f: (_ORDER[f.severity], f.rule, f.sheet, f.cells[:1]))
    return findings


def run(
    book: Book, select: list[str] | None = None, ignore: list[str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in _select(REGISTRY, select, ignore):
        findings.extend(REGISTRY[rule].fn(book))
    return _sorted(findings)


def run_diff(
    old: Book, new: Book, select: list[str] | None = None, ignore: list[str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in _select(DIFF_REGISTRY, select, ignore):
        findings.extend(DIFF_REGISTRY[rule].fn(old, new))
    return _sorted(findings)


# Importing the check modules populates the registries. Kept at the bottom
# because those modules import the decorators from here.
from . import data, formulas, hygiene, versions  # noqa: E402,F401
