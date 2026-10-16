# Архітектурні рішення

Формат кожного запису: рішення, причина та наслідки. Рішення утворюють обов’язкові межі цільового дизайну.

## ADR-001: FastAPI

**Decision.** Кожен із шести сервісів має бути окремим FastAPI application.

**Reason.** FastAPI надає компактний Python API, Pydantic validation та автоматичні OpenAPI/Swagger `/docs`, достатні для навчальної демонстрації.

**Consequences.** Кожен сервіс має окремий процес і контракт. Schema errors можуть використовувати стандартний `422`; бізнес-помилки повинні мати явно визначені status codes.

## ADR-002: SQLite per service

**Decision.** Кожен сервіс володіє окремим SQLite-файлом.

**Reason.** Мета роботи — microservice boundaries і distributed workflow, а не адміністрування складної СУБД.

**Consequences.** Має бути шість DB; cross-database joins і спільні transactions неможливі. Для конкурентного hold Room Service застосовує SQLite transactional locking.

## ADR-003: Синхронний REST через HTTPX

**Decision.** Усі міжсервісні business calls виконуються синхронним REST API через HTTPX.

**Reason.** Виклики легко простежити в коді, логах і Swagger; broker не потрібен для цілей лабораторної.

**Consequences.** Downstream latency і failures впливають на orchestration. Потрібні timeouts, контрольований `503` і compensation після часткового успіху.

## ADR-004: Booking Service як Saga Orchestrator

**Decision.** Booking Service координує create та cancel booking workflows.

**Reason.** Один явний orchestrator робить порядок кроків, переходи status та compensation зрозумілими.

**Consequences.** Booking Service залежить від п’яти сервісів і містить workflow coordination, але не чужу domain logic. Distributed SQL transaction не застосовується.

**Phase 7 state.** Реалізовані successful create, failure compensation і cancellation. HTTP calls не виконуються всередині SQLite transaction. Bounded retry дозволений лише для idempotent Payment create після transport failure; compensation дотримується порядку refund → release, а unresolved partial failure залишається видимим як `PENDING`.

## ADR-005: No shared database

**Decision.** Жоден сервіс не читає й не змінює DB іншого сервісу.

**Reason.** Інакше сервіси були б зв’язаними модулями навколо спільної схеми, а data ownership було б порушено.

**Consequences.** Дані отримуються через REST; IDs між контекстами не мають cross-database foreign keys; можливі тимчасова неузгодженість і необхідність snapshot.

## ADR-006: Симулятор платежів

**Decision.** Payment Service симулює payment і не використовує Stripe, LiqPay, PayPal чи карткові реквізити.

**Reason.** Реальний gateway не потрібний для демонстрації Saga, failure та idempotency.

**Consequences.** `simulate_failure=false` детерміновано створює `PAID`, а `true` — `FAILED`; це поле не зберігається. `booking_id` унікальний, а повторні create/refund не спричиняють double charge/refund і не змінюють первинний результат.

## ADR-007: Симулятор email

**Decision.** Notification Service зберігає повідомлення в DB і може друкувати їх як `[EMAIL]`, без SMTP/provider integration.

**Reason.** Лабораторна демонструє межі сервісів та workflow, а не доставку email.

**Consequences.** `status=SENT` відображає лише симуляцію і не гарантує реальну доставку. Кожний POST створює запис, `[EMAIL]` потрапляє в logs, а історію та read-state можна перевірити через API.

## ADR-008: Docker Compose замість Kubernetes

**Decision.** Локальна orchestration виконується Docker Compose.

**Reason.** Одна команда запускає шість контейнерів і достатня для демонстрації service discovery, ports та environment configuration.

**Consequences.** Кожен сервіс має Dockerfile/build context. `depends_on` не вважається readiness guarantee; готовність перевіряється `/health`.

## ADR-009: Без authentication та authorization

**Decision.** У scope немає users login, roles, JWT або OAuth.

**Reason.** Вони не потрібні для основної теми — distributed booking workflow.

**Consequences.** API не є production-secure і призначений лише для локальної навчальної демонстрації. `user_id` не є authenticated identity.

## ADR-010: Availability за діапазонами дат

**Decision.** Доступність обчислюється за активними `HELD`/`CONFIRMED` allocations та перетином `[check_in, check_out)`, а не полем `available`.

**Reason.** Номер може бути зайнятий в одні дати й вільний в інші; день `check_out` може бути наступним `check_in`.

**Consequences.** Пошук потребує date-range query. Hold виконує check-and-insert атомарно; `RELEASED` allocations не блокують номер.

## ADR-011: Critical core effects і best-effort notification

**Decision.** Room reservation, Payment і локальний Booking state є critical. Notification є secondary side effect для `BOOKING_CONFIRMED`, `PAYMENT_FAILED` та `BOOKING_CANCELLED`.

**Reason.** Недоступність навчального email-симулятора не повинна скасовувати вже узгоджені payment/allocation transitions.

**Consequences.** Notification failure логується з `booking_id` і type, але core response/state зберігається. Гарантована eventual delivery потребувала б outbox/worker або broker і не входить у scope.

## ADR-012: Без durable background reconciliation

**Decision.** Laboratory scope використовує synchronous Saga, bounded retry та явні compensation attempts без outbox, broker або background recovery worker.

**Reason.** Мета — прозоро продемонструвати local transactions, idempotency і межі distributed consistency без додаткової infrastructure.

**Consequences.** При повній недоступності compensating service можливий unresolved `PENDING` marker. Система не заявляє exactly-once delivery, guaranteed distributed rollback або production fault tolerance.

## Non-goals

У цій лабораторній не мають бути реалізовані authentication, authorization, admin roles, JWT, OAuth, real card processing, real email, message broker, Kubernetes, distributed tracing, API Gateway, service mesh, cloud deployment, PostgreSQL, Redis caching або complex frontend. Вони збільшують scope, але не додають необхідної демонстрації decomposition, ownership, Saga, compensation та concurrency control.
