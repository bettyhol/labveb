"""SQLite configuration and schema initialization for Hotel Service."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/hotels.db")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield and reliably close a connection to the Hotel Service database."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the Hotel Service schema without replacing existing data."""
    if DATABASE_PATH != ":memory:":
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS hotels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                address TEXT NOT NULL,
                description TEXT,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hotels_city_rating
            ON hotels (city COLLATE NOCASE, rating)
            """
        )
        connection.commit()
