import json
import time

import pytest
from click.testing import CliRunner

import tokentracker.db as db
from tokentracker import budgets as budgets_mod
from tokentracker.cli import main
from tokentracker.db import log_call


def _seed(db_path, cost, *, model=None, endpoint=None, tag=None, age_days=0.0):
    """Insert one call at ``cost`` USD, optionally aged into the past."""
    log_call(
        model or "gpt-4o",
        10,
        5,
        15,
        cost,
        100.0,
        endpoint=endpoint,
        tag=tag,
        db_path=db_path,
    )
    if age_days:
        conn = db.get_db(db_path)
        conn.execute(
            "UPDATE calls SET timestamp = ? WHERE cost_usd = ? AND timestamp = ("
            "  SELECT MAX(timestamp) FROM calls)",
            (time.time() - age_days * 86400, cost),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_set_and_list(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("monthly", 100.0, days=30, db_path=p)
    rows = budgets_mod.list_budgets(db_path=p)
    assert [b.name for b in rows] == ["monthly"]
    assert rows[0].limit_usd == 100.0 and rows[0].days == 30


def test_set_upserts_by_name(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("cap", 50.0, db_path=p)
    budgets_mod.set_budget("cap", 75.0, days=7, model="gpt-4o", db_path=p)
    rows = budgets_mod.list_budgets(db_path=p)
    assert len(rows) == 1
    assert rows[0].limit_usd == 75.0 and rows[0].days == 7 and rows[0].model == "gpt-4o"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "limit_usd": 10.0},
        {"name": "  ", "limit_usd": 10.0},
        {"name": "x", "limit_usd": 0.0},
        {"name": "x", "limit_usd": -5.0},
        {"name": "x", "limit_usd": 10.0, "warn_at": 0.0},
        {"name": "x", "limit_usd": 10.0, "warn_at": 1.5},
        {"name": "x", "limit_usd": 10.0, "days": 0},
    ],
)
def test_set_rejects_invalid(tmp_path, kwargs):
    p = str(tmp_path / "u.db")
    with pytest.raises(ValueError):
        budgets_mod.set_budget(db_path=p, **kwargs)


def test_remove(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("gone", 10.0, db_path=p)
    assert budgets_mod.remove_budget("gone", db_path=p) is True
    assert budgets_mod.remove_budget("gone", db_path=p) is False
    assert budgets_mod.list_budgets(db_path=p) == []


# --------------------------------------------------------------------------- #
# check status + scope + breach projection
# --------------------------------------------------------------------------- #
def test_check_status_thresholds(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("cap", 10.0, warn_at=0.8, db_path=p)

    assert (
        budgets_mod.check_budget(budgets_mod.list_budgets(db_path=p)[0], db_path=p)["status"]
        == "ok"
    )
    _seed(p, 8.5)  # 85% -> warn
    assert budgets_mod.check_all(db_path=p)[0]["status"] == "warn"
    _seed(p, 5.0)  # 13.5 total -> exceeded
    assert budgets_mod.check_all(db_path=p)[0]["status"] == "exceeded"


def test_check_scope_filters_by_model(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("gpt4", 10.0, model="gpt-4o", db_path=p)
    _seed(p, 9.0, model="cheap-model")  # out of scope
    _seed(p, 3.0, model="gpt-4o")  # in scope
    r = budgets_mod.check_all(db_path=p)[0]
    assert r["spent_usd"] == 3.0 and r["status"] == "ok"


def test_breach_projection(tmp_path):
    p = str(tmp_path / "u.db")
    # $2/day across the 7-day rate window ($14), limit $20 -> $6 left at $2/day
    # -> 3 more days to breach.
    budgets_mod.set_budget("cap", 20.0, days=30, db_path=p)
    for age in range(7):
        _seed(p, 2.0, age_days=age)
    r = budgets_mod.check_all(db_path=p)[0]
    assert r["spent_usd"] == 14.0
    assert r["breach_in_days"] == 3


def test_breach_none_without_recent_spend(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("cap", 20.0, days=30, db_path=p)
    r = budgets_mod.check_all(db_path=p)[0]
    assert r["breach_in_days"] is None  # nothing spent -> not on track


def test_breach_zero_when_over(tmp_path):
    p = str(tmp_path / "u.db")
    budgets_mod.set_budget("cap", 5.0, db_path=p)
    _seed(p, 9.0)
    r = budgets_mod.check_all(db_path=p)[0]
    assert r["status"] == "exceeded" and r["breach_in_days"] == 0


def test_check_all_empty(tmp_path):
    assert budgets_mod.check_all(db_path=str(tmp_path / "u.db")) == []


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_set_list_rm(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", str(tmp_path / "u.db"))
    r = CliRunner().invoke(main, ["budgets", "set", "monthly", "--limit", "100"])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(main, ["budgets", "list", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output)[0]["name"] == "monthly"
    r = CliRunner().invoke(main, ["budgets", "rm", "monthly"])
    assert r.exit_code == 0
    assert CliRunner().invoke(main, ["budgets", "rm", "monthly"]).exit_code != 0  # gone


def test_cli_check_exit_code_on_exceeded(tmp_path, monkeypatch):
    p = str(tmp_path / "u.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", p)
    budgets_mod.set_budget("cap", 5.0, db_path=p)
    _seed(p, 9.0)
    r = CliRunner().invoke(main, ["budgets", "check", "--json"])
    assert r.exit_code == 1  # exceeded -> non-zero for CI gating
    assert json.loads(r.output)[0]["status"] == "exceeded"


def test_cli_check_ok_exit_zero(tmp_path, monkeypatch):
    p = str(tmp_path / "u.db")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", p)
    budgets_mod.set_budget("cap", 100.0, db_path=p)
    _seed(p, 1.0)
    r = CliRunner().invoke(main, ["budgets", "check"])
    assert r.exit_code == 0, r.output
