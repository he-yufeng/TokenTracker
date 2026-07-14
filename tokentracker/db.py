"""SQLite storage for API call logs. Zero config, works out of the box."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import local

_thread_local = local()

# Tag applied to calls logged within a ``tag(...)`` block, so spend can be
# attributed to a feature/flow without threading a label through every call.
_current_tag: ContextVar[str | None] = ContextVar("tokentracker_tag", default=None)


@contextmanager
def tag(name: str) -> Iterator[None]:
    """Attribute every API call logged inside this block to ``name``.

    >>> with tag("checkout-flow"):
    ...     client.chat.completions.create(...)  # logged with tag="checkout-flow"

    Tags nest; the innermost active tag wins. Calls outside any block are
    logged with no tag (and roll up under "(untagged)" in reports).
    """
    token = _current_tag.set(name)
    try:
        yield
    finally:
        _current_tag.reset(token)


def current_tag() -> str | None:
    """Return the tag for the active ``tag(...)`` block, or None."""
    return _current_tag.get()


DEFAULT_DB_PATH = os.environ.get(
    "TOKENTRACKER_DB",
    str(Path.home() / ".tokentracker" / "usage.db"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    latency_ms REAL,
    endpoint TEXT,
    status TEXT DEFAULT 'ok',
    error TEXT,
    metadata TEXT,
    tag TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_calls_model ON calls(model);

CREATE TABLE IF NOT EXISTS budgets (
    name TEXT PRIMARY KEY,
    limit_usd REAL NOT NULL,
    days INTEGER NOT NULL DEFAULT 30,
    warn_at REAL NOT NULL DEFAULT 0.8,
    model TEXT,
    endpoint TEXT,
    tag TEXT,
    created_at REAL NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created.

    ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so databases
    created before the ``tag`` column need it added explicitly. The tag index is
    created here (not in ``_SCHEMA``) so it is only built once the column exists,
    on both legacy and fresh databases. Guarded to be a no-op on re-runs.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(calls)")}
    if "tag" not in columns:
        conn.execute("ALTER TABLE calls ADD COLUMN tag TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_tag ON calls(tag)")
    conn.commit()


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Get a thread-local database connection."""
    path = db_path or DEFAULT_DB_PATH
    key = f"conn_{path}"

    conn = getattr(_thread_local, key, None)
    if conn is None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript(_SCHEMA)
        _migrate(conn)
        setattr(_thread_local, key, conn)
    return conn


def log_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost_usd: float | None,
    latency_ms: float,
    endpoint: str = "chat.completions",
    status: str = "ok",
    error: str | None = None,
    metadata: str | None = None,
    tag: str | None = None,
    db_path: str | None = None,
) -> None:
    """Log a single API call to the database.

    When ``tag`` is not given, the call inherits the active :func:`tag` block
    (if any), so spend can be attributed to a feature without passing a label
    through every call site.
    """
    conn = get_db(db_path)
    if tag is None:
        tag = _current_tag.get()
    conn.execute(
        """INSERT INTO calls
           (timestamp, model, input_tokens, output_tokens, total_tokens,
            cost_usd, latency_ms, endpoint, status, error, metadata, tag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(),
            model,
            input_tokens,
            output_tokens,
            total_tokens,
            cost_usd,
            latency_ms,
            endpoint,
            status,
            error,
            metadata,
            tag,
        ),
    )
    conn.commit()
