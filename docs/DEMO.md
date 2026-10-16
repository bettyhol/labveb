# Демонстрація лабораторної

Це manual defense guide для фінального Phase 8 baseline. Приклади припускають чисті demo-бази, тому створені User, Hotel, rooms і Booking мають IDs `1`, `1`, `1/2`, `1`. Якщо БД уже містять дані, слід підставляти IDs із фактичних responses або запустити automated demo, який завжди використовує actual IDs.

## Передумови

- Docker Desktop із Docker Compose;
- Python 3.12-compatible environment;
- `python -m pip install -r requirements-dev.txt`;
- вільні host ports `8001`–`8006`.

## Автоматизована демонстрація

Після запуску stack виконайте:

```bash
docker compose up --build -d
docker compose ps
python scripts/demo.py
```

`demo.py` перевіряє health 6/6, створює унікальні User/Hotel/two Rooms, availability, successful Booking Saga, Payment/allocation/notifications, очікуваний `409`, cancellation, refund/release, повторну availability та idempotent повтор cancellation. Скрипт використовує actual response IDs, завершується code `0` лише після всіх assertions і є безпечним для повторного запуску на persistent DB.

## 1. Запуск системи

```bash
docker compose up --build
```

В іншому terminal:

```bash
docker compose ps
```

Очікується шість running containers: `user-service`, `hotel-service`, `room-service`, `booking-service`, `payment-service`, `notification-service`. Додатково перевірити `GET /health` на портах `8001`–`8006`; кожен endpoint має повернути `200` і власне ім’я service.

## 2. Swagger

Відкрити й коротко показати:

- <http://localhost:8001/docs> — User Service;
- <http://localhost:8002/docs> — Hotel Service;
- <http://localhost:8003/docs> — Room Service;
- <http://localhost:8004/docs> — Booking Service;
- <http://localhost:8005/docs> — Payment Service;
- <http://localhost:8006/docs> — Notification Service.

Пояснити, що це шість незалежних OpenAPI contracts, а не один монолітний API.

## 3. Створення User

`POST http://localhost:8001/users`

```json
{
  "name": "Maksym",
  "email": "maksym@example.com",
  "phone": "+380991234567"
}
```

Приклад через `curl`:

```bash
curl -i -X POST http://localhost:8001/users -H "Content-Type: application/json" -d '{"name":"Maksym","email":"maksym@example.com","phone":"+380991234567"}'
```

Очікується `201 Created`, `id: 1`, `active: true`.

## 4. Створення Hotel

`POST http://localhost:8002/hotels`

```json
{
  "name": "Kharkiv Palace",
  "city": "Kharkiv",
  "address": "Nezalezhnosti Ave, 2",
  "description": "Five-star hotel",
  "rating": 5
}
```

```bash
curl -i -X POST http://localhost:8002/hotels -H "Content-Type: application/json" -d '{"name":"Kharkiv Palace","city":"Kharkiv","address":"Nezalezhnosti Ave, 2","description":"Five-star hotel","rating":5}'
```

Очікується `201 Created`, `id: 1`, `active: true`.

## 5. Створення rooms

Room 301 — `POST http://localhost:8003/rooms`:

```json
{
  "hotel_id": 1,
  "number": "301",
  "room_type": "DELUXE",
  "capacity": 2,
  "price_per_night": 2500
}
```

Room 302 — той самий endpoint:

```json
{
  "hotel_id": 1,
  "number": "302",
  "room_type": "STANDARD",
  "capacity": 2,
  "price_per_night": 1800
}
```

```bash
curl -i -X POST http://localhost:8003/rooms -H "Content-Type: application/json" -d '{"hotel_id":1,"number":"301","room_type":"DELUXE","capacity":2,"price_per_night":2500}'
curl -i -X POST http://localhost:8003/rooms -H "Content-Type: application/json" -d '{"hotel_id":1,"number":"302","room_type":"STANDARD","capacity":2,"price_per_night":1800}'
```

Очікуються два `201 Created`. Під час кожного create Room Service має перевірити Hotel через HTTP, не через `hotels.db`.

## 6. Початковий availability search

```bash
curl -i "http://localhost:8003/rooms/available?hotel_id=1&check_in=2026-09-20&check_out=2026-09-23&guests=2"
```

