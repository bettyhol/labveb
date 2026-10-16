"""Persistence operations and simulated delivery for Notification Service."""

import logging
from datetime import datetime, timezone
from sqlite3 import Row

from .database import get_connection


logger = logging.getLogger("uvicorn.error")


def _to_dict(row: Row) -> dict[str, object]:
    result = dict(row)
    result["is_read"] = bool(result["is_read"])
    return result


def create_notification(
    *,
    user_id: int,
    booking_id: int | None,
    notification_type: str,
    channel: str,
    recipient: str,
    subject: str,
    message: str,
) -> dict[str, object]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO notifications (
                user_id, booking_id, type, channel, recipient, subject,
                message, status, is_read, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SENT', FALSE, ?)
            """,
            (
                user_id,
                booking_id,
                notification_type,
                channel,
                recipient,
                subject,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        notification = connection.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_dict(notification)


def simulate_email_delivery(notification: dict[str, object]) -> None:
    """Log an educational EMAIL delivery without contacting a provider."""
    logger.info(
        "[EMAIL]\nTo: %s\nSubject: %s\n%s",
        notification["recipient"],
        notification["subject"],
        notification["message"],
    )


def list_notifications() -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM notifications ORDER BY id"
        ).fetchall()
    return [_to_dict(row) for row in rows]


def get_notification(notification_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    return _to_dict(row) if row is not None else None


def list_user_notifications(user_id: int) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [_to_dict(row) for row in rows]


def mark_notification_read(notification_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = ?",
            (notification_id,),
        )
        if cursor.rowcount == 0:
            return None
        connection.commit()
        notification = connection.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    return _to_dict(notification)
