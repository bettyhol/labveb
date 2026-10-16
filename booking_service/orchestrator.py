"""Booking Saga orchestration, compensation, and cancellation workflows."""

import logging
import sqlite3
from decimal import Decimal, InvalidOperation

from . import clients, models
from .schemas import BookingCreate


logger = logging.getLogger("uvicorn.error")
MAX_PAYMENT_ATTEMPTS = 2


class BookingSagaError(Exception):
    """Controlled API-facing failure raised by Booking orchestration."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _downstream_error(error: Exception) -> BookingSagaError:
    if isinstance(error, clients.ServiceUnavailableError):
        return BookingSagaError(503, str(error))
    if isinstance(error, clients.DownstreamHTTPError):
        return BookingSagaError(error.status_code, error.detail)
    if isinstance(error, BookingSagaError):
        return error
    raise error


def _database_error() -> BookingSagaError:
    return BookingSagaError(500, "Booking database error")


def _mark_payment_failed(
    booking_id: int,
    payment_id: int | None,
) -> dict[str, object]:
    try:
        return models.mark_payment_failed(booking_id, payment_id)
    except (sqlite3.Error, models.BookingStateError) as error:
        raise _database_error() from error


def _cleanup_pending(booking_id: int) -> None:
    try:
        if not models.delete_pending_booking(booking_id):
            raise models.BookingStateError("Pending Booking cleanup failed")
    except (sqlite3.Error, models.BookingStateError) as error:
        raise _database_error() from error


def _release_allocation(
    service_clients: clients.BookingServiceClients,
    booking_id: int,
    *,
    absent_is_success: bool = False,
) -> None:
    try:
        allocation = service_clients.release_room_allocation(booking_id)
    except clients.DownstreamHTTPError as error:
        if absent_is_success and error.status_code == 404:
            return
        raise _downstream_error(error) from error
    except clients.ServiceUnavailableError as error:
        raise _downstream_error(error) from error

    if (
        allocation.get("booking_id") != booking_id
        or allocation.get("status") != "RELEASED"
    ):
        raise BookingSagaError(503, "Room compensation was not completed")


def _refund_payment(
    service_clients: clients.BookingServiceClients,
    payment_id: int,
) -> None:
    try:
        payment = service_clients.refund_payment(payment_id)
    except (clients.ServiceUnavailableError, clients.DownstreamHTTPError) as error:
        raise _downstream_error(error) from error
    if payment.get("id") != payment_id or payment.get("status") != "REFUNDED":
        raise BookingSagaError(409, "Payment was not refunded")


def _notification_payload(
    *,
    booking_id: int,
    user_id: int,
    recipient: str,
    notification_type: str,
) -> dict[str, object]:
    subjects = {
        "BOOKING_CONFIRMED": "Booking confirmed",
        "PAYMENT_FAILED": "Payment failed",
        "BOOKING_CANCELLED": "Booking cancelled",
    }
    messages = {
        "BOOKING_CONFIRMED": f"Booking #{booking_id} has been confirmed.",
        "PAYMENT_FAILED": f"Payment for booking #{booking_id} failed.",
        "BOOKING_CANCELLED": f"Booking #{booking_id} has been cancelled.",
    }
    return {
        "user_id": user_id,
        "booking_id": booking_id,
        "type": notification_type,
        "channel": "EMAIL",
        "recipient": recipient,
        "subject": subjects[notification_type],
        "message": messages[notification_type],
    }


def _try_notification(
    service_clients: clients.BookingServiceClients,
    *,
    booking_id: int,
    user_id: int,
    recipient: str,
    notification_type: str,
) -> None:
    try:
        notification = service_clients.create_notification(
            _notification_payload(
                booking_id=booking_id,
                user_id=user_id,
                recipient=recipient,
                notification_type=notification_type,
            )
        )
        if (
            notification.get("booking_id") != booking_id
            or notification.get("status") != "SENT"
        ):
            raise clients.ServiceUnavailableError("Notification")
    except (clients.ServiceUnavailableError, clients.DownstreamHTTPError):
        logger.warning(
            "Notification delivery failed: booking_id=%s type=%s",
            booking_id,
            notification_type,
        )


def _try_cancellation_notification(
    service_clients: clients.BookingServiceClients,
    booking: dict[str, object],
) -> None:
    booking_id = int(booking["id"])
    try:
        user = service_clients.get_user(int(booking["user_id"]))
        if user is None or not user.get("email"):
            raise clients.ServiceUnavailableError("User")
    except (clients.ServiceUnavailableError, clients.DownstreamHTTPError):
        logger.warning(
            "Notification recipient lookup failed: booking_id=%s "
            "type=BOOKING_CANCELLED",
            booking_id,
        )
        return
    _try_notification(
        service_clients,
        booking_id=booking_id,
        user_id=int(booking["user_id"]),
        recipient=str(user["email"]),
        notification_type="BOOKING_CANCELLED",
    )


def _create_payment_with_retry(
    service_clients: clients.BookingServiceClients,
    payload: dict[str, object],
) -> dict[str, object]:
    for attempt in range(1, MAX_PAYMENT_ATTEMPTS + 1):
        try:
            return service_clients.create_payment(payload)
        except clients.ServiceUnavailableError:
            if attempt == MAX_PAYMENT_ATTEMPTS:
                raise
            logger.warning(
                "Retrying idempotent payment create: booking_id=%s attempt=%s",
                payload["booking_id"],
                attempt + 1,
            )
    raise RuntimeError("Unreachable payment retry state")


def _compensate_after_paid(
    service_clients: clients.BookingServiceClients,
    *,
    booking_id: int,
    payment_id: int,
    user_id: int,
    recipient: str,
) -> dict[str, object]:
    logger.warning(
        "Starting paid-booking compensation: booking_id=%s payment_id=%s",
        booking_id,
        payment_id,
    )
    _refund_payment(service_clients, payment_id)
    logger.info(
        "Payment refund compensation completed: booking_id=%s payment_id=%s",
        booking_id,
        payment_id,
    )
    _release_allocation(service_clients, booking_id)
    logger.info("Room release compensation completed: booking_id=%s", booking_id)
    booking = _mark_payment_failed(booking_id, payment_id)
    _try_notification(
        service_clients,
        booking_id=booking_id,
        user_id=user_id,
        recipient=recipient,
        notification_type="PAYMENT_FAILED",
    )
    return booking


def _load_creation_resources(
    service_clients: clients.BookingServiceClients,
    payload: BookingCreate,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    try:
        user = service_clients.get_user(payload.user_id)
        if user is None:
            raise BookingSagaError(404, "User not found")
        if user.get("active") is not True:
            raise BookingSagaError(400, "User is inactive")

        room = service_clients.get_room(payload.room_id)
        if room is None:
            raise BookingSagaError(404, "Room not found")
        if room.get("active") is not True:
            raise BookingSagaError(400, "Room is inactive")

        hotel_id = int(room["hotel_id"])
        hotel = service_clients.get_hotel(hotel_id)
        if hotel is None:
            raise BookingSagaError(404, "Hotel not found")
        if hotel.get("active") is not True:
            raise BookingSagaError(400, "Hotel is inactive")
    except (clients.ServiceUnavailableError, clients.DownstreamHTTPError) as error:
        raise _downstream_error(error) from error
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise BookingSagaError(
            503,
            "Downstream service returned invalid data",
        ) from error
    return user, room, hotel


def create_booking(
    payload: BookingCreate,
    service_clients: clients.BookingServiceClients,
) -> dict[str, object]:
    """Run create Booking Saga including failure compensation."""
    if payload.check_in >= payload.check_out:
        raise BookingSagaError(400, "check_in must be before check_out")

    user, room, hotel = _load_creation_resources(service_clients, payload)
    nights = (payload.check_out - payload.check_in).days
    try:
        price_per_night = Decimal(str(room["price_per_night"]))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise BookingSagaError(503, "Room service returned invalid data") from error
    if not price_per_night.is_finite() or price_per_night <= 0:
        raise BookingSagaError(503, "Room service returned invalid data")
    total_amount = price_per_night * nights

    try:
        booking = models.create_pending_booking(
            user_id=payload.user_id,
            hotel_id=int(room["hotel_id"]),
            hotel_name=str(hotel["name"]),
            room_id=payload.room_id,
            room_number=str(room["number"]),
            room_type=str(room["room_type"]),
            check_in=payload.check_in,
            check_out=payload.check_out,
            nights=nights,
            price_per_night=price_per_night,
            total_amount=total_amount,
        )
    except sqlite3.Error as error:
        raise _database_error() from error

    booking_id = int(booking["id"])
    recipient = str(user["email"])
    hold_payload = {
        "booking_id": booking_id,
        "room_id": payload.room_id,
        "check_in": payload.check_in.isoformat(),
        "check_out": payload.check_out.isoformat(),
    }
    try:
        allocation = service_clients.hold_room(hold_payload)
    except clients.DownstreamHTTPError as error:
        _cleanup_pending(booking_id)
        raise _downstream_error(error) from error
    except clients.ServiceUnavailableError as error:
        try:
            _release_allocation(
                service_clients,
                booking_id,
                absent_is_success=True,
            )
            _cleanup_pending(booking_id)
        except BookingSagaError:
            logger.error(
                "Ambiguous Room HOLD compensation failed: booking_id=%s",
                booking_id,
            )
        raise _downstream_error(error) from error

    if (
        allocation.get("booking_id") != booking_id
        or allocation.get("status") != "HELD"
    ):
        try:
            _release_allocation(service_clients, booking_id, absent_is_success=True)
            _cleanup_pending(booking_id)
        except BookingSagaError:
            logger.error(
                "Unexpected Room HOLD response compensation failed: booking_id=%s",
                booking_id,
            )
        raise BookingSagaError(409, "Room allocation was not held")

    payment_payload = {
        "booking_id": booking_id,
        "user_id": payload.user_id,
        "amount": float(total_amount),
        "currency": "UAH",
        "method": "CARD",
    }
    try:
        payment = _create_payment_with_retry(service_clients, payment_payload)
    except clients.ServiceUnavailableError as error:
        try:
            _release_allocation(service_clients, booking_id)
            _mark_payment_failed(booking_id, None)
            _try_notification(
                service_clients,
                booking_id=booking_id,
                user_id=payload.user_id,
                recipient=recipient,
                notification_type="PAYMENT_FAILED",
            )
        except BookingSagaError:
            logger.error(
                "Payment unavailable and Room compensation failed: booking_id=%s",
                booking_id,
            )
        raise _downstream_error(error) from error
    except clients.DownstreamHTTPError as error:
        try:
            _release_allocation(service_clients, booking_id)
            _mark_payment_failed(booking_id, None)
            _try_notification(
                service_clients,
                booking_id=booking_id,
                user_id=payload.user_id,
                recipient=recipient,
                notification_type="PAYMENT_FAILED",
            )
        except BookingSagaError:
            logger.error(
                "Payment rejection compensation failed: booking_id=%s",
                booking_id,
            )
        raise _downstream_error(error) from error

    if payment.get("booking_id") != booking_id:
        logger.error("Payment response mismatch: booking_id=%s", booking_id)
        raise BookingSagaError(503, "Payment service returned invalid data")

    try:
        payment_id = int(payment["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise BookingSagaError(503, "Payment service returned invalid data") from error

    if payment.get("status") != "PAID":
        try:
            _release_allocation(service_clients, booking_id)
        except BookingSagaError:
            logger.error(
                "Payment failed and Room compensation failed: booking_id=%s",
                booking_id,
            )
            raise
        booking = _mark_payment_failed(booking_id, payment_id)
        _try_notification(
            service_clients,
            booking_id=booking_id,
            user_id=payload.user_id,
            recipient=recipient,
            notification_type="PAYMENT_FAILED",
        )
        return booking

    confirm_failure: BookingSagaError | None = None
    try:
        confirmed_allocation = service_clients.confirm_room_allocation(booking_id)
        if (
            confirmed_allocation.get("booking_id") != booking_id
            or confirmed_allocation.get("status") != "CONFIRMED"
        ):
            raise BookingSagaError(409, "Room allocation was not confirmed")
    except (clients.ServiceUnavailableError, clients.DownstreamHTTPError) as error:
        confirm_failure = _downstream_error(error)
    except BookingSagaError as error:
        confirm_failure = error

    if confirm_failure is not None:
        try:
            _compensate_after_paid(
                service_clients,
                booking_id=booking_id,
                payment_id=payment_id,
                user_id=payload.user_id,
                recipient=recipient,
            )
        except BookingSagaError as compensation_error:
            logger.error(
                "Paid-booking compensation failed: booking_id=%s",
                booking_id,
            )
            raise compensation_error
        raise confirm_failure

    try:
        booking = models.confirm_booking(booking_id, payment_id)
    except (sqlite3.Error, models.BookingStateError) as error:
        try:
            _compensate_after_paid(
                service_clients,
                booking_id=booking_id,
                payment_id=payment_id,
                user_id=payload.user_id,
                recipient=recipient,
            )
        except BookingSagaError:
            logger.error(
                "Local Booking confirm and compensation failed: booking_id=%s",
                booking_id,
            )
        raise _database_error() from error

    _try_notification(
        service_clients,
        booking_id=booking_id,
        user_id=payload.user_id,
        recipient=recipient,
        notification_type="BOOKING_CONFIRMED",
    )
    return booking


def cancel_booking(
    booking_id: int,
    service_clients: clients.BookingServiceClients,
) -> dict[str, object]:
    """Run the idempotent refund → release → cancellation Saga."""
    try:
        booking = models.get_booking(booking_id)
    except sqlite3.Error as error:
        raise _database_error() from error
    if booking is None:
        raise BookingSagaError(404, "Booking not found")
    if booking["status"] == "CANCELLED":
        return booking
    if booking["status"] != "CONFIRMED":
        raise BookingSagaError(409, "Only confirmed bookings can be cancelled")
    if booking["payment_id"] is None:
        raise BookingSagaError(409, "Confirmed booking has no payment")

    payment_id = int(booking["payment_id"])
    _refund_payment(service_clients, payment_id)
    _release_allocation(service_clients, booking_id)

    try:
        cancelled = models.cancel_booking(booking_id)
    except (sqlite3.Error, models.BookingStateError) as error:
        raise _database_error() from error
    _try_cancellation_notification(service_clients, cancelled)
    return cancelled
