# Каталог сервісів

Цей документ визначає межі відповідальності шести реалізованих сервісів. Детальні HTTP-контракти наведено в [API.md](API.md), а схеми сховищ — у [DATABASES.md](DATABASES.md). Phase 8 tooling звертається до них лише через ці public APIs і не є додатковим сервісом.

## Загальні вимоги

Кожен сервіс має бути окремим FastAPI application із власними `Dockerfile`, `requirements.txt`, SQLite database, Swagger `/docs` і `GET /health`. Сервіс виконує SQL лише до власної БД, отримує зовнішні дані через public REST API та повертає зрозумілі HTTP errors без internal traceback.

## User Service

**Відповідальність.** Створення, читання, оновлення користувачів і soft delete через `active=false`.

**Owned data.** `users.db`, таблиця `users`; зокрема унікальність email та active-стан користувача.

**Залежності.** Відсутні.

**Public API responsibility.** CRUD для `/users`, перевірка існування та active-стану користувача для Booking Service.

**Не повинен:** фізично видаляти користувача під час `DELETE`; читати `bookings.db`; керувати бронюваннями, оплатою чи повідомленнями.

## Hotel Service

**Відповідальність.** CRUD готелів, soft delete, фільтрація за city та мінімальним rating.

**Owned data.** `hotels.db`, таблиця `hotels`; назва, адреса, опис, rating та active-стан готелю.

**Залежності.** Відсутні.

**Public API responsibility.** Надати актуальні дані Hotel для клієнта, Booking Service та валідації Room Service.

**Не повинен:** зберігати кімнати; читати `rooms.db`; обчислювати availability або змінювати allocations.

## Room Service

**Відповідальність.** CRUD кімнат, їх характеристики й ціни; пошук availability за діапазоном дат; атомарні hold, confirm і release allocations; захист від double booking.

**Owned data.** `rooms.db`, таблиці `rooms` і `room_allocations`. Це єдине authoritative джерело доступності номера.

**Залежності.** Hotel Service через `HOTEL_SERVICE_URL` — для перевірки існування й active-стану готелю під час створення кімнати, зміни її `hotel_id` та availability search.

**Public API responsibility.** Видавати room data; шукати доступні rooms; створювати `HELD`, переводити його у `CONFIRMED` або `RELEASED`; повертати allocation за `booking_id`.

**Стан Phase 4.** CRUD Room, Hotel validation, availability і allocation API реалізовані. Hold виконує overlap check і `INSERT HELD` в одній `BEGIN IMMEDIATE` transaction; confirm/release також мають локальні transactional state checks. `RELEASED` є terminal, а automatic HELD expiration не реалізовано.

**Не повинен:** відкривати `hotels.db`; зберігати копії Hotel (лише `hotel_id`); використовувати глобальне поле `available`; приймати рішення про payment або booking status.

## Booking Service

**Відповідальність.** Центральний Saga Orchestrator. Валідує учасників бронювання, розраховує кількість ночей і суму, зберігає snapshot, координує hold → payment → confirm/compensation, а також refund → release під час cancellation.

**Owned data.** `bookings.db`, таблиця `bookings`, status і історичні snapshot-поля.

**Залежності.** User, Hotel, Room, Payment і Notification Services; усі base URLs надходять через environment variables.

**Public API responsibility.** Створення й перегляд бронювань, список бронювань користувача, безпечна cancellation.

**Стан Phase 7.** Реалізовані create/read/history API, failure-aware Saga і `POST /bookings/{booking_id}/cancel`. Payment transport failure має один bounded retry з тим самим `booking_id`; definitive `FAILED` не retry-иться. Compensation використовує idempotent Room release та Payment refund. Notification для `BOOKING_CONFIRMED`, `PAYMENT_FAILED` і `BOOKING_CANCELLED` є best-effort та не змінює core result.

**Не повинен:** читати чужі DB; довіряти переданим клієнтом ціні, hotel або `total_amount`; самостійно змінювати allocation/payment/notification records; вважати snapshot актуальним catalog source of truth.

## Payment Service

**Відповідальність.** Детермінована навчальна симуляція payment, зберігання payment state і idempotent refund. Інтеграція зі Stripe, LiqPay або PayPal не передбачається.

**Owned data.** `payments.db`, таблиця `payments`; один payment на `booking_id`, status, transaction reference і час refund.

**Залежності.** Відсутні. Усі потрібні `booking_id`, `user_id`, amount, currency і method отримує в request.

**Public API responsibility.** Створити або повернути існуючий payment, знайти його за payment/booking ID, виконати refund без double refund.

**Стан Phase 5.** API і таблиця `payments` реалізовані. `simulate_failure` детерміновано створює `FAILED`, а звичайний запит — `PAID`; retry не перезаписує первинний результат.

**Не повинен:** читати `bookings.db`; обчислювати вартість номера; змінювати Booking або Room; викликати реальний gateway.

## Notification Service

**Відповідальність.** Симуляція email, збереження notification history, пошук повідомлень і позначення їх прочитаними.

**Owned data.** `notifications.db`, таблиця `notifications`.

**Залежності.** Відсутні. Recipient, subject, message, type та пов’язані IDs передаються у request.

**Public API responsibility.** Створити і зберегти notification, надрукувати симульований `[EMAIL]`, видати список/окремий запис, установити `is_read=true`.

**Стан Phase 5.** API і таблиця `notifications` реалізовані для трьох типів повідомлень та єдиного каналу `EMAIL`. Кожний create створює новий запис; зовнішнього email provider немає.

**Не повинен:** читати `users.db` або `bookings.db`; самостійно шукати email користувача; відправляти реальний email; змінювати стан Booking чи Payment.
