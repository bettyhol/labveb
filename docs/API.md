# REST API contract

Усі payloads мають `application/json`. Дати передаються як `YYYY-MM-DD`, timestamps — ISO 8601 UTC, money — JSON number із точним decimal-розрахунком. Поля `id`, computed fields, statuses і timestamps формує backend.

## Спільні правила

### Health

Кожен сервіс надає `GET /health` без request body. Успіх — `200 OK`:

```json
{
  "status": "ok",
  "service": "booking-service",
  "version": "1.0.0"
}
```

Поле `service` відповідно має значення `user-service`, `hotel-service`, `room-service`, `booking-service`, `payment-service` або `notification-service`.

### Status codes і errors

| Status | Семантика |
|---|---|
| `200 OK` | Успішний GET або operation, зокрема повторна idempotent operation |
| `201 Created` | Новий resource створено |
| `400 Bad Request` | Payload формально валідний, але порушує business rule |
| `404 Not Found` | Запитаний resource не існує |
| `409 Conflict` | Конфлікт зі станом/унікальністю: overlapping allocation, email або hotel/room number |
| `422 Unprocessable Entity` | Стандартна FastAPI/Pydantic schema validation error |
| `503 Service Unavailable` | Потрібний downstream service недоступний |

Контрольована бізнес-помилка має форму:

```json
{
  "detail": "Payment service is unavailable"
}
```

API не повертає Python traceback. Для list endpoints response є JSON array; для resource/operation — JSON object.

## User Service — `http://localhost:8001`

### Модель User

```json
{
  "id": 1,
  "name": "Maksym",
  "email": "maksym@example.com",
  "phone": "+380991234567",
  "active": true,
  "created_at": "2026-09-12T12:00:00Z"
}
```

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/users` | Створити User | UserCreate | `201`, User | `409` email duplicate, `422` validation |
| `GET` | `/users` | Список users | — | `200`, `User[]` | — |
| `GET` | `/users/{user_id}` | Отримати User | path `user_id` | `200`, User | `404` |
| `PATCH` | `/users/{user_id}` | Частково оновити User | UserUpdate | `200`, User | `400` empty update, `404`, `409` duplicate, `422` validation |
| `DELETE` | `/users/{user_id}` | Soft delete (`active=false`) | — | `200`, User | `404` |

`UserCreate`:

```json
{
  "name": "Maksym",
  "email": "maksym@example.com",
  "phone": "+380991234567"
}
```

`UserUpdate` містить будь-яку непорожню підмножину `name`, `email`, `phone`; відсутні поля не змінюються. Active-стан змінюється тільки через `DELETE`, який не видаляє запис фізично.

## Hotel Service — `http://localhost:8002`

### Модель Hotel

```json
{
  "id": 1,
  "name": "Kharkiv Palace",
  "city": "Kharkiv",
  "address": "Nezalezhnosti Ave, 2",
  "description": "Five-star hotel",
  "rating": 5,
  "active": true,
  "created_at": "2026-09-12T12:00:00Z"
}
```

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/hotels` | Створити Hotel | HotelCreate | `201`, Hotel | `422` validation |
| `GET` | `/hotels` | Список/фільтрація hotels | query `city?`, `min_rating?` | `200`, `Hotel[]` | `400` blank city, `422` invalid `min_rating` |
| `GET` | `/hotels/{hotel_id}` | Отримати Hotel | path `hotel_id` | `200`, Hotel | `404` |
| `PATCH` | `/hotels/{hotel_id}` | Частково оновити Hotel | HotelUpdate | `200`, Hotel | `400` empty update, `404`, `422` validation |
| `DELETE` | `/hotels/{hotel_id}` | Soft delete (`active=false`) | — | `200`, Hotel | `404` |

`HotelCreate`:

```json
{
  "name": "Kharkiv Palace",
  "city": "Kharkiv",
  "address": "Nezalezhnosti Ave, 2",
  "description": "Five-star hotel",
  "rating": 5
}
```

`HotelUpdate` містить будь-яку непорожню підмножину `name`, `city`, `address`, `description`, `rating`; відсутні поля не змінюються. Active-стан змінюється тільки через `DELETE`. `GET /hotels?city=Kharkiv&min_rating=4` повертає hotels, що одночасно відповідають обом переданим фільтрам.

## Room Service — `http://localhost:8003`

### Модель Room

```json
{
  "id": 1,
  "hotel_id": 1,
  "number": "301",
  "room_type": "DELUXE",
  "capacity": 2,
  "price_per_night": 2500,
  "active": true,
  "created_at": "2026-09-12T12:00:00Z"
}
```

### Модель Allocation

```json
{
  "id": 1,
  "room_id": 1,
  "booking_id": 12,
  "check_in": "2026-09-20",
  "check_out": "2026-09-23",
  "status": "HELD",
  "expires_at": null,
  "created_at": "2026-09-12T12:00:00Z",
  "updated_at": "2026-09-12T12:00:00Z"
}
```

