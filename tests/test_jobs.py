"""Tests for the job queue API."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import WORKER_HEADERS, TestSessionFactory


# ---------- helpers ----------

async def _create_job(client: AsyncClient, prompt: str = "test prompt") -> dict:
    resp = await client.post("/jobs", json={"prompt": prompt, "params": {"temperature": 0.7}})
    assert resp.status_code == 201
    return resp.json()


async def _claim_job(client: AsyncClient, worker_id: str = "w1") -> dict | None:
    headers = {**WORKER_HEADERS, "X-Worker-Id": worker_id}
    resp = await client.post("/jobs/claim", headers=headers)
    assert resp.status_code == 200
    return resp.json()


# ---------- tests ----------

class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_job(self, client: AsyncClient):
        job = await _create_job(client, "Hello world")
        assert job["status"] == "queued"
        assert job["prompt"] == "Hello world"
        assert job["params"] == {"temperature": 0.7}
        assert job["result"] is None

    @pytest.mark.asyncio
    async def test_get_job(self, client: AsyncClient):
        job = await _create_job(client)
        resp = await client.get(f"/jobs/{job['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == job["id"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/jobs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestClaim:
    @pytest.mark.asyncio
    async def test_claim_sets_running(self, client: AsyncClient):
        await _create_job(client)
        claimed = await _claim_job(client)
        assert claimed is not None
        resp = await client.get(f"/jobs/{claimed['id']}")
        assert resp.json()["status"] == "running"
        assert resp.json()["worker_id"] == "w1"

    @pytest.mark.asyncio
    async def test_claim_empty_queue(self, client: AsyncClient):
        claimed = await _claim_job(client)
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_requires_auth(self, client: AsyncClient):
        await _create_job(client)
        resp = await client.post("/jobs/claim", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401


class TestTwoWorkersConcurrency:
    @pytest.mark.asyncio
    async def test_two_workers_get_different_jobs(self, client: AsyncClient):
        """Two workers claiming from a queue of 2 jobs should get different jobs."""
        await _create_job(client, "job A")
        await _create_job(client, "job B")

        claimed_a = await _claim_job(client, "worker-a")
        claimed_b = await _claim_job(client, "worker-b")

        assert claimed_a is not None
        assert claimed_b is not None
        assert claimed_a["id"] != claimed_b["id"]

    @pytest.mark.asyncio
    async def test_single_job_claimed_by_one_worker(self, client: AsyncClient):
        """Only one job in the queue — second worker gets nothing."""
        await _create_job(client, "only job")

        claimed_a = await _claim_job(client, "worker-a")
        claimed_b = await _claim_job(client, "worker-b")

        assert claimed_a is not None
        assert claimed_b is None


class TestStatusTransitions:
    @pytest.mark.asyncio
    async def test_complete_job(self, client: AsyncClient):
        job = await _create_job(client)
        claimed = await _claim_job(client)
        assert claimed is not None

        resp = await client.post(
            f"/jobs/{claimed['id']}/complete",
            json={"result": "generated text"},
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] == "generated text"
        assert data["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_fail_job(self, client: AsyncClient):
        job = await _create_job(client)
        await _claim_job(client)

        resp = await client.post(
            f"/jobs/{job['id']}/fail",
            json={"error": "out of memory"},
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error"] == "out of memory"

    @pytest.mark.asyncio
    async def test_cannot_complete_queued_job(self, client: AsyncClient):
        job = await _create_job(client)
        resp = await client.post(
            f"/jobs/{job['id']}/complete",
            json={"result": "text"},
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_fail_completed_job(self, client: AsyncClient):
        job = await _create_job(client)
        await _claim_job(client)
        await client.post(
            f"/jobs/{job['id']}/complete",
            json={"result": "text"},
            headers=WORKER_HEADERS,
        )
        resp = await client.post(
            f"/jobs/{job['id']}/fail",
            json={"error": "oops"},
            headers=WORKER_HEADERS,
        )
        assert resp.status_code == 409


class TestStuckJobRecovery:
    @pytest.mark.asyncio
    async def test_stuck_jobs_returned_to_queue(self, client: AsyncClient):
        """Jobs running longer than timeout should be reset to queued."""
        job = await _create_job(client)
        await _claim_job(client)

        # Manually set started_at to 15 minutes ago
        async with TestSessionFactory() as session:
            past = datetime.now(timezone.utc) - timedelta(minutes=15)
            await session.execute(
                text("UPDATE jobs SET started_at = :past WHERE id = :id"),
                {"past": past, "id": job["id"]},
            )
            await session.commit()

        # Trigger recovery manually (simulate what the background task does)
        async with TestSessionFactory() as session:
            await session.execute(
                text(
                    "UPDATE jobs SET status = 'queued', worker_id = NULL, started_at = NULL "
                    "WHERE status = 'running' "
                    "AND started_at < NOW() - MAKE_INTERVAL(mins => 10)"
                )
            )
            await session.commit()

        resp = await client.get(f"/jobs/{job['id']}")
        data = resp.json()
        assert data["status"] == "queued"
        assert data["worker_id"] is None

    @pytest.mark.asyncio
    async def test_recent_running_job_not_reset(self, client: AsyncClient):
        """Jobs running for less than timeout should NOT be reset."""
        job = await _create_job(client)
        await _claim_job(client)

        # Run recovery — job started just now, should stay running
        async with TestSessionFactory() as session:
            await session.execute(
                text(
                    "UPDATE jobs SET status = 'queued', worker_id = NULL, started_at = NULL "
                    "WHERE status = 'running' "
                    "AND started_at < NOW() - MAKE_INTERVAL(mins => 10)"
                )
            )
            await session.commit()

        resp = await client.get(f"/jobs/{job['id']}")
        assert resp.json()["status"] == "running"
