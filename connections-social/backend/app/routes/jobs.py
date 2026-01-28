"""Job status and management routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.jobs import job_manager, JobStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{job_id}")
def get_job_status(job_id: str):
    """Get the status and progress of a job.

    Args:
        job_id: UUID of the job to check

    Returns:
        Job status including:
        - id: Job UUID
        - type: Job type (e.g., "batch_ingest")
        - status: pending | running | completed | failed | cancelled
        - created_at: ISO timestamp when job was created
        - started_at: ISO timestamp when job started (if running/completed)
        - completed_at: ISO timestamp when job finished (if completed)
        - progress: Current progress (if running)
            - current: Current item number
            - total: Total items
            - percentage: Completion percentage
            - current_item: Name of item being processed
            - items_succeeded: Count of successful items
            - items_failed: Count of failed items
        - result: Final result (if completed)
            - success: Boolean
            - data: Result data
            - error: Error message (if failed)
            - items: Per-item results
        - metadata: Job metadata

    Raises:
        404: Job not found
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return job.to_dict()


@router.get("")
def list_recent_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 10
):
    """List recent jobs.

    Note: This endpoint has limited functionality without Redis SCAN.
    In production, consider using a database for job persistence.

    Args:
        status: Filter by status (pending, running, completed, failed)
        job_type: Filter by job type
        limit: Maximum number of jobs to return

    Returns:
        List of recent jobs (limited to in-memory cache for now)
    """
    # For now, return jobs from local cache
    # In production, this would query Redis with SCAN
    jobs = list(job_manager._local_jobs.values())

    # Filter by status
    if status:
        try:
            status_enum = JobStatus(status)
            jobs = [j for j in jobs if j.status == status_enum]
        except ValueError:
            pass

    # Filter by type
    if job_type:
        jobs = [j for j in jobs if j.type == job_type]

    # Sort by created_at descending
    jobs.sort(key=lambda j: j.created_at, reverse=True)

    # Limit results
    jobs = jobs[:limit]

    return {"jobs": [j.to_dict() for j in jobs]}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a pending or running job.

    Note: This marks the job as cancelled but does not stop
    in-progress processing (thread interruption is not implemented).

    Args:
        job_id: UUID of the job to cancel

    Returns:
        Updated job status

    Raises:
        404: Job not found
        400: Job cannot be cancelled (already completed/failed)
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is already {job.status.value} and cannot be cancelled"
        )

    job = job_manager.update_job_status(job_id, JobStatus.CANCELLED)
    return job.to_dict()