Очікується `200 OK` і два rooms — `301` та `302`. Пошук враховує `capacity >= 2` і відсутність overlapping `HELD`/`CONFIRMED` allocations.

## 7. Створення Booking

`POST http://localhost:8004/bookings`

```json
{
  "user_id": 1,
  "room_id": 1,
  "check_in": "2026-09-20",
  "check_out": "2026-09-23"
}
```

```bash
curl -i -X POST http://localhost:8004/bookings -H "Content-Type: application/json" -d '{"user_id":1,"room_id":1,"check_in":"2026-09-20","check_out":"2026-09-23"}'
```

Очікується `201 Created` і Booking:

- `nights: 3`;
- `price_per_night: 2500`;
- `total_amount: 7500`;
- `status: CONFIRMED`;
- snapshot `Kharkiv Palace`, `301`, `DELUXE`;
- непорожній `payment_id`.

Клієнт не передавав суму: Booking Service отримав ціну з Room Service і розрахував `3 × 2500`.

## 8. Перевірка недоступності

Повторити пошук із кроку 6:

```bash
curl -i "http://localhost:8003/rooms/available?hotel_id=1&check_in=2026-09-20&check_out=2026-09-23&guests=2"
```

Очікується лише Room `302`; Room `301` має `CONFIRMED` allocation і більше не доступний для цього періоду.

## 9. Перевірка overlapping booking

```bash
curl -i -X POST http://localhost:8004/bookings -H "Content-Type: application/json" -d '{"user_id":1,"room_id":1,"check_in":"2026-09-21","check_out":"2026-09-22"}'
```

Очікується `409 Conflict`: Room `301` already booked. Це демонструє authoritative overlap check під транзакційним lock, а не довіру до попереднього search result. Booking Service видаляє свій тимчасовий `PENDING`; payment і notification для конфліктного запиту не створюються.

## 10. Перевірка Payment

```bash
curl -i http://localhost:8005/bookings/1/payment
```

Очікується `200 OK`, `status: PAID`, `amount: 7500`, `currency: UAH`. Повторна спроба створення payment із тим самим `booking_id` не повинна створити другий запис або charge.

## 11. Перевірка Notification

```bash
curl -i http://localhost:8006/users/1/notifications
```

Очікується notification із `type: BOOKING_CONFIRMED`, `channel: EMAIL`, `booking_id: 1`. Запис є симуляцією email і одночасно зберігається в `notifications.db`.

## 12. Cancellation

```bash
curl -i -X POST http://localhost:8004/bookings/1/cancel
```

Очікується `200 OK`, Booking зі status `CANCELLED`. Реалізована Saga виконує:

```text
Payment PAID → REFUNDED
Allocation CONFIRMED → RELEASED
Booking CONFIRMED → CANCELLED
Notification BOOKING_CANCELLED
```

Перевірка payment:

```bash
curl -i http://localhost:8005/bookings/1/payment
```

Очікується `status: REFUNDED` і непорожній `refunded_at`.

Перевірка allocation:

```bash
curl -i http://localhost:8003/allocations/1
```

Очікується `status: RELEASED`.

Перевірка notification history:

```bash
curl -i http://localhost:8006/users/1/notifications
```

Очікуються `BOOKING_CONFIRMED` і `BOOKING_CANCELLED`.

## 13. Повторна availability

```bash
curl -i "http://localhost:8003/rooms/available?hotel_id=1&check_in=2026-09-20&check_out=2026-09-23&guests=2"
```

Очікується, що Rooms `301` і `302` знову доступні: `RELEASED` allocation не блокує date range.

## 14. Перевірка idempotent cancellation

Повторити:

```bash
curl -i -X POST http://localhost:8004/bookings/1/cancel
```

Очікується `200 OK`, той самий `CANCELLED` Booking, без другого refund. Значення `refunded_at` у Payment не змінюється.

## 15. Failure policy Phase 7

- Payment transport/5xx failure має лише один idempotent retry з тим самим `booking_id`; після вичерпання retry виконується Room release і повертається controlled `503`.
- Payment `FAILED` не retry-иться: Booking завершується як `PAYMENT_FAILED`, а Room звільняється.
- Якщо Payment вже `PAID`, але Room CONFIRM не вдався, порядок compensation — Payment refund, потім Room release; Booking стає `PAYMENT_FAILED` лише після обох підтверджень.
- Якщо Notification Service недоступний, успішні `CONFIRMED`, `PAYMENT_FAILED` або `CANCELLED` core states не відкочуються.
- Якщо compensating service недоступний, Booking може залишитися `PENDING` як unresolved marker; автоматичного worker/reconciliation у цій лабораторній немає.

