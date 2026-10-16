"""Persistence and state transitions for Payment Service."""

import sqlite3
import uuid
from datetime import datetime, timezone
from sqlite3 import Row

from .database import get_connection


class PaymentConflictError(Exception):
    """Raised when a request conflicts with an existing payment."""


class PaymentNotFoundError(Exception):
    """Raised when a payment cannot be found."""


def _to_dict(row: Row) -> dict[str, object]:
    return dict(row)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _same_payment(
    payment: Row,
    *,
    user_id: int,
    amount: float,
    currency: str,
    method: str,
) -> bool:
    return (
        payment["user_id"] == user_id
        and payment["amount"] == amount
        and payment["currency"] == currency
        and payment["method"] == method
    )


def _resolve_existing(
    payment: Row,
    *,
    user_id: int,
    amount: float,
    currency: str,
    method: str,
) -> dict[str, object]:
    if not _same_payment(
        payment,
        user_id=user_id,
        amount=amount,
        currency=currency,
        method=method,
    ):
        raise PaymentConflictError("Booking already has a different payment")
    return _to_dict(payment)


def create_payment(
    *,
    booking_id: int,
    user_id: int,
    amount: float,
    currency: str,
    method: str,
    simulate_failure: bool,
) -> tuple[dict[str, object], bool]:
    """Create one payment per booking or return its idempotent result."""
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT * FROM payments WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
        if existing is not None:
            return (
                _resolve_existing(
                    existing,
                    user_id=user_id,
                    amount=amount,
                    currency=currency,
                    method=method,
                ),
                False,
            )

        payment_status = "FAILED" if simulate_failure else "PAID"
        transaction_ref = None
        if payment_status == "PAID":
            transaction_ref = f"TX-{uuid.uuid4().hex.upper()}"

        try:
            cursor = connection.execute(
                """
                INSERT INTO payments (
                    booking_id, user_id, amount, currency, method, status,
                    transaction_ref, created_at, refunded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    booking_id,
                    user_id,
                    amount,
                    currency,
                    method,
                    payment_status,
                    transaction_ref,
                    _utc_now_iso(),
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            concurrent = connection.execute(
                "SELECT * FROM payments WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if concurrent is None:
                raise
            return (
                _resolve_existing(
                    concurrent,
                    user_id=user_id,
                    amount=amount,
                    currency=currency,
                    method=method,
                ),
                False,
            )

        payment = connection.execute(
            "SELECT * FROM payments WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_dict(payment), True


def get_payment(payment_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM payments WHERE id = ?",
            (payment_id,),
        ).fetchone()
    return _to_dict(payment) if payment is not None else None


def get_payment_by_booking(booking_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM payments WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
    return _to_dict(payment) if payment is not None else None


def refund_payment(payment_id: int) -> dict[str, object]:
    """Atomically refund a PAID payment or replay an existing refund."""
    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            payment = connection.execute(
                "SELECT * FROM payments WHERE id = ?",
                (payment_id,),
            ).fetchone()
            if payment is None:
                raise PaymentNotFoundError
            if payment["status"] == "REFUNDED":
                connection.commit()
                return _to_dict(payment)
            if payment["status"] != "PAID":
                raise PaymentConflictError("Only paid payments can be refunded")

            connection.execute(
                """
                UPDATE payments
                SET status = 'REFUNDED', refunded_at = ?
                WHERE id = ? AND status = 'PAID'
                """,
                (_utc_now_iso(), payment_id),
            )
            refunded = connection.execute(
                "SELECT * FROM payments WHERE id = ?",
                (payment_id,),
            ).fetchone()
            connection.commit()
            return _to_dict(refunded)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
