"""Query functions for analyzing tracked usage data."""

from __future__ import annotations

from tokentracker.db import get_db
from tokentracker.pricing import blended_price, estimate_cost


def summary(
    days: int = 30,
    db_path: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
) -> dict:
    """Get a summary of usage over the last N days."""
    conn = get_db(db_path)
    filters = ["timestamp > unixepoch('now', ?)", "status = 'ok'"]
    params: list[object] = [f"-{days} days"]
    if model:
        filters.append("model = ?")
        params.append(model)
    if endpoint:
        filters.append("COALESCE(endpoint, 'unknown') = ?")
        params.append(endpoint)
    cur = conn.execute(
        f"""SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(AVG(latency_ms), 0) as avg_latency,
            COUNT(DISTINCT model) as models_used
        FROM calls
        WHERE {" AND ".join(filters)}""",
        params,
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


def spend_forecast(
    days: int = 7,
    forecast_days: int = 30,
    db_path: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
) -> dict:
    """Project spend and calls using the observed daily run rate."""
    observed = summary(days=days, db_path=db_path, model=model, endpoint=endpoint)
    daily_cost = float(observed["total_cost_usd"]) / days
    daily_calls = float(observed["total_calls"]) / days
    return {
        "lookback_days": days,
        "forecast_days": forecast_days,
        "observed_cost_usd": observed["total_cost_usd"],
        "observed_calls": observed["total_calls"],
        "daily_cost_usd": round(daily_cost, 4),
        "projected_cost_usd": round(daily_cost * forecast_days, 4),
        "projected_calls": round(daily_calls * forecast_days),
        "scope": {"model": model, "endpoint": endpoint},
    }


def model_comparison(
    days: int = 30,
    db_path: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
    candidates: list[str] | None = None,
) -> dict:
    """Re-price the observed token volume against every known model.

    Aggregates the input/output tokens of the scoped, successful calls and
    reprices that same workload on each candidate model, ranked cheapest first.
    Answers "what would my actual traffic cost on a different model or provider?".

    Token counts from chat and embedding calls are summed together, so scope the
    query with ``endpoint`` when those workloads should not be mixed.
    """
    from tokentracker.pricing import MODEL_PRICES

    conn = get_db(db_path)
    filters = ["timestamp > unixepoch('now', ?)", "status = 'ok'"]
    params: list[object] = [f"-{days} days"]
    if model:
        filters.append("model = ?")
        params.append(model)
    if endpoint:
        filters.append("COALESCE(endpoint, 'unknown') = ?")
        params.append(endpoint)
    cur = conn.execute(
        f"""SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens,
            COALESCE(SUM(cost_usd), 0) as current_cost,
            COALESCE(SUM(CASE WHEN cost_usd IS NOT NULL THEN 1 ELSE 0 END), 0) as priced_calls
        FROM calls
        WHERE {" AND ".join(filters)}""",
        params,
    )
    total_calls, input_tokens, output_tokens, current_cost, priced_calls = cur.fetchone()
    current_cost = float(current_cost)

    names = candidates if candidates else sorted(MODEL_PRICES)
    options = []
    for name in names:
        projected = estimate_cost(name, input_tokens, output_tokens)
        if projected is None:
            continue
        delta = projected - current_cost
        options.append(
            {
                "model": name,
                "projected_cost_usd": round(projected, 4),
                "delta_usd": round(delta, 4),
                "delta_pct": round(delta / current_cost * 100, 1) if current_cost > 0 else None,
            }
        )
    options.sort(key=lambda o: o["projected_cost_usd"])

    return {
        "days": days,
        "scope": {"model": model, "endpoint": endpoint},
        "total_calls": total_calls,
        "priced_calls": priced_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "current_cost_usd": round(current_cost, 4),
        "cheapest": options[0] if options else None,
        "options": options,
    }


def insights(days: int = 30, db_path: str | None = None) -> dict:
    """Analyze tracked usage and surface anomalies, concentration and savings.

    Pure read-only analysis over the existing query layer. Returns a structured
    result so it can drive both the CLI and any external tooling.
    """
    s = summary(days=days, db_path=db_path)
    daily = cost_by_day(days=days, db_path=db_path)
    models = cost_by_model(days=days, db_path=db_path)
    endpoints = cost_by_endpoint(days=days, db_path=db_path)
    calls = _ok_calls(days=days, db_path=db_path)

    total_cost = float(s["total_cost_usd"])
    return {
        "days": days,
        "total_cost_usd": round(total_cost, 4),
        "total_calls": s["total_calls"],
        "anomalies": _daily_anomalies(daily),
        "concentration": _concentration(models, endpoints, total_cost),
        "suggestions": _suggestions(calls, models),
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


def cost_by_endpoint(days: int = 30, db_path: str | None = None) -> list[dict]:
    """Get cost breakdown by API endpoint."""
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    cur = conn.execute(
        """SELECT
            COALESCE(endpoint, 'unknown') as endpoint,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cost_usd) as total_cost,
            AVG(latency_ms) as avg_latency
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'
        GROUP BY COALESCE(endpoint, 'unknown')
        ORDER BY total_cost DESC, calls DESC""",
        (f"-{days} days",),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def cost_by_tag(days: int = 30, db_path: str | None = None) -> list[dict]:
    """Get cost breakdown by tag, attributing spend to features/flows.

    Calls logged outside any :func:`tokentracker.tag` block roll up under
    ``"(untagged)"`` so the breakdown always accounts for the full spend.
    """
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    cur = conn.execute(
        """SELECT
            COALESCE(tag, '(untagged)') as tag,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cost_usd) as total_cost,
            AVG(latency_ms) as avg_latency
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'
        GROUP BY COALESCE(tag, '(untagged)')
        ORDER BY total_cost DESC, calls DESC""",
        (f"-{days} days",),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


# Modified z-score cutoff and minimum sample size for daily anomaly detection.
_ANOMALY_Z = 3.5
_MIN_ANOMALY_DAYS = 4
# A single model/endpoint above this share of spend is flagged as concentrated.
_CONCENTRATION_THRESHOLD = 0.6
# Routing suggestion fires when this share of a model's calls are small enough
# to move, and the move clears this much money.
_SMALL_CALL_SHARE = 0.5
_MIN_SAVINGS_USD = 0.01
_MISSING_PRICING_MIN_SHARE = 0.05


def _ok_calls(days: int, db_path: str | None) -> list[dict]:
    conn = get_db(db_path)
    conn.row_factory = _dict_factory
    cur = conn.execute(
        """SELECT model, input_tokens, output_tokens, total_tokens, cost_usd
        FROM calls
        WHERE timestamp > unixepoch('now', ?)
          AND status = 'ok'""",
        (f"-{days} days",),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return rows


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _daily_anomalies(daily: list[dict]) -> list[dict]:
    """Flag days whose spend is far above the recent baseline.

    Uses the modified z-score (median / MAD), which holds up when one or two
    spike days would blow out a plain mean and standard deviation. When the MAD
    collapses to zero we fall back to the mean absolute deviation.
    """
    costs = [float(d["cost"] or 0.0) for d in daily]
    if len(costs) < _MIN_ANOMALY_DAYS:
        return []

    median = _median(costs)
    deviations = [abs(c - median) for c in costs]
    mad = _median(deviations)
    if mad > 0:
        scale = 1.4826 * mad
    else:
        scale = 1.253314 * (sum(deviations) / len(deviations))
    if scale == 0:
        return []

    out = []
    for d in daily:
        cost = float(d["cost"] or 0.0)
        z = (cost - median) / scale
        if z >= _ANOMALY_Z:
            out.append(
                {
                    "date": d["date"],
                    "cost_usd": round(cost, 4),
                    "baseline_usd": round(median, 4),
                    "z_score": round(z, 2),
                    "calls": d["calls"],
                }
            )
    out.sort(key=lambda a: a["z_score"], reverse=True)
    return out


def _concentration(models: list[dict], endpoints: list[dict], total_cost: float) -> dict:
    def _top(rows: list[dict], label: str) -> dict | None:
        priced = [r for r in rows if r["total_cost"]]
        if not priced or total_cost <= 0:
            return None
        top = max(priced, key=lambda r: r["total_cost"])
        return {
            label: top[label],
            "cost_usd": round(float(top["total_cost"]), 4),
            "share": round(float(top["total_cost"]) / total_cost, 4),
        }

    top_model = _top(models, "model")
    top_endpoint = _top(endpoints, "endpoint")
    return {
        "top_model": top_model,
        "top_endpoint": top_endpoint,
        "dominated": bool(top_model and top_model["share"] >= _CONCENTRATION_THRESHOLD),
        "threshold": _CONCENTRATION_THRESHOLD,
    }


def _suggestions(calls: list[dict], models: list[dict]) -> list[dict]:
    out = []
    routing = _routing_suggestion(calls, models)
    if routing:
        out.append(routing)
    missing = _missing_pricing_suggestion(calls)
    if missing:
        out.append(missing)
    return out


def _cheapest_alternative(models: list[dict], from_price: float) -> str | None:
    candidates = []
    for m in models:
        price = blended_price(m["model"])
        if price is not None and price < from_price:
            candidates.append((price, m["model"]))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _routing_suggestion(calls: list[dict], models: list[dict]) -> dict | None:
    """Spot an expensive model serving mostly small calls a cheaper one could take."""
    priced = [m for m in models if m["total_cost"]]
    if len(priced) < 2 or not calls:
        return None

    cutoff = _median([c["total_tokens"] for c in calls])
    if cutoff <= 0:
        return None

    best = None
    for m in priced:
        from_model = m["model"]
        from_price = blended_price(from_model)
        if from_price is None:
            continue
        alt = _cheapest_alternative(priced, from_price)
        if alt is None:
            continue
        small = [c for c in calls if c["model"] == from_model and c["total_tokens"] <= cutoff]
        if not small or len(small) / m["calls"] < _SMALL_CALL_SHARE:
            continue

        in_tokens = sum(c["input_tokens"] for c in small)
        out_tokens = sum(c["output_tokens"] for c in small)
        projected = estimate_cost(alt, in_tokens, out_tokens)
        if projected is None:
            continue
        current = sum(c["cost_usd"] or 0.0 for c in small)
        savings = current - projected
        if savings < _MIN_SAVINGS_USD:
            continue
        if best is None or savings > best["_savings"]:
            best = {
                "kind": "cheaper_model",
                "model": from_model,
                "alternative": alt,
                "token_cutoff": int(cutoff),
                "small_calls": len(small),
                "small_call_share": round(len(small) / m["calls"], 4),
                "current_cost_usd": round(current, 4),
                "projected_cost_usd": round(projected, 4),
                "estimated_savings_usd": round(savings, 4),
                "_savings": savings,
            }

    if best is None:
        return None
    best.pop("_savings")
    best["message"] = (
        f"{best['small_calls']} of the {best['model']} calls are small "
        f"(at most {best['token_cutoff']} tokens). Routing those to {best['alternative']} "
        f"would save about ${best['estimated_savings_usd']:.2f}."
    )
    return best


def _missing_pricing_suggestion(calls: list[dict]) -> dict | None:
    if not calls:
        return None
    unpriced = [c for c in calls if c["cost_usd"] is None]
    if not unpriced or len(unpriced) / len(calls) < _MISSING_PRICING_MIN_SHARE:
        return None
    names = sorted({c["model"] for c in unpriced})
    return {
        "kind": "missing_pricing",
        "models": names,
        "calls": len(unpriced),
        "untracked_tokens": sum(c["total_tokens"] for c in unpriced),
        "message": (
            f"{len(unpriced)} calls across {len(names)} model(s) have no pricing data, "
            f"so their cost is invisible. Add them to pricing.py to close the gap."
        ),
    }
