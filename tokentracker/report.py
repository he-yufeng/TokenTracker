"""Render a tracked-usage summary as a self-contained HTML report.

The ``dashboard`` command prints to the terminal; this builds the same picture as
a single static HTML file you can open in a browser, attach to an email, or drop
in a CI artifact. :func:`render_report_html` is a pure function over the query
dicts (the same shapes :mod:`tokentracker.query` already returns), so it needs no
database and is unit-testable with plain dicts. The output embeds its own CSS and
uses plain ``<div>`` bars for the charts — no external assets, no JavaScript, no
network — so the file works fully offline.
"""

from __future__ import annotations

import html


def _bar(value: float, peak: float, color: str) -> str:
    """A single horizontal bar whose width is ``value`` relative to ``peak``."""
    pct = 0.0 if peak <= 0 else max(0.0, min(100.0, value / peak * 100.0))
    return (
        f'<div class="bar-track">'
        f'<div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div>'
        f"</div>"
    )


def _money(value: float | None) -> str:
    return f"${value:.4f}" if value else "—"


def render_report_html(
    *,
    days: int,
    summary: dict,
    by_model: list[dict],
    by_day: list[dict],
    by_endpoint: list[dict],
    generated_at: str = "",
) -> str:
    """Build a standalone HTML report from already-queried usage data.

    Args mirror :mod:`tokentracker.query`: ``summary`` is :func:`query.summary`,
    ``by_model`` / ``by_endpoint`` are the ``cost_by_*`` lists, and ``by_day`` is
    :func:`query.cost_by_day`. ``generated_at`` is an optional pre-formatted
    timestamp (passed in so the function stays pure and deterministic).
    """
    esc = html.escape
    total_cost = summary.get("total_cost_usd", 0) or 0
    empty = (summary.get("total_calls", 0) or 0) == 0

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>TokenTracker report — last {days} days</title>")
    parts.append(_STYLE)
    parts.append("</head><body><main>")
    parts.append("<h1>TokenTracker</h1>")
    sub = f"Last {days} days"
    if generated_at:
        sub += f" · generated {esc(generated_at)}"
    parts.append(f'<p class="sub">{sub}</p>')

    if empty:
        parts.append('<p class="empty">No API calls tracked yet.</p>')
        parts.append("</main></body></html>")
        return "".join(parts)

    # Summary cards.
    cards = [
        ("Total cost", _money(total_cost)),
        ("API calls", f"{summary.get('total_calls', 0):,}"),
        (
            "Tokens",
            f"{summary.get('total_tokens', 0):,} "
            f"({summary.get('total_input_tokens', 0):,} in / "
            f"{summary.get('total_output_tokens', 0):,} out)",
        ),
        ("Avg latency", f"{summary.get('avg_latency_ms', 0):.0f}ms"),
        ("Models used", str(summary.get("models_used", 0))),
    ]
    parts.append('<section class="cards">')
    for label, value in cards:
        parts.append(
            f'<div class="card"><div class="k">{label}</div><div class="v">{value}</div></div>'
        )
    parts.append("</section>")

    # Cost by model (table + bars).
    if by_model:
        peak = max((m.get("total_cost") or 0) for m in by_model)
        parts.append("<h2>Cost by model</h2>")
        parts.append(
            '<table><thead><tr><th>Model</th><th class="r">Calls</th>'
            '<th class="r">Tokens</th><th class="r">Cost</th><th>Share</th></tr></thead><tbody>'
        )
        for m in by_model:
            tokens = (m.get("input_tokens") or 0) + (m.get("output_tokens") or 0)
            cost = m.get("total_cost") or 0
            parts.append(
                f"<tr><td>{esc(str(m.get('model', '')))}</td>"
                f'<td class="r">{m.get("calls", 0):,}</td>'
                f'<td class="r">{tokens:,}</td>'
                f'<td class="r">{_money(cost)}</td>'
                f"<td>{_bar(cost, peak, '#2563eb')}</td></tr>"
            )
        parts.append("</tbody></table>")

    # Daily spend (bars, oldest to newest).
    if by_day:
        peak = max((d.get("cost") or 0) for d in by_day)
        parts.append("<h2>Daily spend</h2>")
        parts.append("<table><tbody>")
        for d in sorted(by_day, key=lambda r: r.get("date", "")):
            cost = d.get("cost") or 0
            parts.append(
                f'<tr><td class="date">{esc(str(d.get("date", "")))}</td>'
                f'<td class="r money">{_money(cost)}</td>'
                f"<td>{_bar(cost, peak, '#16a34a')}</td></tr>"
            )
        parts.append("</tbody></table>")

    # Cost by endpoint.
    if by_endpoint:
        peak = max((e.get("total_cost") or 0) for e in by_endpoint)
        parts.append("<h2>Cost by endpoint</h2>")
        parts.append(
            '<table><thead><tr><th>Endpoint</th><th class="r">Calls</th>'
            '<th class="r">Cost</th><th>Share</th></tr></thead><tbody>'
        )
        for e in by_endpoint:
            cost = e.get("total_cost") or 0
            parts.append(
                f"<tr><td>{esc(str(e.get('endpoint', '')))}</td>"
                f'<td class="r">{e.get("calls", 0):,}</td>'
                f'<td class="r">{_money(cost)}</td>'
                f"<td>{_bar(cost, peak, '#7c3aed')}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append(
        '<p class="foot">Generated by TokenTracker — costs are computed from your own '
        "pricing table, offline.</p>"
    )
    parts.append("</main></body></html>")
    return "".join(parts)


_STYLE = """<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:#f8fafc;color:#0f172a;
 font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:32px 20px}
h1{margin:0;font-size:28px}
h2{margin:32px 0 8px;font-size:18px}
.sub{color:#64748b;margin:4px 0 24px}
.empty{color:#64748b;padding:40px 0}
.cards{display:flex;flex-wrap:wrap;gap:12px}
.card{flex:1 1 150px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px}
.card .k{color:#64748b;font-size:12px}
.card .v{font-size:18px;font-weight:600;margin-top:2px}
table{width:100%;border-collapse:collapse;background:#fff;
 border:1px solid #e2e8f0;border-radius:12px;overflow:hidden}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #f1f5f9;font-size:14px}
th{background:#f8fafc;color:#475569;font-weight:600}
tr:last-child td{border-bottom:none}
.r{text-align:right;white-space:nowrap}
.date{font-variant-numeric:tabular-nums;color:#475569}
.money{font-variant-numeric:tabular-nums}
.bar-track{background:#f1f5f9;border-radius:6px;height:10px;min-width:80px}
.bar-fill{height:10px;border-radius:6px}
.foot{color:#94a3b8;font-size:12px;margin-top:28px}
@media(prefers-color-scheme:dark){
 body{background:#0f172a;color:#e2e8f0}
 .card,table{background:#1e293b;border-color:#334155}
 th{background:#1e293b;color:#94a3b8}
 th,td{border-color:#334155}
 .bar-track{background:#334155}
}
</style>"""
