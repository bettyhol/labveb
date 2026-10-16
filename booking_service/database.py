"""SQLite configuration and schema initialization for Booking Service."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/bookings.db")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield and reliably close a Booking Service database connection."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the Booking-owned schema without replacing existing data."""
    if DATABASE_PATH != ":memory:":
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL CHECK (user_id > 0),
                hotel_id INTEGER NOT NULL CHECK (hotel_id > 0),
                hotel_name TEXT NOT NULL CHECK (length(trim(hotel_name)) > 0),
                room_id INTEGER NOT NULL CHECK (room_id > 0),
                room_number TEXT NOT NULL CHECK (length(trim(room_number)) > 0),
                room_type TEXT NOT NULL CHECK (length(trim(room_type)) > 0),
                check_in TEXT NOT NULL,
                check_out TEXT NOT NULL,
                nights INTEGER NOT NULL CHECK (nights > 0),
                price_per_night REAL NOT NULL CHECK (price_per_night > 0),
                total_amount REAL NOT NULL CHECK (total_amount > 0),
                status TEXT NOT NULL CHECK (
                    status IN (
                        'PENDING',
                        'CONFIRMED',
                        'PAYMENT_FAILED',
                        'CANCELLED'
                    )
                ),
                payment_id INTEGER CHECK (payment_id IS NULL OR payment_id > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (check_in < check_out)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_user_created
            ON bookings (user_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_room_dates
            ON bookings (room_id, check_in, check_out)
            """
        )
        connection.commit()