## Очікуваний результат автоматичного demo

Успішний запуск містить такі ключові повідомлення (actual IDs будуть іншими на кожному запуску):

```text
[OK] 6/6 services healthy
[OK] User created: #<actual id>
[OK] Hotel created: #<actual id>
[OK] Rooms created: #<actual id> and #<actual id>
[OK] Available rooms before booking: 2
[OK] Booking #<actual id> CONFIRMED; Payment #<actual id>
[OK] Payment #<actual id> PAID - 7500 UAH
[OK] BOOKING_CONFIRMED notification SENT
[OK] Booked Room is no longer available
[OK] Overlapping Booking correctly rejected with 409
[OK] Booking #<actual id> CANCELLED
[OK] Payment #<actual id> REFUNDED
[OK] Room RELEASED and BOOKING_CANCELLED notification SENT
[OK] Released Room is available again
[OK] Repeated cancellation is idempotent
DEMO COMPLETED SUCCESSFULLY
```

Повний JSON навмисно не друкується: для захисту показуються IDs, statuses, amount та результати ключових assertions.

## Що демонструє кожен етап

- User/Hotel/Rooms — незалежні ownership boundaries та Room → Hotel REST validation.
- Availability до/після Booking — Room Service є authoritative owner зайнятості.
- Booking — server-side snapshot, price calculation та Saga orchestration.
- Payment/allocation/notifications — cross-service correlation через `booking_id`.
- Overlapping `409` — authoritative atomic HOLD, а не гарантія попереднього GET.
- Cancellation — `REFUND → RELEASE → CANCELLED` і повернення Room в availability.
- Повторний cancel — idempotent no-op без duplicate refund/notification.

## Troubleshooting

- `[FAIL] ... unavailable`: перевірити `docker compose ps` і `docker compose logs <service-name>`; дочекатися стану healthy.
- Port already in use: звільнити відповідний порт `8001`–`8006` або зупинити інший stack.
- Missing `httpx`: виконати `python -m pip install -r requirements-dev.txt`.
- Потрібен clean state: виконати `docker compose down -v`, а в PowerShell — `Remove-Item -Force data\*.db,data\*.db-shm,data\*.db-wal -ErrorAction SilentlyContinue`; `data/.gitkeep` не видаляється.
- Integration tests: `python -m pytest -q -m integration`; якщо весь stack вимкнений, вони skip, а частково недоступний stack дає failure.

## Що сказати викладачу

- **Чому кожен service має свою DB?** Дані мають одного власника, а сервіси не зв’язуються прихованими SQL joins.
- **Чому Booking Service не читає `rooms.db`?** Room state належить Room Service і доступний лише через його public API.
- **Чому Room Service володіє availability?** Він єдиний зберігає Room та allocations і може атомарно перевірити overlap.
- **Чому GET availability не гарантує Booking?** Між GET і HOLD інший клієнт може зайняти Room; authoritative рішення приймає HOLD.
- **Як захищено double booking?** Overlap check та `INSERT HELD` виконуються в одній `BEGIN IMMEDIATE` transaction.
- **Що таке Saga тут?** Booking Service послідовно координує local transactions через REST без distributed SQL transaction.
- **Що таке compensation?** Це протилежна business operation: release після hold або refund після payment.
- **Навіщо payment idempotency?** Retry з тим самим `booking_id` не створює другий payment/charge після ambiguous timeout.
- **Навіщо refund idempotency?** Partial cancellation можна повторити без double refund і зміни `refunded_at`.
- **Навіщо Booking snapshots?** Історія зберігає hotel/room/price на момент покупки незалежно від майбутніх catalog changes.
- **Чому Notification failure не скасовує Booking?** Notification є secondary effect; Payment, allocation і Booking state є critical.
- **Чому немає однієї distributed SQL transaction?** Шість SQLite DB належать різним автономним services; consistency забезпечує Saga.
- **Що коли compensation service недоступний?** Booking може лишитися unresolved `PENDING`; durable reconciliation свідомо поза laboratory scope.
