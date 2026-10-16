"""SQLite configuration and schema initialization for Notification Service."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/notifications.db")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield and reliably close a Notification Service DB connection."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the Notification schema without replacing existing data."""
    if DATABASE_PATH != ":memory:":
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL CHECK (user_id > 0),
                booking_id INTEGER CHECK (booking_id IS NULL OR booking_id > 0),
                type TEXT NOT NULL CHECK (
                    type IN (
                        'BOOKING_CONFIRMED',
                        'BOOKING_CANCELLED',
                        'PAYMENT_FAILED'
                    )
                ),
                channel TEXT NOT NULL CHECK (channel = 'EMAIL'),
                recipient TEXT NOT NULL CHECK (length(trim(recipient)) > 0),
                subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
                message TEXT NOT NULL CHECK (length(trim(message)) > 0),
                status TEXT NOT NULL CHECK (status = 'SENT'),
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_user_created
            ON notifications (user_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_booking
            ON notifications (booking_id)
            """
        )
        connection.commit()
