"""
Script Matching API Routes.

Endpoints for script-to-clip matching functionality.
"""

from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from app.config import get_settings
from app.services.video_indexer import VideoIndexer
from app.services.script_processor import ScriptProcessor
from app.services.clip_matcher import ClipMatcher
from app.services.memories_client import MemoriesAIClient
from app.services.storage import StorageService
from app.services.job_manager import JobManager


router = APIRouter()

settings = get_settings()


class IndexResponse(BaseModel):
    """Response for video indexing."""
    video_id: str
    indexed: bool
    scene_count: int


class MatchResponse(BaseModel):
    """Response for script matching."""
    matching_id: str
    matches: List[Dict]
    confidence_scores: List[float]


class AdjustMatchRequest(BaseModel):
    """Request to adjust a match."""
    segment_index: int
    new_clip: Dict


@router.post("/{video_id}/index", response_model=IndexResponse)
async def index_video(video_id: str):
    """
    Trigger video indexing (create embeddings).
    
    Args:
        video_id: Video identifier (Memories.ai video_no)
        
    Returns:
        Indexing status
    """
    try:
        video_indexer = VideoIndexer()
        
        # Check if already indexed
        is_indexed = await video_indexer.is_indexed(video_id)
        
        if is_indexed:
            embeddings = await video_indexer.get_video_embeddings(video_id)
            return IndexResponse(
                video_id=video_id,
                indexed=True,
                scene_count=len(embeddings)
            )
        
        # Index the video
        embeddings = await video_indexer.index_video(video_id)
        
        return IndexResponse(
            video_id=video_id,
            indexed=True,
            scene_count=len(embeddings)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")


@router.post("/{video_id}/match", response_model=MatchResponse)
async def match_script(
    video_id: str,
    script: str = Form(...),
    audio_file: Optional[UploadFile] = File(None)
):
    """
    Upload script and get matches.
    
    Args:
        video_id: Video identifier
        script: Script text
        audio_file: Optional audio file for timing alignment
        
    Returns:
        Matching results
    """
    try:
        # Process script
        script_processor = ScriptProcessor()
        
        # Save audio file temporarily if provided
        audio_path = None
        if audio_file:
            storage = StorageService()
            audio_path = f"{storage.temp_dir}/script_audio_{video_id}.mp3"
            with open(audio_path, "wb") as f:
                content = await audio_file.read()
                f.write(content)
        
        script_segments = await script_processor.process_script(script, audio_path)
        
        if not script_segments:
            raise HTTPException(status_code=400, detail="No script segments generated")
        
        # Get video embeddings
        video_indexer = VideoIndexer()
        is_indexed = await video_indexer.is_indexed(video_id)
        
        if not is_indexed:
            # Index video first
            await video_indexer.index_video(video_id)
        
        # Match clips
        clip_matcher = ClipMatcher()
        matches = await clip_matcher.match_script_to_clips(
            script_segments,
            video_id
        )
        
        # Generate matching ID (simple hash or UUID)
        import hashlib
        matching_id = hashlib.md5(f"{video_id}:{script}".encode()).hexdigest()[:16]
        
        # Store matching results (simplified - in production, use proper storage)
        # For now, we'll return directly
        
        return MatchResponse(
            matching_id=matching_id,
            matches=[
                {
                    "segment": {
                        "text": m["script_segment"]["text"],
                        "index": m["script_segment"]["segment_id"]
                    },
                    "matched_clip": {
                        "start_time": m["matched_clip"]["start_time"] if m["matched_clip"] else 0,
                        "end_time": m["matched_clip"]["end_time"] if m["matched_clip"] else 0,
                        "confidence": m["confidence"]
                    },
                    "alternatives": [
                        {
                            "start_time": alt["start_time"],
                            "end_time": alt["end_time"],
                            "confidence": alt.get("similarity_score", 0)
                        }
                        for alt in m["alternatives"]
                    ]
                }
                for m in matches
            ],
            confidence_scores=[m["confidence"] for m in matches]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Matching failed: {str(e)}")


@router.get("/{matching_id}/preview")
async def preview_matches(matching_id: str):
    """
    Get preview of matched clips with alternatives.
    
    Args:
        matching_id: Matching identifier
        
    Returns:
        Preview data (simplified - in production, retrieve from storage)
    """
    # TODO: Implement proper storage/retrieval of matching results
    raise HTTPException(status_code=501, detail="Preview endpoint not yet implemented")


@router.post("/{matching_id}/adjust")
async def adjust_match(matching_id: str, request: AdjustMatchRequest):
    """
    Manually adjust a clip match.
    
    Args:
        matching_id: Matching identifier
        request: Adjustment request
        
    Returns:
        Updated match
    """
    # TODO: Implement proper storage/update of matching results
    raise HTTPException(status_code=501, detail="Adjust endpoint not yet implemented")


@router.post("/{matching_id}/generate")
async def generate_final_video(matching_id: str):
    """
    Generate final video with matched clips.
    
    Args:
        matching_id: Matching identifier
        
    Returns:
        Job ID for video generation
    """
    # TODO: Implement video generation from matches
    raise HTTPException(status_code=501, detail="Generate endpoint not yet implemented")

