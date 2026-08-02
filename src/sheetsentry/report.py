"""Output: text for humans, JSON for scripts, SARIF for GitHub.

The text report is plain ASCII on purpose. Box-drawing and check-mark glyphs
render as mojibake on a Windows console that is not in UTF-8 mode, and the
severity is already stated by the section heading.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .checks import REGISTRY
from .finding import Finding, Severity
from .text import n_plural

_HEADING = {
    Severity.ERROR: "ERRORS",
    Severity.WARNING: "WARNINGS",
    Severity.INFO: "NOTES",
}
_COUNTED = {
    Severity.ERROR: ("error", "errors"),
    Severity.WARNING: ("warning", "warnings"),
    Severity.INFO: ("note", "notes"),
}
_SARIF_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}


def text(path: Path, findings: list[Finding]) -> str:
    lines = [f"{path.name}"]

    if not findings:
        lines.append("  No findings.")
        return "\n".join(lines)

    counts = Counter(f.severity for f in findings)
    for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        lines.append("")
        lines.append(f"{_HEADING[severity]} ({len(group)})")
        for finding in group:
            lines.append(f"  {finding.rule}  {finding.location()}")
            lines.append(f"      {finding.message}")
            if finding.evidence:
                lines.append(f"      > {finding.evidence}")

    lines.append("")
    summary = ", ".join(
        n_plural(counts[s], *_COUNTED[s])
        for s in (Severity.ERROR, Severity.WARNING, Severity.INFO)
        if counts[s]
    )
    lines.append(f"Total: {n_plural(len(findings), 'finding', 'findings')} ({summary})")
    return "\n".join(lines)


def as_json(path: Path, findings: list[Finding]) -> str:
    counts = Counter(f.severity.value for f in findings)
    payload = {
        "file": str(path),
        "summary": {
            "total": len(findings),
            "error": counts.get("error", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
        },
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def as_sarif(path: Path, findings: list[Finding]) -> str:
    """SARIF 2.1.0 for GitHub code scanning.

    A limitation worth knowing: a spreadsheet cell has no line number in the
    file, yet SARIF requires a physical location. We report line 1 and put the
    real address (`Sheet!B12`) in the message text. Without a location GitHub
    rejects the upload.
    """
    used = sorted({f.rule for f in findings})
    rules = [
        {
            "id": rule,
            "name": REGISTRY[rule].title,
            "shortDescription": {"text": REGISTRY[rule].title},
            "fullDescription": {"text": REGISTRY[rule].summary},
            "defaultConfiguration": {"level": _SARIF_LEVEL[REGISTRY[rule].severity]},
        }
        for rule in used
        if rule in REGISTRY
    ]

    results = [
        {
            "ruleId": finding.rule,
            "level": _SARIF_LEVEL[finding.severity],
            "message": {"text": f"{finding.location()}: {finding.message}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": path.name},
                        "region": {"startLine": 1},
                    }
                }
            ],
        }
        for finding in findings
    ]

    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "SheetSentry",
                            "informationUri": "https://github.com/sheetsentry/sheetsentry",
                            "rules": rules,
                        }
                    },
                    "results": results,
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def render(fmt: str, path: Path, findings: list[Finding]) -> str:
    if fmt == "json":
        return as_json(path, findings)
    if fmt == "sarif":
        return as_sarif(path, findings)
    return text(path, findings)
