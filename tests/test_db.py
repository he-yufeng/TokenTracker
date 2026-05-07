"""Tests for database logging."""

from tokentracker.db import get_db, log_call


def test_log_and_query(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_call(
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        latency_ms=500.0,
        db_path=db_path,
    )

    conn = get_db(db_path)
    cur = conn.execute("SELECT COUNT(*) FROM calls")
    assert cur.fetchone()[0] == 1

    cur = conn.execute("SELECT model, input_tokens FROM calls")
    row = cur.fetchone()
    assert row[0] == "gpt-4o"
    assert row[1] == 100


def test_log_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_call(
        model="gpt-4o",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost_usd=None,
        latency_ms=100.0,
        status="error",
        error="rate limit",
        db_path=db_path,
    )
    conn = get_db(db_path)
    cur = conn.execute("SELECT status, error FROM calls")
    row = cur.fetchone()
    assert row[0] == "error"
    assert row[1] == "rate limit"