### Room endpoints

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/rooms` | Створити Room після Hotel validation | RoomCreate | `201`, Room | `400`, `404` hotel, `409` duplicate, `503` Hotel Service |
| `GET` | `/rooms` | Список rooms | — | `200`, `Room[]` | — |
| `GET` | `/rooms/{room_id}` | Отримати Room | path `room_id` | `200`, Room | `404` |
| `PATCH` | `/rooms/{room_id}` | Частково оновити Room | RoomUpdate | `200`, Room | `400`, `404` room/hotel, `409` duplicate, `503` Hotel Service |
| `DELETE` | `/rooms/{room_id}` | Soft delete (`active=false`) | — | `200`, Room | `404` |
| `GET` | `/hotels/{hotel_id}/rooms` | Кімнати певного Hotel | path `hotel_id` | `200`, `Room[]` | — |
| `GET` | `/rooms/available` | Доступні active rooms за dates/capacity | query AvailabilityQuery | `200`, `Room[]` | `400`, `404` hotel, `503` Hotel Service |

`RoomCreate`:

```json
{
  "hotel_id": 1,
  "number": "301",
  "room_type": "DELUXE",
  "capacity": 2,
  "price_per_night": 2500
}
```

`RoomUpdate` містить будь-яку непорожню підмножину `hotel_id`, `number`, `room_type`, `capacity`, `price_per_night`; поле `active` змінюється лише через `DELETE`. При зміні `hotel_id` Room Service перевіряє новий Hotel через HTTP; якщо `hotel_id` не змінився, зайвий downstream-виклик не виконується.

`AvailabilityQuery` складається з обов’язкових `hotel_id: integer`, `check_in: date`, `check_out: date`, `guests: integer`. Приклад:

```http
GET /rooms/available?hotel_id=1&check_in=2026-09-20&check_out=2026-09-23&guests=2
```

Room потрапляє у відповідь, якщо він active, `capacity >= guests`, Hotel існує й active та немає overlapping `HELD`/`CONFIRMED` allocation. Інтервал напіввідкритий: `[check_in, check_out)`. `check_in >= check_out` дає `400`; невалідний date syntax, `hotel_id <= 0` або `guests <= 0` — `422`.

### Allocation endpoints

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `POST` | `/allocations/hold` | Атомарно перевірити overlap і створити `HELD` | AllocationHold | `201` new / `200` idempotent, Allocation | `400`, `404` room, `409` overlap/booking conflict, `503` DB busy |
| `POST` | `/allocations/{booking_id}/confirm` | `HELD → CONFIRMED` | — | `200`, Allocation | `404`, `409` invalid transition |
| `POST` | `/allocations/{booking_id}/release` | `HELD/CONFIRMED → RELEASED` | — | `200`, Allocation | `404`, `409` invalid transition |
| `GET` | `/allocations/{booking_id}` | Allocation за booking | path `booking_id` | `200`, Allocation | `404` |

`AllocationHold` — внутрішній request від Booking Service:

```json
{
  "booking_id": 12,
  "room_id": 1,
  "check_in": "2026-09-20",
  "check_out": "2026-09-23"
}
```

Hold виконує реальний `BEGIN IMMEDIATE`, потім в тій самій transaction перевіряє existing `booking_id`, Room active-state і overlapping `HELD`/`CONFIRMED`, вставляє `HELD` та commit-ить. Conflict/exception робить rollback. Identical retry існуючого `HELD` або `CONFIRMED` повертає той самий allocation з `200`; retry з іншим Room/dates дає `409`.

Transitions: `HELD → CONFIRMED`, `HELD → RELEASED`, `CONFIRMED → RELEASED`. Повторні confirm для `CONFIRMED` і release для `RELEASED` є idempotent `200` no-op і не змінюють `updated_at`. `RELEASED` terminal: його не можна confirm-ити або hold-ити повторно з тим самим `booking_id`. `expires_at` у Phase 4 дорівнює `null`; auto-expiration немає.

## Booking Service — `http://localhost:8004`

### Модель Booking

