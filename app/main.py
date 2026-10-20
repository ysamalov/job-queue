import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import STUCK_JOB_TIMEOUT_MINUTES, WORKER_TOKEN
from app.database import async_session_factory, engine, get_session
from app.models import Base, Job, JobStatus
from app.schemas import JobClaimed, JobComplete, JobCreate, JobFail, JobOut


async def _recover_stuck_jobs() -> None:
    """Background loop: return stuck running jobs back to queued."""
    while True:
        await asyncio.sleep(60)
        try:
            async with async_session_factory() as session:
                stmt = text(
                    "UPDATE jobs SET status = 'queued', worker_id = NULL, started_at = NULL "
                    "WHERE status = 'running' "
                    "AND started_at < NOW() - MAKE_INTERVAL(mins => :timeout)"
                )
                await session.execute(stmt, {"timeout": STUCK_JOB_TIMEOUT_MINUTES})
                await session.commit()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if not os.getenv("TESTING"):
        task = asyncio.create_task(_recover_stuck_jobs())
    else:
        task = None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Job Queue API", lifespan=lifespan)


def verify_worker_token(authorization: str = Header(...)) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid worker token")
    return token


# --------------- Client endpoints ---------------

@app.post("/jobs", response_model=JobOut, status_code=201)
async def create_job(body: JobCreate, session: AsyncSession = Depends(get_session)):
    job = Job(prompt=body.prompt, params=body.params)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@app.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# --------------- Worker endpoints ---------------

@app.post("/jobs/claim", response_model=Optional[JobClaimed])
async def claim_job(
    session: AsyncSession = Depends(get_session),
    _token: str = Depends(verify_worker_token),
    x_worker_id: str = Header("anonymous"),
):
    row = (
        await session.execute(
            text(
                "SELECT id FROM jobs "
                "WHERE status = 'queued' "
                "ORDER BY created_at "
                "LIMIT 1 "
                "FOR UPDATE SKIP LOCKED"
            )
        )
    ).fetchone()

    if row is None:
        return None

    job_id = row[0]
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            "UPDATE jobs SET status = 'running', worker_id = :wid, started_at = :now "
            "WHERE id = :id"
        ),
        {"wid": x_worker_id, "now": now, "id": job_id},
    )
    await session.commit()

    job = await session.get(Job, job_id)
    return job


@app.post("/jobs/{job_id}/complete", response_model=JobOut)
async def complete_job(
    job_id: uuid.UUID,
    body: JobComplete,
    session: AsyncSession = Depends(get_session),
    _token: str = Depends(verify_worker_token),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.running:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, expected running")

    job.status = JobStatus.completed
    job.result = body.result
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(job)
    return job


@app.post("/jobs/{job_id}/fail", response_model=JobOut)
async def fail_job(
    job_id: uuid.UUID,
    body: JobFail,
    session: AsyncSession = Depends(get_session),
    _token: str = Depends(verify_worker_token),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.running:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, expected running")

    job.status = JobStatus.failed
    job.error = body.error
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(job)
    return job
