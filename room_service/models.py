"""Persistence operations for Room Service."""

import sqlite3
from datetime import date, datetime, timezone
from sqlite3 import Row

from .database import get_connection


UPDATE_COLUMNS = {
    "hotel_id": "hotel_id = ?",
    "number": "number = ?",
    "room_type": "room_type = ?",
    "capacity": "capacity = ?",
    "price_per_night": "price_per_night = ?",
}

ACTIVE_ALLOCATION_STATUSES = ("HELD", "CONFIRMED")


class RoomNotFoundError(Exception):
    """Raised when an allocation references an unknown Room."""


class RoomInactiveError(Exception):
    """Raised when an allocation references an inactive Room."""


class AllocationNotFoundError(Exception):
    """Raised when an allocation cannot be found by booking ID."""


class AllocationConflictError(Exception):
    """Raised when allocation state or dates conflict."""


class DatabaseBusyError(Exception):
    """Raised when SQLite cannot acquire its write reservation in time."""


def _to_dict(row: Row) -> dict[str, object]:
    result = dict(row)
    result["active"] = bool(result["active"])
    return result


def _allocation_to_dict(row: Row) -> dict[str, object]:
    return dict(row)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rollback(connection) -> None:
    if connection.in_transaction:
        connection.rollback()


def _raise_database_error(error: Exception) -> None:
    if (
        isinstance(error, sqlite3.OperationalError)
        and "locked" in str(error).lower()
    ):
        raise DatabaseBusyError from error
    raise error


def create_room(
    hotel_id: int,
    number: str,
    room_type: str,
    capacity: int,
    price_per_night: float,
) -> dict[str, object]:
    created_at = _utc_now_iso()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO rooms (
                hotel_id, number, room_type, capacity,
                price_per_night, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, TRUE, ?)
            """,
            (
                hotel_id,
                number,
                room_type,
                capacity,
                price_per_night,
                created_at,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM rooms WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_dict(row)


def list_rooms() -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM rooms ORDER BY id").fetchall()
    return [_to_dict(row) for row in rows]


def list_hotel_rooms(hotel_id: int) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM rooms WHERE hotel_id = ? ORDER BY id",
            (hotel_id,),
        ).fetchall()
    return [_to_dict(row) for row in rows]


def get_room(room_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM rooms WHERE id = ?",
            (room_id,),
        ).fetchone()
    return _to_dict(row) if row is not None else None


def update_room(
    room_id: int,
    changes: dict[str, object],
) -> dict[str, object] | None:
    assignments = ", ".join(UPDATE_COLUMNS[field] for field in changes)
    parameters = [*changes.values(), room_id]

    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE rooms SET {assignments} WHERE id = ?",
            parameters,
        )
        if cursor.rowcount == 0:
            return None
        connection.commit()
        row = connection.execute(
            "SELECT * FROM rooms WHERE id = ?",
            (room_id,),
        ).fetchone()
    return _to_dict(row)


def soft_delete_room(room_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE rooms SET active = FALSE WHERE id = ?",
            (room_id,),
        )
        if cursor.rowcount == 0:
            return None
        connection.commit()
        row = connection.execute(
            "SELECT * FROM rooms WHERE id = ?",
            (room_id,),
        ).fetchone()
    return _to_dict(row)


def list_available_rooms(
    hotel_id: int,
    check_in: date,
    check_out: date,
    guests: int,
) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT rooms.*
            FROM rooms
            WHERE rooms.hotel_id = ?
              AND rooms.active = TRUE
              AND rooms.capacity >= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM room_allocations
                  WHERE room_allocations.room_id = rooms.id
                    AND room_allocations.status IN ('HELD', 'CONFIRMED')
                    AND room_allocations.check_in < ?
                    AND room_allocations.check_out > ?
              )
            ORDER BY rooms.id
            """,
            (hotel_id, guests, check_out.isoformat(), check_in.isoformat()),
        ).fetchall()
    return [_to_dict(row) for row in rows]


