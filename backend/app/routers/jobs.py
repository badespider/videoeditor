"""
Job status and management endpoints.

Supports both authenticated (user-specific) and public (legacy) access.
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends
import redis
import json

from app.config import get_settings
from app.models import JobStatus, JobProgress, JobResult
from app.services.job_manager import JobManager
from app.middleware.auth import get_current_user_optional, AuthenticatedUser


router = APIRouter()
settings = get_settings()


@router.get("/{job_id}", response_model=JobProgress)
async def get_job_status(
    job_id: str,
    user: Optional[AuthenticatedUser] = Depends(get_current_user_optional)
):
    """
    Get the current status and progress of a job.
    
    If authenticated, verifies the job belongs to the user.
    
    Args:
        job_id: The job ID
        
    Returns:
        Job progress information
    """
    job_manager = JobManager()
    progress = job_manager.get_job_progress(job_id)
    
    if not progress:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    # If user is authenticated, verify ownership
    if user:
        job = job_manager.get_job(job_id)
        if job and job.get("user_id") and job["user_id"] != user.id:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
    
    return progress


@router.get("/{job_id}/result", response_model=JobResult)
async def get_job_result(job_id: str):
    """
    Get the result of a completed job.
    
    Args:
        job_id: The job ID
        
    Returns:
        Job result with output URL and scene data
    """
    job_manager = JobManager()
    result = job_manager.get_job_result(job_id)
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    if result.status not in [JobStatus.COMPLETED, JobStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail="Job is still processing"
        )
    
    return result


@router.get("/", response_model=List[JobProgress])
async def list_jobs(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Optional[AuthenticatedUser] = Depends(get_current_user_optional)
):
    """
    List jobs with optional status filter.
    
    If authenticated, returns only the user's jobs.
    If not authenticated (legacy mode), returns all jobs.
    
    Args:
        status: Optional status filter
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip (for pagination)
        
    Returns:
        List of job progress objects
    """
    job_manager = JobManager()
    
    status_filter = None
    if status:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}"
            )
    
    # Filter by user_id if authenticated
    user_id = user.id if user else None
    jobs = job_manager.list_jobs(status=status_filter, limit=limit, offset=offset, user_id=user_id)
    
    return [
        JobProgress(
            job_id=job["job_id"],
            status=JobStatus(job["status"]),
            progress=job["progress"],
            current_step=job["current_step"],
            total_scenes=job["total_scenes"],
            processed_scenes=job["processed_scenes"],
            error_message=job.get("error_message"),
            created_at=job["created_at"],
            updated_at=job["updated_at"]
        )
        for job in jobs
    ]


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    user: Optional[AuthenticatedUser] = Depends(get_current_user_optional)
):
    """
    Cancel a pending or processing job.
    
    Note: This only marks the job as cancelled. If the worker
    has already started processing, it may complete anyway.
    
    Args:
        job_id: The job ID to cancel
        
    Returns:
        Confirmation message
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    # Verify ownership if authenticated
    if user and job.get("user_id") and job["user_id"] != user.id:
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )
    
    if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel completed or failed job"
        )

    # Atomically fail the job unless it completed between our check and this update.
    applied = job_manager.fail_job_if_not_completed(
        job_id=job_id,
        error_message="Cancelled by user",
        current_step="Failed",
    )

    if not applied:
        # Re-check current state to return a truthful response.
        latest = job_manager.get_job(job_id) or {}
        if latest.get("status") == JobStatus.COMPLETED.value:
            raise HTTPException(status_code=409, detail="Job already completed")
        if latest.get("status") == JobStatus.FAILED.value:
            raise HTTPException(status_code=409, detail="Job already failed")

    return {"message": "Job cancelled", "success": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str):
    """
    Retry a failed job.
    
    Args:
        job_id: The job ID to retry
        
    Returns:
        New job information
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    if job["status"] != JobStatus.FAILED.value:
        raise HTTPException(
            status_code=400,
            detail="Can only retry failed jobs"
        )
    
    # Create a new job for the same video
    new_job_id = job_manager.create_job(job["video_id"], job["filename"])
    
    return {
        "message": "Job queued for retry",
        "new_job_id": new_job_id,
        "old_job_id": job_id
    }


@router.websocket("/{job_id}/ws")
async def job_websocket(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time job progress updates.
    
    Clients can connect to receive live updates as the job progresses.
    
    Args:
        websocket: WebSocket connection
        job_id: The job ID to subscribe to
    """
    await websocket.accept()
    
    job_manager = JobManager()
    
    # Check if job exists
    job = job_manager.get_job(job_id)
    if not job:
        await websocket.close(code=4004, reason="Job not found")
        return
    
    # Send initial state
    await websocket.send_json({
        "type": "initial",
        "data": job
    })
    
    # If job is already complete, close connection
    if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
        await websocket.close(code=1000, reason="Job already complete")
        return
    
    # Subscribe to Redis pubsub for updates
    r = redis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    pubsub.subscribe(f"job_updates:{job_id}")
    
    try:
        while True:
            # Check for Redis messages
            message = pubsub.get_message(timeout=1.0)
            
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json({
                    "type": "update",
                    "data": data
                })
                
                # Close if job is complete
                if data["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                    # Send final result
                    result = job_manager.get_job(job_id)
                    await websocket.send_json({
                        "type": "complete",
                        "data": result
                    })
                    break
            
            # Also check for client disconnect
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
                
    finally:
        pubsub.unsubscribe(f"job_updates:{job_id}")
        pubsub.close()

