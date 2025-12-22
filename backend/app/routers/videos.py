"""
Video upload and management endpoints.

Supports both authenticated (user-specific) and public (legacy) access.
"""

import os
import uuid
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form, Depends
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models import (
    VideoUploadResponse, 
    VideoListResponse, 
    VideoListItem,
    JobStatus
)
from app.services.storage import StorageService
from app.services.job_manager import JobManager
from app.middleware.auth import get_current_user_optional, AuthenticatedUser


router = APIRouter()
settings = get_settings()


@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    script: Optional[UploadFile] = File(None),
    tags: Optional[str] = None,
    target_duration_minutes: Optional[float] = Form(None),
    character_guide: Optional[str] = Form(None),
    enable_scene_matcher: Optional[str] = Form(None),  # Changed to str - FastAPI Form sends strings
    enable_copyright_protection: Optional[str] = Form(None),  # Copyright protection toggle
    series_id: Optional[str] = Form(None),  # Series ID for character persistence
    user: Optional[AuthenticatedUser] = Depends(get_current_user_optional)
):
    # ========== SUBSCRIPTION VALIDATION ==========
    # If user is authenticated, validate their subscription and quota
    if user:
        # Check if user has remaining quota (subscription minutes OR top-ups).
        if not user.has_quota:
            # If they have no minutes at all, treat as payment required.
            error_type = "payment_required" if user.minutes_limit <= 0 and user.minutes_remaining <= 0 else "quota_exceeded"
            message = (
                "You need minutes to process videos. Please buy minutes or subscribe."
                if error_type == "payment_required"
                else f"You've used all {user.minutes_limit} minutes for this billing period. Purchase a top-up or wait for your quota to reset."
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error": error_type,
                    "message": message,
                    "plan_tier": user.plan_tier,
                    "minutes_used": user.minutes_used,
                    "minutes_limit": user.minutes_limit,
                    "minutes_remaining": user.minutes_remaining,
                }
            )
        
        print(f"✅ User {user.id} quota check passed: {user.minutes_remaining:.1f} min remaining (plan: {user.plan_tier})", flush=True)
    
    # Parse enable_scene_matcher from string to bool
    # Form data sends "true" as string, not boolean
    enable_scene_matcher_bool = False
    if enable_scene_matcher:
        enable_scene_matcher_bool = str(enable_scene_matcher).lower() in ('true', '1', 'yes', 'on')
    
    # Parse enable_copyright_protection from string to bool
    enable_copyright_protection_bool = False
    if enable_copyright_protection:
        enable_copyright_protection_bool = str(enable_copyright_protection).lower() in ('true', '1', 'yes', 'on')
    
    # Clean up series_id (strip whitespace, lowercase, make None if empty)
    if series_id:
        series_id = series_id.strip().lower()
        if not series_id:
            series_id = None
    
    """
    Upload a video file for processing.
    
    The video will be stored and a processing job will be queued.
    Optionally upload a narration script for the "Anchor Method" -
    the AI will sync your script to the video instead of generating new content.
    
    Args:
        file: Video file to upload
        script: Optional narration script (.txt or .md file)
        tags: Optional comma-separated tags
        target_duration_minutes: Optional target duration for final recap (allows ~10% over)
        character_guide: Optional character name mapping to replace generic descriptions
            Example: "Woman with powers = The Ancient One\nSkeptical man = Doctor Strange"
        
    Returns:
        Upload response with job ID and video ID
    """
    # Validate file type - check MIME type OR file extension
    # Some video formats may not be recognized by the browser's MIME detection
    VIDEO_EXTENSIONS = {
        ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", 
        ".m4v", ".mpeg", ".mpg", ".3gp", ".ts", ".mts", ".m2ts"
    }
    
    filename = (file.filename or "").lower()
    file_ext = os.path.splitext(filename)[1] if filename else ""
    
    is_video_mime = file.content_type and (
        file.content_type.startswith("video/") or 
        file.content_type == "application/octet-stream"  # Some browsers send this
    )
    is_video_ext = file_ext in VIDEO_EXTENSIONS
    
    if not is_video_mime and not is_video_ext:
        raise HTTPException(
            status_code=400,
            detail=f"File must be a video. Got content_type='{file.content_type}', extension='{file_ext}'"
        )
    
    # Validate script file type if provided
    if script:
        script_ext = (script.filename or "").lower().split(".")[-1]
        if script_ext not in ["txt", "md", "text"]:
            raise HTTPException(
                status_code=400,
                detail="Script must be a text file (.txt or .md)"
            )
    
    # Generate unique video ID
    video_id = f"{uuid.uuid4()}.mp4"
    
    # Save to temp file first
    temp_path = os.path.join(settings.temp_dir, video_id)
    os.makedirs(settings.temp_dir, exist_ok=True)
    
    try:
        # Write uploaded file to temp
        with open(temp_path, "wb") as video_file:
            content = await file.read()
            video_file.write(content)
        
        # Upload to MinIO
        try:
            storage = StorageService()
            storage.upload_video(video_id, temp_path)
        except Exception as storage_err:
            raise HTTPException(status_code=500, detail=f"Failed to upload video to storage: {str(storage_err)}")
        
        # Create processing job
        try:
            job_manager = JobManager()
            job_id = job_manager.create_job(
                video_id, 
                file.filename or "video.mp4",
                target_duration_minutes=target_duration_minutes,
                character_guide=character_guide,
                enable_scene_matcher=enable_scene_matcher_bool,
                enable_copyright_protection=enable_copyright_protection_bool,
                series_id=series_id,
                user_id=user.id if user else None,
                plan_tier=user.plan_tier if user else "none",
                is_priority=user.is_priority if user else False
            )
            
            if series_id:
                print(f"📚 Job {job_id} linked to series '{series_id}' for character persistence", flush=True)
            if user:
                priority_label = "PRIORITY" if user.is_priority else "standard"
                print(f"👤 Job {job_id} created by user '{user.id}' (plan: {user.plan_tier}, queue: {priority_label})", flush=True)
        except Exception as job_err:
            raise HTTPException(status_code=500, detail=f"Failed to create processing job: {str(job_err)}")
        
        # Upload script if provided
        has_script = False
        if script:
            try:
                script_content = await script.read()
                script_object_name = f"{job_id}/script.txt"
                storage.upload_script(script_object_name, script_content)
                has_script = True
                
                # Update job with script info
                job_manager.update_job(job_id, has_script=True)
                print(f"📜 Script uploaded for job {job_id} ({len(script_content)} bytes)", flush=True)
            except Exception as script_err:
                print(f"⚠️ Script upload failed (non-critical): {script_err}", flush=True)
                # Continue without script - not critical
        
        message = "Video uploaded successfully. Processing will begin shortly."
        if has_script:
            message = "Video and script uploaded. Using Anchor Method for precise narration sync."
        
        return VideoUploadResponse(
            job_id=job_id,
            video_id=video_id,
            filename=file.filename or "video.mp4",
            status=JobStatus.PENDING,
            message=message
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (already properly formatted)
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        print(f"❌ Upload endpoint error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass  # Best effort cleanup


@router.get("/", response_model=VideoListResponse)
async def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None
):
    """
    List all uploaded videos with their processing status.
    
    Args:
        page: Page number (1-indexed)
        page_size: Number of items per page
        status: Optional status filter
        
    Returns:
        Paginated list of videos
    """
    job_manager = JobManager()
    
    # Convert status string to enum if provided
    status_filter = None
    if status:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}"
            )
    
    jobs = job_manager.list_jobs(status=status_filter, limit=page_size * page)
    
    # Paginate
    start = (page - 1) * page_size
    end = start + page_size
    page_jobs = jobs[start:end]
    
    videos = [
        VideoListItem(
            video_id=job["video_id"],
            filename=job["filename"],
            status=JobStatus(job["status"]),
            created_at=datetime.fromisoformat(job["created_at"]),
            output_url=job.get("output_url")
        )
        for job in page_jobs
    ]
    
    return VideoListResponse(
        videos=videos,
        total=len(jobs),
        page=page,
        page_size=page_size
    )


