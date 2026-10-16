# Схеми баз даних

## Головне правило

**NO CROSS-DATABASE ACCESS.** Кожен сервіс відкриває лише свій SQLite-файл. Посилання на сутності інших сервісів є звичайними IDs без міжбазових foreign keys; перевірка зовнішніх сутностей відбувається через REST API їх власника.

Для `BOOLEAN` у SQLite мають використовуватися `0/1`, для `DATE` — ISO `YYYY-MM-DD`, для `DATETIME` — ISO 8601 у UTC. Грошові значення API повертає як decimal-compatible number; реалізація не повинна використовувати binary float для фінальних розрахунків.

## `users.db`

**Owner:** User Service.

### `users`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор користувача |
| `name` | `TEXT NOT NULL` | Ім’я |
| `email` | `TEXT NOT NULL UNIQUE` | Унікальний email |
| `phone` | `TEXT NULL` | Телефон |
| `active` | `BOOLEAN NOT NULL DEFAULT TRUE` | Ознака soft delete |
| `created_at` | `TEXT NOT NULL` | UTC ISO 8601 час створення |

`UNIQUE(email)` одночасно є важливим unique rule/index. `DELETE /users/{id}` змінює `active` на false і не видаляє рядок.

## `hotels.db`

**Owner:** Hotel Service.

### `hotels`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор готелю |
| `name` | `TEXT NOT NULL` | Назва |
| `city` | `TEXT NOT NULL` | Місто |
| `address` | `TEXT NOT NULL` | Адреса |
| `description` | `TEXT NULL` | Опис |
| `rating` | `INTEGER NOT NULL`, значення `1..5` | Рейтинг |
| `active` | `BOOLEAN NOT NULL DEFAULT TRUE` | Ознака soft delete |
| `created_at` | `TEXT NOT NULL` | UTC ISO 8601 час створення |

Має бути constraint `CHECK (rating BETWEEN 1 AND 5)`. Для `GET /hotels?city=...&min_rating=...` доцільний index `(city, rating)`. Soft delete лише змінює `active=false`.

## `rooms.db`

**Owner:** Room Service.

### `rooms`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор номера |
| `hotel_id` | `INTEGER NOT NULL` | Логічне посилання на Hotel Service |
| `number` | `TEXT NOT NULL` | Номер усередині готелю |
| `room_type` | `TEXT NOT NULL` | `STANDARD`, `DELUXE` або `SUITE` |
| `capacity` | `INTEGER NOT NULL` | Максимальна кількість гостей |
| `price_per_night` | `REAL NOT NULL` | Ціна за ніч, більше нуля |
| `active` | `BOOLEAN NOT NULL DEFAULT TRUE` | Ознака soft delete |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC час створення |

Constraints: `UNIQUE(hotel_id, number)`, `CHECK (room_type IN ('STANDARD','DELUXE','SUITE'))`, `CHECK (capacity > 0)`, `CHECK (price_per_night > 0)`. Index `(hotel_id, active, capacity)` підтримує список кімнат і пошук кандидатів. `hotel_id` не є SQLite foreign key до `hotels.db`.

### `room_allocations`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор allocation |
| `room_id` | `INTEGER NOT NULL` | Посилання на `rooms.id` у цій БД |
| `booking_id` | `INTEGER NOT NULL UNIQUE` | Ідемпотентний зв’язок з бронюванням |
| `check_in` | `TEXT NOT NULL` | ISO date; початок зайнятості, включно |
| `check_out` | `TEXT NOT NULL` | ISO date; кінець зайнятості, не включно |
| `status` | `TEXT NOT NULL` | `HELD`, `CONFIRMED`, `RELEASED` |
| `expires_at` | `TEXT NULL` | ISO 8601 UTC момент завершення тимчасового hold |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC час створення |
| `updated_at` | `TEXT NOT NULL` | ISO 8601 UTC час останнього переходу status |

Constraints: local foreign key `room_id → rooms.id`, `UNIQUE(booking_id)`, `CHECK (check_in < check_out)` і status check. Index `(room_id, status, check_in, check_out)` потрібний для overlap query. Записи `RELEASED` залишаються в історії, але не блокують room.

Room є зайнятим, якщо знайдено allocation зі status `HELD` або `CONFIRMED`, для якого:

```text
existing.check_in < requested.check_out
AND existing.check_out > requested.check_in
```

У Phase 4 availability check і `INSERT HELD` виконуються в одній explicit write transaction з `BEGIN IMMEDIATE`; бізнес-конфлікт або exception спричиняє rollback. Connection має 5-second SQLite timeout і `busy_timeout=5000`, тому короткий concurrent writer дочікується commit, а потім бачить актуальний allocation state. Confirm і release також виконуються під `BEGIN IMMEDIATE`.

`booking_id` є idempotency key: ідентичний retry для `HELD`/`CONFIRMED` повертає існуючий запис, а інший Room/dates дає conflict. `RELEASED` є terminal для цього `booking_id`; новий booking ID може знову hold-ити звільнені dates. `expires_at` залишається `NULL`; automatic expiration, worker або cleanup не реалізовані.

