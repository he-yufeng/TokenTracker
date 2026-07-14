"""Persistent named budgets.

The one-shot ``budget`` command answers "am I under $X in the last N days?" for a
single ad-hoc limit passed on the command line. This module persists *named*
budgets in the database, so a project declares its limits once — a total cap, a
per-model cap, a per-endpoint or per-tag cap — and checks every one of them
together. Each check reuses the same spend query the rest of the tool uses and
adds a run-rate estimate of when an on-track budget will breach.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from tokentracker.db import get_db
from tokentracker.query import summary


@dataclass(frozen=True)
class Budget:
    """A saved spending limit and the scope it applies to."""

    name: str
    limit_usd: float
    days: int = 30
    warn_at: float = 0.8
    model: str | None = None
    endpoint: str | None = None
    tag: str | None = None


def set_budget(
    name: str,
    limit_usd: float,
    *,
    days: int = 30,
    warn_at: float = 0.8,
    model: str | None = None,
    endpoint: str | None = None,
    tag: str | None = None,
    db_path: str | None = None,
) -> Budget:
    """Create or replace a named budget. Reusing a name overwrites it (upsert)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("budget name must be a non-empty string")
    if limit_usd <= 0:
        raise ValueError("limit_usd must be greater than zero")
    if not 0 < warn_at <= 1:
        raise ValueError("warn_at must be within the (0, 1] range")
    if days <= 0:
        raise ValueError("days must be greater than zero")

    conn = get_db(db_path)
    conn.execute(
        """INSERT INTO budgets
               (name, limit_usd, days, warn_at, model, endpoint, tag, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
               limit_usd = excluded.limit_usd,
               days      = excluded.days,
               warn_at   = excluded.warn_at,
               model     = excluded.model,
               endpoint  = excluded.endpoint,
               tag       = excluded.tag""",
        (name, float(limit_usd), int(days), float(warn_at), model, endpoint, tag, time.time()),
    )
    conn.commit()
    return Budget(name, float(limit_usd), int(days), float(warn_at), model, endpoint, tag)


def list_budgets(db_path: str | None = None) -> list[Budget]:
    """Return every saved budget, ordered by name."""
    conn = get_db(db_path)
    rows = conn.execute(
        "SELECT name, limit_usd, days, warn_at, model, endpoint, tag FROM budgets ORDER BY name"
    ).fetchall()
    return [Budget(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]


def remove_budget(name: str, db_path: str | None = None) -> bool:
    """Delete a budget by name. Returns True if a row was actually removed."""
    conn = get_db(db_path)
    cur = conn.execute("DELETE FROM budgets WHERE name = ?", ((name or "").strip(),))
    conn.commit()
    return cur.rowcount > 0


def _breach_in_days(budget: Budget, spent: float, db_path: str | None) -> int | None:
    """Days until spend crosses the limit at the recent run rate.

    Returns 0 if already over, ``None`` when there is no recent spend to project
    from (so the budget is not on track to breach). The rate is taken from the
    most recent slice of the window (capped at 7 days) so a check reacts to a
    current spike rather than being flattened by an idle earlier period.
    """
    if spent >= budget.limit_usd:
        return 0
    window = min(budget.days, 7)
    recent = summary(
        days=window, db_path=db_path, model=budget.model, endpoint=budget.endpoint, tag=budget.tag
    )
    daily = float(recent["total_cost_usd"]) / window
    if daily <= 0:
        return None
    return math.ceil((budget.limit_usd - spent) / daily)


def check_budget(budget: Budget, db_path: str | None = None) -> dict:
    """Evaluate one budget against current spend within its scope and window."""
    s = summary(
        days=budget.days,
        db_path=db_path,
        model=budget.model,
        endpoint=budget.endpoint,
        tag=budget.tag,
    )
    spent = float(s["total_cost_usd"])
    ratio = spent / budget.limit_usd if budget.limit_usd else 0.0
    status = "exceeded" if spent > budget.limit_usd else "warn" if ratio >= budget.warn_at else "ok"
    return {
        "name": budget.name,
        "status": status,
        "days": budget.days,
        "limit_usd": round(budget.limit_usd, 4),
        "spent_usd": round(spent, 4),
        "remaining_usd": round(max(budget.limit_usd - spent, 0.0), 4),
        "usage_pct": round(ratio * 100, 1),
        "total_calls": s["total_calls"],
        "total_tokens": s["total_tokens"],
        "scope": {"model": budget.model, "endpoint": budget.endpoint, "tag": budget.tag},
        "breach_in_days": _breach_in_days(budget, spent, db_path),
    }


def check_all(db_path: str | None = None) -> list[dict]:
    """Evaluate every saved budget. Empty list when none are defined."""
    return [check_budget(b, db_path=db_path) for b in list_budgets(db_path)]
