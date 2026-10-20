# Очередь заданий генерации с воркерами

Сервис для постановки заданий в очередь и их выполнения GPU-воркерами.
Построен на **FastAPI + PostgreSQL**, атомарный захват задания через `SELECT … FOR UPDATE SKIP LOCKED`.

## Архитектура

```
Клиент ──► POST /jobs ──► [PostgreSQL: jobs]
                                │
               worker-1 ◄── POST /jobs/claim ──┤
               worker-2 ◄── POST /jobs/claim ──┘
                  │
          POST /jobs/{id}/complete
          POST /jobs/{id}/fail
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/jobs` | Создать задание (`prompt`, `params`) |
| `GET` | `/jobs/{id}` | Получить статус задания |
| `POST` | `/jobs/claim` | Воркер забирает одно задание (нужен токен) |
| `POST` | `/jobs/{id}/complete` | Воркер отмечает выполнение (нужен токен) |
| `POST` | `/jobs/{id}/fail` | Воркер отмечает ошибку (нужен токен) |

### Авторизация воркера

Эндпоинты `claim`, `complete`, `fail` требуют заголовок:

```
Authorization: Bearer <WORKER_TOKEN>
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/jobqueue` | Строка подключения к БД |
| `WORKER_TOKEN` | `secret-worker-token` | Токен авторизации воркеров |
| `STUCK_JOB_TIMEOUT_MINUTES` | `10` | Таймаут зависших заданий (мин.) |
| `API_URL` | `http://api:8000` | URL API для воркера |
| `WORKER_ID` | авто | Идентификатор воркера |
| `POLL_INTERVAL` | `2` | Интервал опроса очереди (сек.) |

## Запуск

```bash
docker compose up --build
```

Поднимутся: PostgreSQL, API-сервер, два воркера.

### Пример использования

```bash
# Создать задание
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Сгенерируй аудио приветствие", "params": {"voice": "ru"}}'

# Проверить статус
curl http://localhost:8000/jobs/<job-id>
```

## Тесты

Тесты используют реальный PostgreSQL (нужен запущенный контейнер):

```bash
# Поднять только БД
docker compose up -d db

# Создать тестовую базу
docker compose exec db psql -U postgres -c "CREATE DATABASE jobqueue_test;"

# Запустить тесты
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/jobqueue_test" \
  pytest tests/ -v
```

## Возврат зависших заданий

Фоновая задача проверяет каждую минуту: если задание в статусе `running` дольше
`STUCK_JOB_TIMEOUT_MINUTES`, оно возвращается в очередь (`queued`).