```json
{
  "id": 12,
  "user_id": 1,
  "hotel_id": 1,
  "hotel_name": "Kharkiv Palace",
  "room_id": 1,
  "room_number": "301",
  "room_type": "DELUXE",
  "check_in": "2026-09-20",
  "check_out": "2026-09-23",
  "nights": 3,
  "price_per_night": 2500,
  "total_amount": 7500,
  "status": "CONFIRMED",
  "payment_id": 8,
  "created_at": "2026-09-12T12:00:00Z",
  "updated_at": "2026-09-12T12:00:02Z"
}
```

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/bookings` | Виконати Create Booking Saga | BookingCreate | `201`, Booking | `400`, `404`, `409`, `503` downstream |
| `GET` | `/bookings` | Список bookings | — | `200`, `Booking[]` | — |
| `GET` | `/bookings/{booking_id}` | Отримати Booking | path `booking_id` | `200`, Booking | `404` |
| `POST` | `/bookings/{booking_id}/cancel` | Refund, release і cancel Booking | — | `200`, Booking `CANCELLED` | `404`, `409`, `503` downstream |
| `GET` | `/users/{user_id}/bookings` | Історія bookings користувача | path `user_id` | `200`, `Booking[]` | — |

`BookingCreate`:

```json
{
  "user_id": 1,
  "room_id": 1,
  "check_in": "2026-09-20",
  "check_out": "2026-09-23"
}
```

Клієнт не передає `hotel_id`, room snapshot, price, `nights` або `total_amount`. Booking Service отримує їх із Room/Hotel Services і розраховує:

```text
nights = check_out - check_in
total_amount = nights * price_per_night
```

Inactive User/Room/Hotel або неправильні dates дають `400`; відсутня сутність — `404`; downstream conflict — `409`; transport/5xx failure — controlled `503`. Успішний flow створює local `PENDING`, виконує HOLD, PAID і allocation CONFIRM, переводить Booking у `CONFIRMED` та повертає `201`. Notification failure не змінює цей результат.

Definitive Payment `FAILED` створює реальний Payment resource, тому після Room release `POST /bookings` повертає `201` із Booking `PAYMENT_FAILED` та його `payment_id`: HTTP resource creation не дорівнює successful booking outcome. Payment transport failure retry-иться рівно один раз з ідентичним payload; після двох невдалих спроб повертається `503`, а підтверджена compensation переводить Booking у `PAYMENT_FAILED` без відомого `payment_id`.

Cancellation приймає лише `CONFIRMED`: Payment refund → Room release → local `CANCELLED` → best-effort `BOOKING_CANCELLED`. `PENDING`/`PAYMENT_FAILED` дають `409`, unknown ID — `404`. Повтор для вже `CANCELLED` повертає `200` без downstream calls, повторного notification або зміни `updated_at`.

## Payment Service — `http://localhost:8005`

### Модель Payment

```json
{
  "id": 8,
  "booking_id": 12,
  "user_id": 1,
  "amount": 7500,
  "currency": "UAH",
  "method": "CARD",
  "status": "PAID",
  "transaction_ref": "TX-1F92DA71",
  "created_at": "2026-09-12T12:00:01Z",
  "refunded_at": null
}
```

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/payments` | Створити/симулювати payment | PaymentCreate | `201` новий або `200` idempotent Payment | `409` payload не відповідає existing payment, `422` validation |
| `GET` | `/payments/{payment_id}` | Payment за ID | path `payment_id` | `200`, Payment | `404` |
| `GET` | `/bookings/{booking_id}/payment` | Payment за Booking ID | path `booking_id` | `200`, Payment | `404` |
| `POST` | `/payments/{payment_id}/refund` | Idempotent refund | — | `200`, Payment зі status `REFUNDED` | `404`, `409` payment не `PAID/REFUNDED` |

`PaymentCreate`:

```json
{
  "booking_id": 12,
  "user_id": 1,
  "amount": 7500,
  "currency": "UAH",
  "method": "CARD",
  "simulate_failure": false
}
```

`simulate_failure` є optional request-only полем: `false` створює `PAID` з UUID transaction reference, `true` — `FAILED` без reference; обидва первинні результати повертаються з `201`. `booking_id` є idempotency key. Повтор із тим самим canonical payload повертає первинний Payment з `200` незалежно від нового `simulate_failure`; інші user/amount/currency/method дають `409`. Повторний refund стану `REFUNDED` не змінює `refunded_at`.

## Notification Service — `http://localhost:8006`

### Модель Notification

```json
{
  "id": 15,
  "user_id": 1,
  "booking_id": 12,
  "type": "BOOKING_CONFIRMED",
  "channel": "EMAIL",
  "recipient": "maksym@example.com",
  "subject": "Booking confirmed",
  "message": "Booking #12 has been confirmed.",
  "status": "SENT",
  "is_read": false,
  "created_at": "2026-09-12T12:00:02Z"
}
```

| Method | Path | Purpose | Request | Success response | Important errors |
|---|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `200`, Health | — |
| `POST` | `/notifications` | Зберегти й симулювати відправлення | NotificationCreate | `201`, Notification | `422` validation/type/channel |
| `GET` | `/notifications` | Список notifications | — | `200`, `Notification[]` | — |
| `GET` | `/notifications/{notification_id}` | Отримати Notification | path ID | `200`, Notification | `404` |
| `GET` | `/users/{user_id}/notifications` | Історія користувача | path `user_id` | `200`, `Notification[]` | — |
| `POST` | `/notifications/{notification_id}/read` | Встановити `is_read=true` | — | `200`, Notification | `404` |

`NotificationCreate`:

```json
{
  "user_id": 1,
  "booking_id": 12,
  "type": "BOOKING_CONFIRMED",
  "channel": "EMAIL",
  "recipient": "maksym@example.com",
  "subject": "Booking confirmed",
  "message": "Booking #12 has been confirmed."
}
```

Допустимі types: `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`, `PAYMENT_FAILED`; channel — `EMAIL`, а `booking_id` може бути `null`. Сервер встановлює `SENT`, `is_read=false` й UTC timestamp та пише `[EMAIL]` у log без network delivery. Кожний POST створює новий запис. Повторне позначення прочитаним безпечне й повертає поточний resource.