## `bookings.db`

**Owner:** Booking Service.

### `bookings`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор бронювання |
| `user_id` | `INTEGER NOT NULL` | Логічне посилання на User Service |
| `hotel_id` | `INTEGER NOT NULL` | ID готелю на момент бронювання |
| `hotel_name` | `TEXT NOT NULL` | Snapshot назви готелю |
| `room_id` | `INTEGER NOT NULL` | Логічне посилання на Room Service |
| `room_number` | `TEXT NOT NULL` | Snapshot номера кімнати |
| `room_type` | `TEXT NOT NULL` | Snapshot типу кімнати |
| `check_in` | `TEXT NOT NULL` | ISO `YYYY-MM-DD`, дата заїзду |
| `check_out` | `TEXT NOT NULL` | ISO `YYYY-MM-DD`, дата виїзду |
| `nights` | `INTEGER NOT NULL` | `check_out - check_in`, більше нуля |
| `price_per_night` | `REAL NOT NULL` | Snapshot ціни за ніч; розрахунок виконується через Decimal |
| `total_amount` | `REAL NOT NULL` | Server-calculated `nights * price_per_night` |
| `status` | `TEXT NOT NULL` | `PENDING`, `CONFIRMED`, `PAYMENT_FAILED`, `CANCELLED` |
| `payment_id` | `INTEGER NULL` | ID фактично створеного Payment (`PAID` або definitive `FAILED`); `NULL`, якщо результат недоступний |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC час створення |
| `updated_at` | `TEXT NOT NULL` | ISO 8601 UTC час останнього переходу status |

Реалізовані constraints для positive external IDs/amounts, non-empty snapshot, `check_in < check_out`, `nights > 0`, canonical status і nullable positive `payment_id`. Phase 7 атомарно виконує локальні переходи `PENDING → CONFIRMED`, `PENDING → PAYMENT_FAILED` та `CONFIRMED → CANCELLED`; definite HOLD conflict видаляє тимчасовий `PENDING`. Якщо remote compensation не підтверджена, `PENDING` навмисно зберігається як unresolved marker. Index `(user_id, created_at)` підтримує історію користувача; `(room_id, check_in, check_out)` корисний для аудиту, але не є source of truth availability. Cross-service foreign keys і копії чужих таблиць відсутні.

`hotel_name`, `room_number`, `room_type`, `price_per_night` — незмінний історичний snapshot. Якщо каталог пізніше зміниться, старе бронювання відображає умови покупки. Snapshot не замінює дані Hotel/Room Service і не використовується для перевірки їх актуального стану.

## `payments.db`

**Owner:** Payment Service.

### `payments`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор payment |
| `booking_id` | `INTEGER NOT NULL UNIQUE` | Idempotency key: один payment на booking |
| `user_id` | `INTEGER NOT NULL` | Ідентифікатор платника |
| `amount` | `REAL NOT NULL` | Сума, більше нуля; API повертає JSON number |
| `currency` | `TEXT NOT NULL` | Наприклад, `UAH` |
| `method` | `TEXT NOT NULL` | Для demo — `CARD` |
| `status` | `TEXT NOT NULL` | `PENDING`, `PAID`, `FAILED`, `REFUNDED` |
| `transaction_ref` | `TEXT NULL` | Референс симульованої транзакції |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC час створення |
| `refunded_at` | `TEXT NULL` | ISO 8601 UTC час першого успішного refund |

Constraints: positive IDs/amount, non-empty currency/method, `UNIQUE(booking_id)` і status check. Unique index за `booking_id` є механізмом захисту від double charging навіть за конкурентних повторів. Повторний create повертає той самий запис; повторний refund не змінює `refunded_at` і повертає стан `REFUNDED`.

## `notifications.db`

**Owner:** Notification Service.

### `notifications`

| Поле | Тип і constraints | Призначення |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Ідентифікатор notification |
| `user_id` | `INTEGER NOT NULL` | Логічний ID отримувача |
| `booking_id` | `INTEGER NULL` | Логічний ID пов’язаного booking |
| `type` | `TEXT NOT NULL` | `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`, `PAYMENT_FAILED` |
| `channel` | `TEXT NOT NULL` | У scope — `EMAIL` |
| `recipient` | `TEXT NOT NULL` | Адреса отримувача, передана caller-ом |
| `subject` | `TEXT NOT NULL` | Тема |
| `message` | `TEXT NOT NULL` | Тіло повідомлення |
| `status` | `TEXT NOT NULL` | `SENT` |
| `is_read` | `BOOLEAN NOT NULL DEFAULT FALSE` | Ознака прочитання |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC час створення |

Реалізовані check constraints для positive IDs, type/channel/status і non-empty text та indexes `(user_id, created_at)` і `(booking_id)`. Ці IDs не є foreign keys до чужих DB. Notification Service зберігає передані snapshot-дані й не читає User або Booking DB.
