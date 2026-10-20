from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import JobStatus


class JobCreate(BaseModel):
    prompt: str
    params: dict[str, Any] | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    prompt: str
    params: dict[str, Any] | None
    status: JobStatus
    result: str | None
    error: str | None
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class JobClaimed(BaseModel):
    id: uuid.UUID
    prompt: str
    params: dict[str, Any] | None

    model_config = {"from_attributes": True}


class JobComplete(BaseModel):
    result: str


class JobFail(BaseModel):
    error: str
