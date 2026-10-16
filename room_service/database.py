"""SQLite configuration and schema initialization for Room Service."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/rooms.db")
SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MILLISECONDS = 5000


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield and reliably close a connection to the Room Service database."""
    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=SQLITE_TIMEOUT_SECONDS,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MILLISECONDS}"
    )
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Create Room Service tables without replacing existing data."""
    if DATABASE_PATH != ":memory:":
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                number TEXT NOT NULL,
                room_type TEXT NOT NULL CHECK (
                    room_type IN ('STANDARD', 'DELUXE', 'SUITE')
                ),
                capacity INTEGER NOT NULL CHECK (capacity > 0),
                price_per_night REAL NOT NULL CHECK (price_per_night > 0),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                UNIQUE (hotel_id, number)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS room_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                booking_id INTEGER NOT NULL UNIQUE,
                check_in TEXT NOT NULL,
                check_out TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('HELD', 'CONFIRMED', 'RELEASED')
                ),
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (check_in < check_out),
                FOREIGN KEY (room_id) REFERENCES rooms (id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rooms_hotel_active_capacity
            ON rooms (hotel_id, active, capacity)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_allocations_room_status_dates
            ON room_allocations (room_id, status, check_in, check_out)
            """
        )
        connection.commit()
