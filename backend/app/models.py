from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field


class JobStatus(str, Enum):
    """Status of a processing job."""
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    DETECTING_SCENES = "detecting_scenes"
    GENERATING_DESCRIPTIONS = "generating_descriptions"
    GENERATING_AUDIO = "generating_audio"
    STITCHING = "stitching"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoStatus(str, Enum):
    """Status of a video in Memories.ai."""
    UNPARSE = "UNPARSE"
    PARSE = "PARSE"
    PARSE_ERROR = "PARSE_ERROR"


class Scene(BaseModel):
    """Represents a detected scene in the video."""
    index: int
    start_time: float  # seconds
    end_time: float    # seconds
    duration: float    # seconds
    video_path: Optional[str] = None
    frame_path: Optional[str] = None
    narration_text: Optional[str] = None
    audio_path: Optional[str] = None
    audio_duration: Optional[float] = None
    processed: bool = False


class VideoUploadRequest(BaseModel):
    """Request model for video upload."""
    callback_url: Optional[str] = None
    tags: Optional[List[str]] = None


class VideoUploadResponse(BaseModel):
    """Response model for video upload."""
    job_id: str
    video_id: str
    filename: str
    status: JobStatus
    message: str


class JobProgress(BaseModel):
    """Progress information for a job."""
    job_id: str
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    current_step: str
    total_scenes: int = 0
    processed_scenes: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobResult(BaseModel):
    """Result of a completed job."""
    job_id: str
    video_id: str
    status: JobStatus
    output_url: Optional[str] = None
    scenes: List[Scene] = []
    duration: float = 0
    error_message: Optional[str] = None


class VideoListItem(BaseModel):
    """Video item in list response."""
    video_id: str
    filename: str
    status: JobStatus
    created_at: datetime
    duration: Optional[float] = None
    output_url: Optional[str] = None


class VideoListResponse(BaseModel):
    """Response for listing videos."""
    videos: List[VideoListItem]
    total: int
    page: int
    page_size: int


class ScenePreview(BaseModel):
    """Preview information for a scene."""
    scene_index: int
    start_time: float
    end_time: float
    thumbnail_url: str
    narration: Optional[str] = None
    audio_url: Optional[str] = None


class MemoriesUploadResponse(BaseModel):
    """Response from Memories.ai upload."""
    video_no: str
    video_name: str
    video_status: str
    upload_time: str


class MemoriesChatResponse(BaseModel):
    """Response from Memories.ai chat."""
    text: str
    video_no: str


# =============================================================================
# Character Extraction Models
# =============================================================================

# --- API Request/Response Models for Character Management ---

class CharacterCreateRequest(BaseModel):
    """Request model for creating a new character."""
    name: str = Field(..., min_length=1, max_length=100)
    aliases: Optional[List[str]] = []
    description: Optional[str] = ""
    role: Optional[str] = "supporting"
    visual_traits: Optional[List[str]] = []


class CharacterUpdateRequest(BaseModel):
    """Request model for updating an existing character."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    aliases: Optional[List[str]] = None
    description: Optional[str] = None
    role: Optional[str] = None
    visual_traits: Optional[List[str]] = None


class CharacterResponse(BaseModel):
    """Response model for a single character."""
    id: str
    name: str
    aliases: List[str] = []
    description: str = ""
    role: str = "supporting"
    visual_traits: List[str] = []
    confidence: float = 0.5
    first_appearance: float = 0.0
    source_video_no: str = ""


class CharacterListResponse(BaseModel):
    """Response model for list of characters."""
    series_id: str
    characters: List[CharacterResponse]
    count: int


class SeriesInfo(BaseModel):
    """Information about a series with characters."""
    series_id: str
    character_count: int
    last_updated: Optional[str] = None


class SeriesListResponse(BaseModel):
    """Response model for list of series."""
    series: List[SeriesInfo]
    count: int


class SeriesStatsResponse(BaseModel):
    """Detailed statistics for a series."""
    series_id: str
    character_count: int
    speaker_mapping_count: int
    last_updated: Optional[str] = None
    characters: List[Dict] = []


# --- Internal Dataclass Models ---

@dataclass
class CharacterAppearance:
    """A character's appearance in a specific video segment."""
    start_time: float
    end_time: float
    confidence: float  # 0-1 how confident we are this is the character
    source: str  # "dialogue", "visual", "ai_inference"


@dataclass
class CharacterInfo:
    """
    Complete character profile extracted from video analysis.
    
    Used by CharacterExtractor to identify and track characters
    across video content for accurate narration.
    """
    id: str  # Unique ID (e.g., "char_abc123")
    name: str  # Primary name (e.g., "Doctor Strange")
    aliases: List[str] = field(default_factory=list)  # Alternative names ["Stephen", "Strange"]
    description: str = ""  # Visual/role description
    role: str = "supporting"  # "protagonist", "antagonist", "supporting", "minor"
    visual_traits: List[str] = field(default_factory=list)  # ["dark hair", "goatee", "red cloak"]
    confidence: float = 0.5  # Overall confidence in this character identification
    first_appearance: float = 0.0  # Timestamp of first appearance in video
    appearances: List[CharacterAppearance] = field(default_factory=list)  # All appearances
    source_video_no: str = ""  # Video where character was identified

