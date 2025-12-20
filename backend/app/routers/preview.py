"""
Preview and streaming endpoints.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, RedirectResponse

from app.config import get_settings
from app.models import JobStatus, ScenePreview
from app.services.storage import StorageService
from app.services.job_manager import JobManager


router = APIRouter()
settings = get_settings()


@router.get("/{job_id}/output")
async def get_output_preview(job_id: str):
    """
    Get the final output video URL for a completed job.
    
    Args:
        job_id: The job ID
        
    Returns:
        Direct URL for the output video (bucket is public)
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Job is not completed"
        )
    
    storage = StorageService()
    output_name = f"{job_id}/final_recap.mp4"
    
    if not storage.object_exists(settings.minio.bucket_output, output_name):
        raise HTTPException(
            status_code=404,
            detail="Output file not found"
        )
    
    # Return direct URL (output bucket is public)
    url = f"http://localhost:9000/{settings.minio.bucket_output}/{output_name}"
    return {"url": url}


@router.get("/{job_id}/output/stream")
async def stream_output(job_id: str):
    """
    Stream the output video directly.
    
    Args:
        job_id: The job ID
        
    Returns:
        Redirect to the video stream
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Job is not completed"
        )
    
    storage = StorageService()
    output_name = f"{job_id}/final_recap.mp4"
    
    if not storage.object_exists(settings.minio.bucket_output, output_name):
        raise HTTPException(
            status_code=404,
            detail="Output file not found"
        )
    
    # Get presigned URL and redirect
    url = storage.get_output_url(output_name, expires=3600)
    return RedirectResponse(url=url)


@router.get("/{job_id}/scenes")
async def get_scenes(job_id: str):
    """
    Get all scenes for a job with their details.
    
    Args:
        job_id: The job ID
        
    Returns:
        List of scene information
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    scenes = job.get("scenes", [])
    storage = StorageService()
    
    result = []
    for scene in scenes:
        # Generate thumbnail URL
        thumb_name = f"{job_id}/thumbnails/scene_{scene['index']:04d}.jpg"
        thumb_url = None
        
        try:
            if storage.object_exists(settings.minio.bucket_output, thumb_name):
                thumb_url = storage.get_output_url(thumb_name, expires=3600)
        except Exception:
            pass
        
        result.append({
            "index": scene["index"],
            "start_time": scene["start_time"],
            "end_time": scene["end_time"],
            "duration": scene["duration"],
            "narration": scene.get("narration_text"),
            "thumbnail_url": thumb_url,
            "processed": scene.get("processed", False)
        })
    
    return {"job_id": job_id, "scenes": result}


@router.get("/{job_id}/scenes/{scene_index}")
async def get_scene(job_id: str, scene_index: int):
    """
    Get details for a specific scene.
    
    Args:
        job_id: The job ID
        scene_index: The scene index
        
    Returns:
        Scene details
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    scenes = job.get("scenes", [])
    
    for scene in scenes:
        if scene["index"] == scene_index:
            storage = StorageService()
            
            # Get thumbnail URL
            thumb_name = f"{job_id}/thumbnails/scene_{scene_index:04d}.jpg"
            thumb_url = None
            
            try:
                if storage.object_exists(settings.minio.bucket_output, thumb_name):
                    thumb_url = storage.get_output_url(thumb_name, expires=3600)
            except Exception:
                pass
            
            return {
                **scene,
                "thumbnail_url": thumb_url
            }
    
    raise HTTPException(
        status_code=404,
        detail="Scene not found"
    )


@router.get("/{job_id}/thumbnail")
async def get_job_thumbnail(job_id: str, scene: int = Query(0, ge=0)):
    """
    Get a thumbnail image for the job.
    
    Args:
        job_id: The job ID
        scene: Scene index for thumbnail (default: first scene)
        
    Returns:
        Redirect to thumbnail image
    """
    storage = StorageService()
    thumb_name = f"{job_id}/thumbnails/scene_{scene:04d}.jpg"
    
    if not storage.object_exists(settings.minio.bucket_output, thumb_name):
        raise HTTPException(
            status_code=404,
            detail="Thumbnail not found"
        )
    
    url = storage.get_output_url(thumb_name, expires=3600)
    return RedirectResponse(url=url)


@router.get("/{job_id}/download")
async def download_output(
    job_id: str,
    expires: int = Query(3600, ge=60, le=86400)
):
    """
    Get a download URL for the final output.
    
    Args:
        job_id: The job ID
        expires: URL validity in seconds (unused, bucket is public)
        
    Returns:
        Download URL
    """
    job_manager = JobManager()
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Job is not completed"
        )
    
    storage = StorageService()
    output_name = f"{job_id}/final_recap.mp4"
    
    if not storage.object_exists(settings.minio.bucket_output, output_name):
        raise HTTPException(
            status_code=404,
            detail="Output file not found"
        )
    
    # Direct URL for download (output bucket is public)
    url = f"http://localhost:9000/{settings.minio.bucket_output}/{output_name}"
    
    return {
        "download_url": url,
        "filename": f"recap_{job_id[:8]}.mp4",
        "expires_in": expires
    }

