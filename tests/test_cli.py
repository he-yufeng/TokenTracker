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
