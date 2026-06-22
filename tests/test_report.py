"""Tests for the standalone HTML report renderer (pure, no database)."""

from __future__ import annotations

from tokentracker.report import render_report_html

_SUMMARY = {
    "total_calls": 3,
    "total_input_tokens": 100,
    "total_output_tokens": 50,
    "total_tokens": 150,
    "total_cost_usd": 0.1234,
    "avg_latency_ms": 420.0,
    "models_used": 2,
}
_BY_MODEL = [
    {
        "model": "gpt-4o",
        "calls": 2,
        "input_tokens": 80,
        "output_tokens": 40,
        "total_cost": 0.1,
        "avg_latency": 500,
    },
    {
        "model": "gpt-4o-mini",
        "calls": 1,
        "input_tokens": 20,
        "output_tokens": 10,
        "total_cost": 0.0234,
        "avg_latency": 200,
    },
]
_BY_DAY = [
    {"date": "2026-06-22", "calls": 1, "tokens": 50, "cost": 0.02},
    {"date": "2026-06-23", "calls": 2, "tokens": 100, "cost": 0.1034},
]
_BY_ENDPOINT = [
    {
        "endpoint": "chat.completions",
        "calls": 3,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_cost": 0.1234,
        "avg_latency": 420,
    },
]


def _render(**overrides):
    kwargs = dict(
        days=30,
        summary=_SUMMARY,
        by_model=_BY_MODEL,
        by_day=_BY_DAY,
        by_endpoint=_BY_ENDPOINT,
    )
    kwargs.update(overrides)
    return render_report_html(**kwargs)


def test_report_is_self_contained_html():
    out = _render()
    assert out.startswith("<!DOCTYPE html>")
    assert out.rstrip().endswith("</html>")
    # No external assets: no remote scripts, stylesheets, or images.
    assert "<script" not in out
    assert "http://" not in out and "https://" not in out
    assert "src=" not in out and 'rel="stylesheet"' not in out


def test_report_shows_totals_and_models():
    out = _render()
    assert "$0.1234" in out  # total cost
    assert "gpt-4o" in out and "gpt-4o-mini" in out
    assert "chat.completions" in out


def test_report_escapes_model_names():
    # A model name with HTML metacharacters must not break out of the markup.
    out = _render(
        by_model=[
            {
                "model": "<script>x</script>",
                "calls": 1,
                "input_tokens": 1,
                "output_tokens": 1,
                "total_cost": 0.01,
                "avg_latency": 1,
            }
        ]
    )
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out


def test_bar_widths_are_bounded_and_relative():
    out = _render()
    # The largest model cost should produce a full-width bar; widths stay <=100%.
    assert "width:100.0%" in out
    assert "width:120" not in out  # never overflow


def test_empty_data_renders_a_friendly_page():
    out = _render(
        summary={"total_calls": 0, "total_cost_usd": 0},
        by_model=[],
        by_day=[],
        by_endpoint=[],
    )
    assert "No API calls tracked yet" in out
    assert out.startswith("<!DOCTYPE html>")
    assert out.rstrip().endswith("</html>")


def test_generated_at_is_included_and_escaped():
    out = _render(generated_at="2026-06-23 12:00")
    assert "2026-06-23 12:00" in out
