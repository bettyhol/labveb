"""Persistence operations for Hotel Service."""

from datetime import datetime, timezone
from sqlite3 import Row

from .database import get_connection


UPDATE_COLUMNS = {
    "name": "name = ?",
    "city": "city = ?",
    "address": "address = ?",
    "description": "description = ?",
    "rating": "rating = ?",
}


def _to_dict(row: Row) -> dict[str, object]:
    result = dict(row)
    result["active"] = bool(result["active"])
    return result


def create_hotel(
    name: str,
    city: str,
    address: str,
    description: str | None,
    rating: int,
) -> dict[str, object]:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO hotels (
                name, city, address, description, rating, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, TRUE, ?)
            """,
            (name, city, address, description, rating, created_at),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM hotels WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_dict(row)


def list_hotels(
    city: str | None = None,
    min_rating: int | None = None,
) -> list[dict[str, object]]:
    clauses: list[str] = []
    parameters: list[object] = []

    if city is not None:
        clauses.append("city = ? COLLATE NOCASE")
        parameters.append(city)
    if min_rating is not None:
        clauses.append("rating >= ?")
        parameters.append(min_rating)

    query = "SELECT * FROM hotels"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"

    with get_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [_to_dict(row) for row in rows]


def get_hotel(hotel_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM hotels WHERE id = ?",
            (hotel_id,),
        ).fetchone()
    return _to_dict(row) if row is not None else None


def update_hotel(
    hotel_id: int,
    changes: dict[str, object],
) -> dict[str, object] | None:
    assignments = ", ".join(UPDATE_COLUMNS[field] for field in changes)
    parameters = [*changes.values(), hotel_id]

    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE hotels SET {assignments} WHERE id = ?",
            parameters,
        )
        if cursor.rowcount == 0:
            return None
        connection.commit()
        row = connection.execute(
            "SELECT * FROM hotels WHERE id = ?",
            (hotel_id,),
        ).fetchone()
    return _to_dict(row)


def soft_delete_hotel(hotel_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE hotels SET active = FALSE WHERE id = ?",
            (hotel_id,),
        )
        if cursor.rowcount == 0:
            return None
        connection.commit()
        row = connection.execute(
            "SELECT * FROM hotels WHERE id = ?",
            (hotel_id,),
        ).fetchone()
    return _to_dict(row)
