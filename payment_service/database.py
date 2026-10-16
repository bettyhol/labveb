"""SQLite configuration and schema initialization for Payment Service."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/payments.db")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield and reliably close a Payment Service database connection."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the Payment Service schema without replacing existing data."""
    if DATABASE_PATH != ":memory:":
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL UNIQUE CHECK (booking_id > 0),
                user_id INTEGER NOT NULL CHECK (user_id > 0),
                amount REAL NOT NULL CHECK (amount > 0),
                currency TEXT NOT NULL CHECK (length(trim(currency)) > 0),
                method TEXT NOT NULL CHECK (length(trim(method)) > 0),
                status TEXT NOT NULL CHECK (
                    status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')
                ),
                transaction_ref TEXT,
                created_at TEXT NOT NULL,
                refunded_at TEXT
            )
            """
        )
        connection.commit()
