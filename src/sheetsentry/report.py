"""Output: text for humans, JSON for scripts, SARIF for GitHub.

The text report is plain ASCII on purpose. Box-drawing and check-mark glyphs
render as mojibake on a Windows console that is not in UTF-8 mode, and the
severity is already stated by the section heading.
"""

from __future__ import annotations

import json
import urllib.parse
from collections import Counter
from pathlib import Path

from .checks import DIFF_REGISTRY, REGISTRY
from .finding import Finding, Severity
from .text import n_plural

_INFORMATION_URI = "https://github.com/HlinorAI/sheetsentry"

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


def text(path: Path, findings: list[Finding], title: str | None = None) -> str:
    lines = [title or path.name]

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


def as_json(path: Path, findings: list[Finding], title: str | None = None) -> str:
    counts = Counter(f.severity.value for f in findings)
    payload = {
        "file": str(path),
        "subject": title or path.name,
        "summary": {
            "total": len(findings),
            "error": counts.get("error", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
        },
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def as_sarif(path: Path, findings: list[Finding], title: str | None = None) -> str:
    """SARIF 2.1.0 for GitHub code scanning.

    A limitation worth knowing: a spreadsheet cell has no line number in the
    file, yet SARIF requires a physical location. We report line 1 and put the
    real address (`Sheet!B12`) in the message text. Without a location GitHub
    rejects the upload.
    """
    # Rule metadata lives in two registries: audit rules and diff rules.
    # SARIF needs a descriptor for every ruleId it sees, whichever produced it.
    known = {**REGISTRY, **DIFF_REGISTRY}
    used = sorted({f.rule for f in findings})
    rules = [
        {
            "id": rule,
            "name": known[rule].title,
            "shortDescription": {"text": known[rule].title},
            "fullDescription": {"text": known[rule].summary},
            "defaultConfiguration": {"level": _SARIF_LEVEL[known[rule].severity]},
        }
        for rule in used
        if rule in known
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
                            "informationUri": _INFORMATION_URI,
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


def _artifact_uri(path: Path) -> str:
    """Relative forward-slash URI for a workbook, spaces encoded.

    The full given path (directories included) is kept so that two files with
    the same basename in different directories stay distinguishable.
    """
    return urllib.parse.quote(path.as_posix(), safe="/:")


def _sarif_rules(findings_lists: list[list[Finding]]) -> list[dict]:
    """One descriptor per distinct ruleId across all inputs, deduplicated."""
    known = {**REGISTRY, **DIFF_REGISTRY}
    used = sorted({finding.rule for findings in findings_lists for finding in findings})
    return [
        {
            "id": rule,
            "name": known[rule].title,
            "shortDescription": {"text": known[rule].title},
            "fullDescription": {"text": known[rule].summary},
            "defaultConfiguration": {"level": _SARIF_LEVEL[known[rule].severity]},
        }
        for rule in used
        if rule in known
    ]


def aggregate_json(
    entries: list[tuple[Path, list[Finding] | None, str | None]],
) -> str:
    """One JSON object for several workbooks (or any failed single run).

    `reports` holds the usual per-file payload for every successfully read
    workbook; `errors` records the files that could not be opened, so a bad
    file is never presented as a clean one. Single-file successful audits keep
    the original root shape instead.
    """
    reports: list[dict] = []
    errors: list[dict] = []
    for path, findings, error in entries:
        if error is not None:
            errors.append({"file": str(path), "error": error})
        else:
            reports.append(json.loads(as_json(path, findings or [])))
    return json.dumps(
        {"reports": reports, "errors": errors}, ensure_ascii=False, indent=2
    )


def aggregate_sarif(
    entries: list[tuple[Path, list[Finding] | None, str | None]],
) -> str:
    """One SARIF 2.1.0 document for several workbooks (or any failed run).

    One run; rule descriptors deduplicated across inputs; results keep the
    original workbook path and the cell address in the message. `artifacts`
    lists every successfully processed workbook, clean ones included, so the
    coverage of multiple inputs is observable even without findings. Files
    that could not be opened become tool execution notifications instead of
    silently disappearing.
    """
    successful = [
        (path, findings or []) for path, findings, error in entries if error is None
    ]
    rules = _sarif_rules([findings for _, findings in successful])

    results: list[dict] = []
    artifacts: list[dict] = []
    notifications: list[dict] = []
    seen_uris: set[str] = set()
    for path, findings, error in entries:
        if error is not None:
            notifications.append(
                {
                    "level": "error",
                    "message": {"text": f"{path}: {error}"},
                }
            )
            continue
        uri = _artifact_uri(path)
        if uri not in seen_uris:
            seen_uris.add(uri)
            artifacts.append({"location": {"uri": uri}})
        for finding in findings:
            results.append(
                {
                    "ruleId": finding.rule,
                    "level": _SARIF_LEVEL[finding.severity],
                    "message": {"text": f"{finding.location()}: {finding.message}"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": uri},
                                "region": {"startLine": 1},
                            }
                        }
                    ],
                }
            )

    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "SheetSentry",
                            "informationUri": _INFORMATION_URI,
                            "rules": rules,
                        }
                    },
                    "invocations": [
                        {
                            # SARIF 2.1.0 keeps tool execution notifications
                            # under run.invocations[], not on the run itself
                            # (the run object forbids additional properties).
                            "executionSuccessful": not notifications,
                            "toolExecutionNotifications": notifications,
                        }
                    ],
                    "artifacts": artifacts,
                    "results": results,
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def render(fmt: str, path: Path, findings: list[Finding], title: str | None = None) -> str:
    if fmt == "json":
        return as_json(path, findings, title)
    if fmt == "sarif":
        return as_sarif(path, findings, title)
    return text(path, findings, title)
