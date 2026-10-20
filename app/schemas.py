import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.models import JobStatus


class JobCreate(BaseModel):
    prompt: str
    params: Optional[Dict[str, Any]] = None


class JobOut(BaseModel):
    id: uuid.UUID
    prompt: str
    params: Optional[Dict[str, Any]]
    status: JobStatus
    result: Optional[str]
    error: Optional[str]
    worker_id: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class JobClaimed(BaseModel):
    id: uuid.UUID
    prompt: str
    params: Optional[Dict[str, Any]]

    model_config = {"from_attributes": True}


class JobComplete(BaseModel):
    result: str


class JobFail(BaseModel):
    error: str
