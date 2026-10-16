"""Booking persistence and local state transitions."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlite3 import Row

from .database import get_connection


class BookingStateError(Exception):
    """Raised when a local Booking state transition cannot be completed."""


def _to_dict(row: Row) -> dict[str, object]:
    return dict(row)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pending_booking(
    *,
    user_id: int,
    hotel_id: int,
    hotel_name: str,
    room_id: int,
    room_number: str,
    room_type: str,
    check_in: date,
    check_out: date,
    nights: int,
    price_per_night: Decimal,
    total_amount: Decimal,
) -> dict[str, object]:
    """Persist a complete historical snapshot in a short transaction."""
    timestamp = _utc_now_iso()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bookings (
                user_id, hotel_id, hotel_name, room_id, room_number,
                room_type, check_in, check_out, nights, price_per_night,
                total_amount, status, payment_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?)
            """,
            (
                user_id,
                hotel_id,
                hotel_name,
                room_id,
                room_number,
                room_type,
                check_in.isoformat(),
                check_out.isoformat(),
                nights,
                float(price_per_night),
                float(total_amount),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_dict(booking)


def confirm_booking(booking_id: int, payment_id: int) -> dict[str, object]:
    """Atomically store payment identity and transition PENDING to CONFIRMED."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bookings
            SET status = 'CONFIRMED', payment_id = ?, updated_at = ?
            WHERE id = ? AND status = 'PENDING'
            """,
            (payment_id, _utc_now_iso(), booking_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise BookingStateError("Booking could not be confirmed")
        connection.commit()
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    return _to_dict(booking)


def delete_pending_booking(booking_id: int) -> bool:
    """Remove a temporary Booking after a definitive pre-payment failure."""
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM bookings WHERE id = ? AND status = 'PENDING'",
            (booking_id,),
        )
        connection.commit()
    return cursor.rowcount == 1


def mark_payment_failed(
    booking_id: int,
    payment_id: int | None,
) -> dict[str, object]:
    """Atomically finish a compensated creation flow as PAYMENT_FAILED."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bookings
            SET status = 'PAYMENT_FAILED', payment_id = ?, updated_at = ?
            WHERE id = ? AND status = 'PENDING'
            """,
            (payment_id, _utc_now_iso(), booking_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise BookingStateError("Booking could not be marked PAYMENT_FAILED")
        connection.commit()
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    return _to_dict(booking)


def cancel_booking(booking_id: int) -> dict[str, object]:
    """Atomically transition a fully compensated Booking to CANCELLED."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bookings
            SET status = 'CANCELLED', updated_at = ?
            WHERE id = ? AND status = 'CONFIRMED'
            """,
            (_utc_now_iso(), booking_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise BookingStateError("Booking could not be cancelled")
        connection.commit()
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    return _to_dict(booking)


def get_booking(booking_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    return _to_dict(booking) if booking is not None else None


def list_bookings() -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM bookings ORDER BY id").fetchall()
    return [_to_dict(row) for row in rows]


def list_user_bookings(user_id: int) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bookings WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [_to_dict(row) for row in rows]