@router.get("/{video_id}")
async def get_video(video_id: str):
    """
    Get details about a specific video.
    
    Args:
        video_id: The video ID
        
    Returns:
        Video details including processing status
    """
    storage = StorageService()
    
    # Check if video exists
    if not storage.object_exists(settings.minio.bucket_videos, video_id):
        raise HTTPException(
            status_code=404,
            detail="Video not found"
        )
    
    # Get video info
    info = storage.get_object_info(settings.minio.bucket_videos, video_id)
    
    # Get job info
    job_manager = JobManager()
    jobs = job_manager.list_jobs(limit=100)
    
    job_data = None
    for job in jobs:
        if job["video_id"] == video_id:
            job_data = job
            break
    
    return {
        "video_id": video_id,
        "storage_info": info,
        "job": job_data,
        "download_url": storage.get_video_url(video_id) if info else None
    }


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    """
    Delete a video and its associated job.
    
    Args:
        video_id: The video ID to delete
        
    Returns:
        Confirmation message
    """
    storage = StorageService()
    job_manager = JobManager()
    
    # Delete from storage
    try:
        storage.delete_object(settings.minio.bucket_videos, video_id)
    except Exception:
        pass  # May not exist
    
    # Find and delete associated job
    jobs = job_manager.list_jobs(limit=100)
    for job in jobs:
        if job["video_id"] == video_id:
            job_manager.delete_job(job["job_id"])
            
            # Also delete output if exists
            output_name = f"{job['job_id']}/final_recap.mp4"
            try:
                storage.delete_object(settings.minio.bucket_output, output_name)
            except Exception:
                pass
    
    return {"message": "Video deleted successfully"}


@router.get("/{video_id}/download")
async def get_download_url(video_id: str, expires: int = Query(3600, ge=60, le=86400)):
    """
    Get a presigned download URL for a video.
    
    Args:
        video_id: The video ID
        expires: URL validity in seconds (default 1 hour)
        
    Returns:
        Presigned download URL
    """
    storage = StorageService()
    
    if not storage.object_exists(settings.minio.bucket_videos, video_id):
        raise HTTPException(
            status_code=404,
            detail="Video not found"
        )
    
    url = storage.get_video_url(video_id, expires)
    
    return {"download_url": url, "expires_in": expires}

