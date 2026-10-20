import os


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/jobqueue",
)
DATABASE_URL_SYNC = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg2://postgres:postgres@db:5432/jobqueue",
)
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "secret-worker-token")
STUCK_JOB_TIMEOUT_MINUTES = int(os.getenv("STUCK_JOB_TIMEOUT_MINUTES", "10"))
