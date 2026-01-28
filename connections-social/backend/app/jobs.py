"""Async job processing with Redis-backed state management.

Provides background job execution with status tracking for long-running
operations like batch image ingestion.
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import redis

from app.config import REDIS_URL

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobProgress:
    """Progress information for a running job."""
    current: int = 0
    total: int = 0
    percentage: float = 0.0
    current_item: Optional[str] = None
    items_succeeded: int = 0
    items_failed: int = 0


@dataclass
class JobResult:
    """Result information for a completed job."""
    success: bool = True
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None


@dataclass
class Job:
    """Represents an async job."""
    id: str
    type: str
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: Optional[JobProgress] = None
    result: Optional[JobResult] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for JSON serialization."""
        data = {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }
        if self.progress:
            data["progress"] = asdict(self.progress)
        if self.result:
            data["result"] = asdict(self.result)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create job from dictionary."""
        progress = None
        if data.get("progress"):
            progress = JobProgress(**data["progress"])

        result = None
        if data.get("result"):
            result = JobResult(**data["result"])

        return cls(
            id=data["id"],
            type=data["type"],
            status=JobStatus(data["status"]),
            created_at=data["created_at"],
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            progress=progress,
            result=result,
            metadata=data.get("metadata"),
        )


class JobManager:
    """Manages async jobs with Redis-backed persistence.

    Jobs are stored in Redis with automatic expiration (24 hours by default).
    Background threads execute job functions and update progress.
    """

    def __init__(self, redis_url: str = REDIS_URL, job_ttl: int = 86400):
        """Initialize job manager.

        Args:
            redis_url: Redis connection URL
            job_ttl: Time-to-live for job records in seconds (default: 24 hours)
        """
        self.redis_url = redis_url
        self.job_ttl = job_ttl
        self._redis: Optional[redis.Redis] = None
        self._local_jobs: Dict[str, Job] = {}  # Fallback if Redis unavailable

    @property
    def redis_client(self) -> Optional[redis.Redis]:
        """Get Redis client, connecting on first use."""
        if self._redis is None:
            try:
                self._redis = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2
                )
                # Test connection
                self._redis.ping()
                logger.info("Connected to Redis for job management")
            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.warning(f"Redis unavailable, using in-memory storage: {e}")
                self._redis = None
        return self._redis

    def _job_key(self, job_id: str) -> str:
        """Generate Redis key for a job."""
        return f"job:{job_id}"

    def _save_job(self, job: Job) -> None:
        """Save job state to storage."""
        client = self.redis_client
        if client:
            try:
                client.setex(
                    self._job_key(job.id),
                    self.job_ttl,
                    json.dumps(job.to_dict())
                )
                return
            except redis.RedisError as e:
                logger.warning(f"Redis save failed, using memory: {e}")

        # Fallback to memory
        self._local_jobs[job.id] = job

    def _load_job(self, job_id: str) -> Optional[Job]:
        """Load job state from storage."""
        client = self.redis_client
        if client:
            try:
                data = client.get(self._job_key(job_id))
                if data:
                    return Job.from_dict(json.loads(data))
            except redis.RedisError as e:
                logger.warning(f"Redis load failed, checking memory: {e}")

        # Fallback to memory
        return self._local_jobs.get(job_id)

    def create_job(
        self,
        job_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Job:
        """Create a new job record.

        Args:
            job_type: Type/name of the job (e.g., "batch_ingest")
            metadata: Optional metadata to store with job

        Returns:
            Created Job instance
        """
        job = Job(
            id=str(uuid.uuid4()),
            type=job_type,
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )
        self._save_job(job)
        logger.info(f"Created job {job.id} of type {job_type}")
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID.

        Args:
            job_id: Job UUID

        Returns:
            Job instance or None if not found
        """
        return self._load_job(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> Optional[Job]:
        """Update job status.

        Args:
            job_id: Job UUID
            status: New status
            started_at: When job started (ISO format)
            completed_at: When job completed (ISO format)

        Returns:
            Updated Job or None if not found
        """
        job = self._load_job(job_id)
        if not job:
            return None

        job.status = status
        if started_at:
            job.started_at = started_at
        if completed_at:
            job.completed_at = completed_at

        self._save_job(job)
        return job

    def update_job_progress(
        self,
        job_id: str,
        current: int,
        total: int,
        current_item: Optional[str] = None,
        items_succeeded: int = 0,
        items_failed: int = 0,
    ) -> Optional[Job]:
        """Update job progress.

        Args:
            job_id: Job UUID
            current: Current item number
            total: Total items to process
            current_item: Name/ID of current item being processed
            items_succeeded: Number of items successfully processed
            items_failed: Number of items that failed

        Returns:
            Updated Job or None if not found
        """
        job = self._load_job(job_id)
        if not job:
            return None

        percentage = (current / total * 100) if total > 0 else 0

        job.progress = JobProgress(
            current=current,
            total=total,
            percentage=round(percentage, 1),
            current_item=current_item,
            items_succeeded=items_succeeded,
            items_failed=items_failed,
        )

        self._save_job(job)
        return job

    def complete_job(
        self,
        job_id: str,
        success: bool = True,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Job]:
        """Mark job as completed.

        Args:
            job_id: Job UUID
            success: Whether job succeeded
            data: Result data (for successful jobs)
            error: Error message (for failed jobs)
            items: List of item results

        Returns:
            Updated Job or None if not found
        """
        job = self._load_job(job_id)
        if not job:
            return None

        job.status = JobStatus.COMPLETED if success else JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.result = JobResult(
            success=success,
            data=data,
            error=error,
            items=items,
        )

        self._save_job(job)
        logger.info(f"Job {job_id} completed with status {'success' if success else 'failed'}")
        return job

    def run_async(
        self,
        job_id: str,
        func: Callable[[str, "JobManager"], None]
    ) -> None:
        """Run a function asynchronously in a background thread.

        The function receives the job_id and job_manager as arguments
        and is responsible for updating progress and completing the job.

        Args:
            job_id: Job UUID
            func: Function to execute (receives job_id, job_manager)
        """
        def _wrapper():
            try:
                self.update_job_status(
                    job_id,
                    JobStatus.RUNNING,
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                func(job_id, self)
            except Exception as e:
                logger.error(f"Job {job_id} failed with exception: {e}")
                self.complete_job(job_id, success=False, error=str(e))

        thread = threading.Thread(target=_wrapper, daemon=True)
        thread.start()
        logger.info(f"Started background thread for job {job_id}")


# Global job manager instance
job_manager = JobManager()
