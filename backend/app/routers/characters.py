"""
Character management API endpoints.

Provides CRUD operations for managing characters in a series.
Characters are stored in Redis and persist across video processing jobs.
"""

import uuid
from typing import List
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.models import (
    CharacterCreateRequest,
    CharacterUpdateRequest,
    CharacterResponse,
    CharacterListResponse,
    SeriesInfo,
    SeriesListResponse,
    SeriesStatsResponse,
    CharacterInfo
)
from app.services.character_database import CharacterDatabase


router = APIRouter()


def character_to_response(char: CharacterInfo) -> CharacterResponse:
    """Convert CharacterInfo dataclass to CharacterResponse Pydantic model."""
    return CharacterResponse(
        id=char.id,
        name=char.name,
        aliases=char.aliases or [],
        description=char.description or "",
        role=char.role or "supporting",
        visual_traits=char.visual_traits or [],
        confidence=char.confidence,
        first_appearance=char.first_appearance,
        source_video_no=char.source_video_no or ""
    )


@router.get("/series", response_model=SeriesListResponse)
async def list_series():
    """
    List all series with saved characters.
    
    Returns:
        List of series IDs with character counts
    """
    char_db = CharacterDatabase()
    series_ids = char_db.list_series()
    
    series_list = []
    for series_id in series_ids:
        stats = char_db.get_series_stats(series_id)
        series_list.append(SeriesInfo(
            series_id=series_id,
            character_count=stats.get("character_count", 0),
            last_updated=stats.get("last_updated")
        ))
    
    return SeriesListResponse(
        series=series_list,
        count=len(series_list)
    )


@router.get("/series/{series_id}", response_model=CharacterListResponse)
async def get_series_characters(series_id: str):
    """
    Get all characters for a series.
    
    Args:
        series_id: The series identifier
        
    Returns:
        List of characters in the series
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    characters = char_db.get_series_characters(series_id)
    
    return CharacterListResponse(
        series_id=series_id,
        characters=[character_to_response(c) for c in characters],
        count=len(characters)
    )


@router.get("/series/{series_id}/stats", response_model=SeriesStatsResponse)
async def get_series_stats(series_id: str):
    """
    Get detailed statistics for a series.
    
    Args:
        series_id: The series identifier
        
    Returns:
        Character count, speaker mapping count, last updated, etc.
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    stats = char_db.get_series_stats(series_id)
    
    if not stats:
        return SeriesStatsResponse(
            series_id=series_id,
            character_count=0,
            speaker_mapping_count=0,
            last_updated=None,
            characters=[]
        )
    
    return SeriesStatsResponse(
        series_id=series_id,
        character_count=stats.get("character_count", 0),
        speaker_mapping_count=stats.get("speaker_mapping_count", 0),
        last_updated=stats.get("last_updated"),
        characters=stats.get("characters", [])
    )


@router.post("/series/{series_id}/characters", response_model=CharacterResponse)
async def add_character(series_id: str, character: CharacterCreateRequest):
    """
    Add a new character to a series.
    
    Manually added characters have 100% confidence.
    
    Args:
        series_id: The series identifier
        character: Character data to create
        
    Returns:
        The created character
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    
    # Validate role
    valid_roles = ["protagonist", "antagonist", "supporting", "minor"]
    role = character.role or "supporting"
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {valid_roles}"
        )
    
    # Create CharacterInfo
    char_info = CharacterInfo(
        id=f"char_manual_{uuid.uuid4().hex[:8]}",
        name=character.name,
        aliases=character.aliases or [],
        description=character.description or "",
        role=role,
        visual_traits=character.visual_traits or [],
        confidence=1.0,  # Manual = high confidence
        first_appearance=0.0,
        appearances=[],
        source_video_no="manual"
    )
    
    # Add to database
    success = char_db.add_character(series_id, char_info)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to add character to database"
        )
    
    return character_to_response(char_info)


@router.put("/series/{series_id}/characters/{char_id}", response_model=CharacterResponse)
async def update_character(
    series_id: str,
    char_id: str,
    updates: CharacterUpdateRequest
):
    """
    Update an existing character.
    
    Use this to correct AI-identified characters.
    
    Args:
        series_id: The series identifier
        char_id: The character ID to update
        updates: Fields to update
        
    Returns:
        The updated character
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    
    # Get existing characters to find the one to update
    characters = char_db.get_series_characters(series_id)
    target_char = None
    for char in characters:
        if char.id == char_id:
            target_char = char
            break
    
    if not target_char:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{char_id}' not found in series '{series_id}'"
        )
    
    # Validate role if provided
    if updates.role:
        valid_roles = ["protagonist", "antagonist", "supporting", "minor"]
        if updates.role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role '{updates.role}'. Must be one of: {valid_roles}"
            )
    
    # Build updates dict (only non-None values)
    update_dict = {}
    if updates.name is not None:
        update_dict["name"] = updates.name
    if updates.aliases is not None:
        update_dict["aliases"] = updates.aliases
    if updates.description is not None:
        update_dict["description"] = updates.description
    if updates.role is not None:
        update_dict["role"] = updates.role
    if updates.visual_traits is not None:
        update_dict["visual_traits"] = updates.visual_traits
    
    if not update_dict:
        # Nothing to update, return current state
        return character_to_response(target_char)
    
    # Apply updates
    success = char_db.update_character(series_id, char_id, update_dict)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to update character"
        )
    
    # Get updated character
    characters = char_db.get_series_characters(series_id)
    for char in characters:
        if char.id == char_id:
            return character_to_response(char)
    
    raise HTTPException(
        status_code=500,
        detail="Character updated but could not retrieve updated data"
    )


@router.delete("/series/{series_id}/characters/{char_id}")
async def delete_character(series_id: str, char_id: str):
    """
    Delete a character from a series.
    
    Args:
        series_id: The series identifier
        char_id: The character ID to delete
        
    Returns:
        Success message
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    
    # Check if character exists
    characters = char_db.get_series_characters(series_id)
    found = any(c.id == char_id for c in characters)
    
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{char_id}' not found in series '{series_id}'"
        )
    
    success = char_db.delete_character(series_id, char_id)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete character"
        )
    
    return {"message": f"Character '{char_id}' deleted successfully"}


@router.delete("/series/{series_id}")
async def clear_series(series_id: str):
    """
    Clear all characters for a series.
    
    Warning: This deletes all character data for the series!
    
    Args:
        series_id: The series identifier
        
    Returns:
        Success message
    """
    # Normalize to lowercase for case-insensitive matching
    series_id = series_id.strip().lower()
    
    char_db = CharacterDatabase()
    
    # Get count before deletion for message
    characters = char_db.get_series_characters(series_id)
    count = len(characters)
    
    success = char_db.clear_series(series_id)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to clear series"
        )
    
    return {
        "message": f"Series '{series_id}' cleared successfully",
        "deleted_characters": count
    }

