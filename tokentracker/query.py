"""Query functions for analyzing tracked usage data."""

from __future__ import annotations

from tokentracker.db import get_db


def summary(days: int = 30, db_path: str | None = None) -> dict:
    """Get a summary of usage over the last N days."""
    conn = get_db(db_path)
    cur = conn.execute(
        """SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(AVG(latency_ms), 0) as avg_latency,
            COUNT(DISTINCT model) as models_used
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'""",
        (f"-{days} days",),
    )
    row = cur.fetchone()
    return {
        "total_calls": row[0],
        "total_input_tokens": row[1],
        "total_output_tokens": row[2],
        "total_tokens": row[3],
        "total_cost_usd": round(row[4], 4),
        "avg_latency_ms": round(row[5], 1),
        "models_used": row[6],
    }


def recent(limit: int = 20, days: int | None = None, db_path: str | None = None) -> list[dict]:
    """Get the most recent API calls."""
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    where = ""
    params: list[object] = []
    if days is not None:
        where = "WHERE timestamp > unixepoch('now', ?)"
        params.append(f"-{days} days")
    params.append(limit)
    cur = conn.execute(
        """SELECT timestamp, model, input_tokens, output_tokens,
                  total_tokens, cost_usd, latency_ms, status, error
        FROM calls {where}
        ORDER BY timestamp DESC LIMIT ?""".format(where=where),
        params,
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def cost_by_model(days: int = 30, db_path: str | None = None) -> list[dict]:
    """Get cost breakdown by model."""
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    cur = conn.execute(
        """SELECT
            model,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cost_usd) as total_cost,
            AVG(latency_ms) as avg_latency
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'
        GROUP BY model
        ORDER BY total_cost DESC""",
        (f"-{days} days",),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def cost_by_day(days: int = 30, db_path: str | None = None) -> list[dict]:
    """Get daily cost breakdown."""
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    cur = conn.execute(
        """SELECT
            date(timestamp, 'unixepoch') as date,
            COUNT(*) as calls,
            SUM(total_tokens) as tokens,
            SUM(cost_usd) as cost
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'
        GROUP BY date(timestamp, 'unixepoch')
        ORDER BY date DESC""",
        (f"-{days} days",),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}
