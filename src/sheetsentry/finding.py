"""A finding is the unit of output.

Rule from the spec: a finding without a cell address is not a finding.
That is why `sheet` and `cells` are required and `evidence` carries something
the user can look at and check us against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


def at_least(value: Severity, threshold: Severity) -> bool:
    """Whether `value` reaches `threshold`."""
    return _ORDER[value] >= _ORDER[threshold]


@dataclass
class Finding:
    rule: str
    """Rule identifier: SD001, SF002, ..."""

    title: str
    """Short rule name, identical across every finding of that rule."""

    severity: Severity

    message: str
    """Plain-language explanation of this particular finding."""

    sheet: str
    """Empty when the finding is about the workbook as a whole."""

    cells: list[str] = field(default_factory=list)
    """Addresses. The first one is primary, the rest are examples."""

    evidence: str | None = None
    """Formula text or value: the proof."""

    count: int | None = None
    """Total cells affected when the finding is aggregated over a column."""

    def location(self) -> str:
        if not self.sheet:
            return "whole workbook"
        if not self.cells:
            return self.sheet
        head = self.cells[0]
        if self.count and self.count > len(self.cells):
            return f"{self.sheet}!{head} (+{self.count - 1})"
        if len(self.cells) > 1:
            return f"{self.sheet}!{head} (+{len(self.cells) - 1})"
        return f"{self.sheet}!{head}"

    @property
    def finding_id(self) -> str:
        """Stable local identity used to connect a finding to a recheck."""
        identity = "\x00".join([
            self.rule,
            self.sheet,
            ",".join(self.cells),
            self.evidence or "",
        ]).casefold()
        return f"finding_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "rule": self.rule,
            "title": self.title,
            "severity": self.severity.value,
            "message": self.message,
            "sheet": self.sheet,
            "cells": self.cells,
            "evidence": self.evidence,
            "count": self.count if self.count is not None else len(self.cells),
        }
