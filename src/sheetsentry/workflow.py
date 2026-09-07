"""Local finding lifecycle and recheck reconciliation for SheetSentry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


STATUSES = {"open", "correction_required", "accepted-risk", "resolved"}


@dataclass(frozen=True)
class Item:
    finding_id: str
    status: str
    owner: str
    next_action: str
    due_at: str | None = None
    accepted_risk_expires_at: str | None = None


def load_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("items"), list):
        raise ValueError("review state must contain version: 1 and an items list")
    for item in value["items"]:
        validate_item(item)
    return value


def validate_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError("review state items must be objects")
    for field in ("finding_id", "status", "owner", "next_action"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"review state item requires {field}")
    if item["status"] not in STATUSES:
        raise ValueError(f"unsupported review status: {item['status']}")
    if item["status"] in {"correction_required", "accepted-risk"}:
        _future(item.get("due_at"), "due_at")
    if item["status"] == "accepted-risk":
        _future(item.get("accepted_risk_expires_at"), "accepted_risk_expires_at")


def reconcile(report: dict[str, Any], state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("audit report must contain a findings list")
    current = {}
    for finding in findings:
        if not isinstance(finding, dict) or not finding.get("finding_id"):
            raise ValueError("audit findings must contain finding_id; regenerate the JSON report")
        current[str(finding["finding_id"])] = finding

    tracked = {item["finding_id"]: item for item in state["items"]}
    records: list[dict[str, Any]] = []
    for finding_id in current:
        item = tracked.get(finding_id)
        if item is None:
            records.append({"finding_id": finding_id, "status": "open", "present_in_audit": True, "verification": "untracked"})
            continue
        status = item["status"]
        if status == "resolved":
            status = "reopened"
        records.append({**item, "status": status, "present_in_audit": True, "verification": "still_present"})
    for item in state["items"]:
        if item["finding_id"] in current:
            continue
        status = "resolved" if item["status"] == "correction_required" else item["status"]
        records.append({**item, "status": status, "present_in_audit": False, "verification": "not_present_in_audit"})

    return {
        "version": 1,
        "report_file": report.get("file"),
        "finding_count": len(findings),
        "tracked_count": len(state["items"]),
        "records": records,
        "checked_at": now.isoformat(),
    }


def render_text(result: dict[str, Any]) -> str:
    lines = [
        "SheetSentry review reconciliation",
        f"Findings: {result['finding_count']}",
        f"Tracked: {result['tracked_count']}",
    ]
    for item in result["records"]:
        owner = f" owner={item['owner']}" if item.get("owner") else ""
        lines.append(f"- [{item['status']}] {item['finding_id']}{owner} verification={item['verification']}")
    return "\n".join(lines)


def _future(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review state requires {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"review state {field} must be an ISO timestamp") from exc
    if parsed <= datetime.now(parsed.tzinfo):
        raise ValueError(f"review state {field} must be in the future")
