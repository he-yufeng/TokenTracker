"""Tests for database logging."""

import sqlite3

from tokentracker.db import get_db, log_call, tag
from tokentracker.query import cost_by_tag


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


def test_tag_context_manager_labels_calls(tmp_path):
    db_path = str(tmp_path / "test.db")
    with tag("checkout-flow"):
        log_call("gpt-4o", 100, 50, 150, 0.001, 500.0, db_path=db_path)
    log_call("gpt-4o", 10, 5, 15, 0.0001, 100.0, db_path=db_path)  # outside block

    conn = get_db(db_path)
    rows = dict(conn.execute("SELECT COALESCE(tag, '(none)'), COUNT(*) FROM calls GROUP BY tag"))
    assert rows["checkout-flow"] == 1
    assert rows["(none)"] == 1


def test_explicit_tag_overrides_context(tmp_path):
    db_path = str(tmp_path / "test.db")
    with tag("outer"):
        log_call("gpt-4o", 1, 1, 2, 0.0, 1.0, tag="explicit", db_path=db_path)

    conn = get_db(db_path)
    assert conn.execute("SELECT tag FROM calls").fetchone()[0] == "explicit"


def test_migration_adds_tag_column_to_legacy_db(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    # Simulate a database created before the tag column existed.
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """CREATE TABLE calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL, model TEXT NOT NULL,
            input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
            cost_usd REAL, latency_ms REAL, endpoint TEXT,
            status TEXT, error TEXT, metadata TEXT
        );"""
    )
    legacy.execute(
        "INSERT INTO calls (timestamp, model) VALUES (strftime('%s','now'), 'old-model')"
    )
    legacy.commit()
    legacy.close()

    # get_db migrates the legacy schema; logging a tagged call must now work.
    columns = {row[1] for row in get_db(db_path).execute("PRAGMA table_info(calls)")}
    assert "tag" in columns
    log_call("gpt-4o", 1, 1, 2, 0.0, 1.0, tag="new", db_path=db_path)
    tagged = get_db(db_path).execute("SELECT tag FROM calls WHERE tag IS NOT NULL").fetchone()
    assert tagged[0] == "new"


def test_cost_by_tag_rolls_up_untagged(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_call("gpt-4o", 100, 50, 150, 0.30, 500.0, tag="search", db_path=db_path)
    log_call("gpt-4o", 80, 20, 100, 0.20, 400.0, tag="search", db_path=db_path)
    log_call("gpt-4o", 10, 5, 15, 0.05, 100.0, db_path=db_path)  # untagged

    rows = {r["tag"]: r for r in cost_by_tag(days=1, db_path=db_path)}
    assert rows["search"]["calls"] == 2
    assert abs(rows["search"]["total_cost"] - 0.50) < 1e-9
    assert rows["(untagged)"]["calls"] == 1
