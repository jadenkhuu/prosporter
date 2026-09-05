#!/usr/bin/env python3
"""Structured, per-record error model for the migration pipeline.

Every exception is PII-free by construction: only entity type, source id and a
slug/SKU-style reference are recorded, never a customer name, email or address.
Customers are referenced as ``customer:<woo_id>`` only.
"""
from __future__ import annotations

SEVERITIES = ("critical", "high", "medium", "low")
RETRY_STATUSES = ("auto-retryable", "needs-decision", "wont-fix", "resolved")

# Owner is who has to act, not who wrote the code.
OWNER_CLIENT = "client"
OWNER_AGENCY = "purpl"


class ExceptionCollector:
    """Collects structured errors and keeps them in a deterministic order."""

    def __init__(self) -> None:
        self._rows: list[dict] = []

    def add(
        self,
        *,
        record_type: str,
        record_id,
        record_ref: str,
        stage: str,
        severity: str,
        code: str,
        message: str,
        owner: str,
        retry_status: str = "needs-decision",
        detail: dict | None = None,
    ) -> dict:
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity {severity!r}")
        if retry_status not in RETRY_STATUSES:
            raise ValueError(f"unknown retry_status {retry_status!r}")
        row = {
            "record": {
                "type": record_type,
                "id": record_id,
                "ref": record_ref,
            },
            "stage": stage,
            "severity": severity,
            "code": code,
            "message": message,
            "owner": owner,
            "retry_status": retry_status,
            "detail": detail or {},
        }
        self._rows.append(row)
        return row

    def extend(self, rows) -> None:
        self._rows.extend(rows)

    @property
    def rows(self) -> list[dict]:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return sorted(
            self._rows,
            key=lambda r: (
                order[r["severity"]],
                r["code"],
                r["record"]["type"],
                str(r["record"]["id"]),
            ),
        )

    def by_severity(self) -> dict:
        counts = {s: 0 for s in SEVERITIES}
        for row in self._rows:
            counts[row["severity"]] += 1
        return counts

    def by_code(self) -> dict:
        counts: dict[str, int] = {}
        for row in self._rows:
            counts[row["code"]] = counts.get(row["code"], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def critical_count(self) -> int:
        return sum(1 for row in self._rows if row["severity"] == "critical")

    def ids_for(self, code: str) -> list:
        return [r["record"]["id"] for r in self._rows if r["code"] == code]
