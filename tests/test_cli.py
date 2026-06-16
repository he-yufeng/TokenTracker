import json
import time

from click.testing import CliRunner

import tokentracker.db as db
from tokentracker.cli import main
from tokentracker.db import get_db, log_call


def test_export_respects_days_window(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)

    conn = get_db(db_path)
    now = time.time()
    conn.execute(
        """INSERT INTO calls
           (timestamp, model, input_tokens, output_tokens, total_tokens,
            cost_usd, latency_ms, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (now - 3 * 86400, "old-model", 1, 1, 2, 0.01, 100.0, "ok"),
    )
    conn.commit()
    log_call("new-model", 10, 5, 15, 0.02, 120.0, db_path=db_path)

    result = CliRunner().invoke(main, ["export", "--format", "json", "--days", "1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["model"] for row in payload] == ["new-model"]


def test_budget_json_ok(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call("gpt-4o", 100, 50, 150, 0.25, 500.0, db_path=db_path)

    result = CliRunner().invoke(main, ["budget", "--limit", "1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["spent_usd"] == 0.25
    assert payload["remaining_usd"] == 0.75


def test_budget_exits_nonzero_when_exceeded(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call("gpt-4o", 100, 50, 150, 1.25, 500.0, db_path=db_path)

    result = CliRunner().invoke(main, ["budget", "--limit", "1", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["status"] == "exceeded"


def test_endpoints_groups_cost_by_endpoint(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call(
        "gpt-4o",
        100,
        50,
        150,
        0.25,
        500.0,
        endpoint="chat.completions",
        db_path=db_path,
    )
    log_call(
        "text-embedding-3-small",
        200,
        0,
        200,
        0.02,
        80.0,
        endpoint="embeddings",
        db_path=db_path,
    )

    result = CliRunner().invoke(main, ["endpoints", "--days", "1"])

    assert result.exit_code == 0, result.output
    assert "chat.completions" in result.output
    assert "embeddings" in result.output


def test_budget_can_target_model_and_endpoint(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call(
        "gpt-4o",
        100,
        50,
        150,
        0.75,
        500.0,
        endpoint="chat.completions",
        db_path=db_path,
    )
    log_call(
        "text-embedding-3-small",
        200,
        0,
        200,
        0.05,
        80.0,
        endpoint="embeddings",
        db_path=db_path,
    )

    result = CliRunner().invoke(
        main,
        [
            "budget",
            "--limit",
            "0.1",
            "--model",
            "text-embedding-3-small",
            "--endpoint",
            "embeddings",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["spent_usd"] == 0.05
    assert payload["total_calls"] == 1
    assert payload["scope"] == {
        "model": "text-embedding-3-small",
        "endpoint": "embeddings",
    }


def test_forecast_projects_scoped_run_rate(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call(
        "gpt-4o",
        100,
        50,
        150,
        0.70,
        500.0,
        endpoint="chat.completions",
        db_path=db_path,
    )
    log_call(
        "text-embedding-3-small",
        200,
        0,
        200,
        0.05,
        80.0,
        endpoint="embeddings",
        db_path=db_path,
    )

    result = CliRunner().invoke(
        main,
        [
            "forecast",
            "--days",
            "7",
            "--forecast-days",
            "28",
            "--model",
            "gpt-4o",
            "--endpoint",
            "chat.completions",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["observed_cost_usd"] == 0.7
    assert payload["projected_cost_usd"] == 2.8
    assert payload["projected_calls"] == 4
    assert payload["scope"]["model"] == "gpt-4o"


def test_forecast_rejects_invalid_window():
    result = CliRunner().invoke(main, ["forecast", "--days", "0"])

    assert result.exit_code != 0
    assert "--days must be greater than zero" in result.output


def _insert(conn, *, model, input_tokens, output_tokens, cost_usd, ts, endpoint="chat.completions"):
    conn.execute(
        """INSERT INTO calls
           (timestamp, model, input_tokens, output_tokens, total_tokens,
            cost_usd, latency_ms, endpoint, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok')""",
        (ts, model, input_tokens, output_tokens, input_tokens + output_tokens,
         cost_usd, 100.0, endpoint),
    )
    conn.commit()


def test_insights_flags_a_spend_spike(tmp_path):
    from tokentracker.query import insights

    db_path = str(tmp_path / "usage.db")
    conn = get_db(db_path)
    now = time.time()
    baseline = {1: 0.50, 2: 0.55, 3: 0.50, 4: 0.60, 5: 0.52}
    for day, cost in baseline.items():
        _insert(conn, model="gpt-4o", input_tokens=100, output_tokens=50,
                cost_usd=cost, ts=now - day * 86400)
    _insert(conn, model="gpt-4o", input_tokens=100, output_tokens=50,
            cost_usd=5.0, ts=now)

    data = insights(days=30, db_path=db_path)
    anomalies = data["anomalies"]

    assert len(anomalies) == 1
    assert anomalies[0]["cost_usd"] == 5.0
    assert anomalies[0]["z_score"] >= 3.5


def test_insights_no_anomaly_on_flat_spend(tmp_path):
    from tokentracker.query import insights

    db_path = str(tmp_path / "usage.db")
    conn = get_db(db_path)
    now = time.time()
    for day in range(1, 6):
        _insert(conn, model="gpt-4o", input_tokens=100, output_tokens=50,
                cost_usd=0.50, ts=now - day * 86400)

    assert insights(days=30, db_path=db_path)["anomalies"] == []


def test_insights_reports_cost_concentration(tmp_path):
    from tokentracker.query import insights

    db_path = str(tmp_path / "usage.db")
    conn = get_db(db_path)
    now = time.time()
    _insert(conn, model="gpt-4o", input_tokens=1000, output_tokens=1000,
            cost_usd=0.90, ts=now)
    _insert(conn, model="gpt-4o-mini", input_tokens=1000, output_tokens=1000,
            cost_usd=0.10, ts=now)

    conc = insights(days=30, db_path=db_path)["concentration"]

    assert conc["dominated"] is True
    assert conc["top_model"]["model"] == "gpt-4o"
    assert conc["top_model"]["share"] == 0.9


def test_insights_suggests_cheaper_model(tmp_path):
    from tokentracker.pricing import estimate_cost
    from tokentracker.query import insights

    db_path = str(tmp_path / "usage.db")
    conn = get_db(db_path)
    now = time.time()
    # gpt-4o doing eight small calls plus three genuinely large ones.
    for _ in range(8):
        _insert(conn, model="gpt-4o", input_tokens=500, output_tokens=500,
                cost_usd=estimate_cost("gpt-4o", 500, 500), ts=now)
    for _ in range(3):
        _insert(conn, model="gpt-4o", input_tokens=10000, output_tokens=10000,
                cost_usd=estimate_cost("gpt-4o", 10000, 10000), ts=now)
    for _ in range(5):
        _insert(conn, model="gpt-4o-mini", input_tokens=250, output_tokens=250,
                cost_usd=estimate_cost("gpt-4o-mini", 250, 250), ts=now)

    suggestions = insights(days=30, db_path=db_path)["suggestions"]
    routing = next(s for s in suggestions if s["kind"] == "cheaper_model")

    assert routing["model"] == "gpt-4o"
    assert routing["alternative"] == "gpt-4o-mini"
    assert routing["small_calls"] == 8
    assert routing["estimated_savings_usd"] > 0


def test_insights_flags_untracked_pricing(tmp_path):
    from tokentracker.query import insights

    db_path = str(tmp_path / "usage.db")
    conn = get_db(db_path)
    now = time.time()
    _insert(conn, model="gpt-4o", input_tokens=100, output_tokens=50,
            cost_usd=0.25, ts=now)
    for _ in range(3):
        _insert(conn, model="mystery-model", input_tokens=100, output_tokens=50,
                cost_usd=None, ts=now)

    suggestions = insights(days=30, db_path=db_path)["suggestions"]
    missing = next(s for s in suggestions if s["kind"] == "missing_pricing")

    assert "mystery-model" in missing["models"]
    assert missing["calls"] == 3


def test_insights_cli_json(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    log_call("gpt-4o", 100, 50, 150, 0.25, 500.0, db_path=db_path)

    result = CliRunner().invoke(main, ["insights", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_calls"] == 1
    assert set(payload) >= {"anomalies", "concentration", "suggestions"}


def test_insights_cli_empty_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "usage.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)

    result = CliRunner().invoke(main, ["insights"])

    assert result.exit_code == 0, result.output
    assert "No API calls tracked yet." in result.output
