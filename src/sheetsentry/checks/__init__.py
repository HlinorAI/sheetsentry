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


@dataclass(frozen=True)
class CheckMeta:
    rule: str
    title: str
    severity: Severity
    """Default level. An individual finding may raise or lower it."""
    summary: str
    fn: CheckFn


REGISTRY: dict[str, CheckMeta] = {}


def check(rule: str, title: str, severity: Severity, summary: str):
    def decorator(fn: CheckFn) -> CheckFn:
        if rule in REGISTRY:
            raise ValueError(f"Rule {rule} is already registered")
        REGISTRY[rule] = CheckMeta(rule, title, severity, summary, fn)
        return fn

    return decorator


def selected_rules(select: list[str] | None, ignore: list[str] | None) -> list[str]:
    """Select rules by exact id or by family prefix (`SD`)."""
    rules = sorted(REGISTRY)

    def matches(rule: str, patterns: list[str]) -> bool:
        return any(rule == p.upper() or rule.startswith(p.upper()) for p in patterns)

    if select:
        rules = [r for r in rules if matches(r, select)]
    if ignore:
        rules = [r for r in rules if not matches(r, ignore)]
    return rules


def run(
    book: Book, select: list[str] | None = None, ignore: list[str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in selected_rules(select, ignore):
        findings.extend(REGISTRY[rule].fn(book))

    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    findings.sort(key=lambda f: (order[f.severity], f.rule, f.sheet, f.cells[:1]))
    return findings


# Importing the check modules populates the registry. Kept at the bottom
# because those modules import `check` from here.
from . import data, formulas, hygiene  # noqa: E402,F401