def get_allocation(booking_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM room_allocations WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
    return _allocation_to_dict(row) if row is not None else None


def hold_allocation(
    *,
    booking_id: int,
    room_id: int,
    check_in: date,
    check_out: date,
) -> tuple[dict[str, object], bool]:
    """Atomically check availability and create or replay a hold."""
    check_in_value = check_in.isoformat()
    check_out_value = check_out.isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                "SELECT * FROM room_allocations WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if existing is not None:
                same_request = (
                    existing["room_id"] == room_id
                    and existing["check_in"] == check_in_value
                    and existing["check_out"] == check_out_value
                )
                if not same_request:
                    raise AllocationConflictError(
                        "Booking already has a different room allocation"
                    )
                if existing["status"] == "RELEASED":
                    raise AllocationConflictError(
                        "Released allocation cannot be held again"
                    )

                connection.commit()
                return _allocation_to_dict(existing), False

            room = connection.execute(
                "SELECT id, active FROM rooms WHERE id = ?",
                (room_id,),
            ).fetchone()
            if room is None:
                raise RoomNotFoundError
            if not bool(room["active"]):
                raise RoomInactiveError

            overlap = connection.execute(
                """
                SELECT 1
                FROM room_allocations
                WHERE room_id = ?
                  AND status IN (?, ?)
                  AND check_in < ?
                  AND check_out > ?
                LIMIT 1
                """,
                (
                    room_id,
                    *ACTIVE_ALLOCATION_STATUSES,
                    check_out_value,
                    check_in_value,
                ),
            ).fetchone()
            if overlap is not None:
                raise AllocationConflictError(
                    "Room is not available for the selected dates"
                )

            timestamp = _utc_now_iso()
            cursor = connection.execute(
                """
                INSERT INTO room_allocations (
                    room_id, booking_id, check_in, check_out, status,
                    expires_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'HELD', NULL, ?, ?)
                """,
                (
                    room_id,
                    booking_id,
                    check_in_value,
                    check_out_value,
                    timestamp,
                    timestamp,
                ),
            )
            allocation = connection.execute(
                "SELECT * FROM room_allocations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()
            return _allocation_to_dict(allocation), True
        except Exception as error:
            _rollback(connection)
            _raise_database_error(error)


def _transition_allocation(
    booking_id: int,
    target_status: str,
) -> dict[str, object]:
    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            allocation = connection.execute(
                "SELECT * FROM room_allocations WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if allocation is None:
                raise AllocationNotFoundError

            current_status = allocation["status"]
            if current_status == target_status:
                connection.commit()
                return _allocation_to_dict(allocation)

            if target_status == "CONFIRMED" and current_status == "RELEASED":
                raise AllocationConflictError(
                    "Released allocation cannot be confirmed"
                )

            allowed_transition = (
                target_status == "CONFIRMED" and current_status == "HELD"
            ) or (
                target_status == "RELEASED"
                and current_status in ACTIVE_ALLOCATION_STATUSES
            )
            if not allowed_transition:
                raise AllocationConflictError("Invalid allocation state transition")

            updated_at = _utc_now_iso()
            cursor = connection.execute(
                """
                UPDATE room_allocations
                SET status = ?, updated_at = ?
                WHERE booking_id = ? AND status = ?
                """,
                (target_status, updated_at, booking_id, current_status),
            )
            if cursor.rowcount != 1:
                raise AllocationConflictError("Allocation state changed concurrently")

            updated = connection.execute(
                "SELECT * FROM room_allocations WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            connection.commit()
            return _allocation_to_dict(updated)
        except Exception as error:
            _rollback(connection)
            _raise_database_error(error)


def confirm_allocation(booking_id: int) -> dict[str, object]:
    return _transition_allocation(booking_id, "CONFIRMED")


def release_allocation(booking_id: int) -> dict[str, object]:
    return _transition_allocation(booking_id, "RELEASED")
