from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class MemoriesConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.memories.ai"


class GeminiConfig(BaseModel):
    api_key: str = ""
    max_file_size_gb: float = 2.0
    compression_crf: int = 28  # Higher = smaller file
    target_bitrate: str = "2M"


class ElevenLabsConfig(BaseModel):
    api_key: str = ""
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Default Rachel voice
    model_id: str = "eleven_multilingual_v2"
    

class MinioConfig(BaseModel):
    endpoint: str = "minio:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket_videos: str = "videos"
    bucket_audio: str = "audio"
    bucket_output: str = "output"
    secure: bool = False


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    # Allow setting a full URL directly (takes precedence over individual fields)
    full_url: str = ""

    @property
    def url(self) -> str:
        # If full_url is set (e.g., from REDIS_URL env var), use it directly
        if self.full_url:
            return self.full_url
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class CeleryConfig(BaseModel):
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/0"


class StorageConfig(BaseModel):
    temp_storage_path: str = "./temp_storage"
    max_video_size_gb: float = 2.5


class FFmpegConfig(BaseModel):
    threads: int = 4
    video_output_format: str = "mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_bitrate: str = "2M"


class ProcessingConfig(BaseModel):
    scene_detection_threshold: float = 30.0
    max_scene_duration: float = 30.0  # seconds
    min_scene_duration: float = 2.5   # seconds (prevents extreme slow-motion on short clips)
    video_speed_min: float = 0.5      # Minimum speed multiplier
    video_speed_max: float = 2.0      # Maximum speed multiplier
    

class AgentPlanningConfig(BaseModel):
    planning_timeout_seconds: int = 300
    max_storyboard_scenes: int = 50


class AgentRetrievalConfig(BaseModel):
    retrieval_batch_size: int = 10
    clip_cache_size_gb: float = 5.0


class AgentRenderingConfig(BaseModel):
    render_timeout_seconds: int = 1800
    max_concurrent_renders: int = 2


class AgentsConfig(BaseModel):
    planning: AgentPlanningConfig = Field(default_factory=AgentPlanningConfig)
    retrieval: AgentRetrievalConfig = Field(default_factory=AgentRetrievalConfig)
    rendering: AgentRenderingConfig = Field(default_factory=AgentRenderingConfig)


class JwtConfig(BaseModel):
    """
    JWT verification settings for backend.

    Our frontend (NextAuth/Auth.js) typically uses HS256 for signed JWTs.
    """
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


class VectorMatchingConfig(BaseModel):
    """Configuration for vector-based script-to-clip matching."""
    enable_vector_matching: bool = True
    similarity_threshold: float = 0.65
    embedding_model_name: str = "all-MiniLM-L6-v2"  # or "all-mpnet-base-v2" for better quality
    embedding_dimension: int = 384  # 768 for mpnet
    max_script_segment_length: int = 500
    vector_index_name: str = "video_embeddings"
    temporal_coherence_weight: float = 0.15  # Reduced from 0.2 for diversity balance
    semantic_weight: float = 0.25  # Reduced from 0.6 to prevent embedding collapse
    validation_boost: float = 0.15
    
    # Visual validation settings
    enable_visual_validation: bool = True
    validation_fps: float = 1.0  # Default FPS (overridden by adaptive)
    validation_threshold: float = 0.80  # Raised from 0.75 for stricter matching
    progression_weight: float = 0.5  # Weight for action progression
    state_alignment_weight: float = 0.3  # Weight for temporal states
    
    # Enhanced validation settings (Fix 1-5)
    enable_validation_debug: bool = False  # Show detailed mismatch reasons
    state_compatibility_threshold: float = 0.8  # Raised from 0.6 for stricter state matching
    enable_direction_checking: bool = True  # Enable action direction verification
    duration_mismatch_warning_ratio: float = 2.0  # Warn if clip is 2x+ longer than expected
    
    # Fine-grained indexing
    enable_fine_grained_indexing: bool = True
    max_chapter_segment_duration: float = 30.0
    preferred_segment_duration: float = 15.0
    
    # Action boundary detection
    enable_action_boundary_detection: bool = True
    boundary_sample_rate: float = 0.5  # Seconds between samples
    boundary_similarity_threshold: float = 0.7  # Change detection threshold
    
    # Diversity enforcement (prevents clip repetition)
    enable_diversity_penalty: bool = True
    max_segment_reuse: int = 0  # 0 = no reuse allowed
    max_overlap_ratio: float = 0.3  # Max 30% overlap with used segments
    num_temporal_partitions: int = 5  # Divide video into N regions for balanced coverage
    max_clips_per_partition: int = 2  # Max clips from same region
    
    # Rebalanced scoring weights for diversity
    diversity_weight: float = 0.20  # Weight for diversity penalty
    coverage_weight: float = 0.15  # Weight for timeline coverage score
    partition_balance_weight: float = 0.10  # Weight for partition balance boost
    
    # Visual grounding (pre-filter before semantic matching)
    enable_visual_grounding: bool = True
    grounding_score_threshold: float = 0.70  # Increased from 0.65 for stricter matching
    grounding_relaxed_threshold: float = 0.50  # Fallback threshold
    grounding_sample_frames: int = 3  # Frames to analyze per clip
    grounding_weight: float = 0.15  # Reduced from 0.30 (entailment now higher priority)
    grounding_requires_action_binding: bool = True  # NEW: Verify WHO-DOES-WHAT
    
    # Visual Entailment Settings (NEW - highest priority verification)
    # Based on Chen et al. "Explainable Video Entailment with Grounded Visual Evidence" (ICCV 2021)
    enable_visual_entailment: bool = True
    entailment_threshold: float = 0.70  # Minimum confidence for ENTAIL judgment
    entailment_frame_samples: int = 5  # Frames to sample for entailment check
    
    # Rebalanced Weights (entailment prioritized over semantic similarity)
    # Total should sum to ~1.0 for normalized scoring
    weight_entailment: float = 0.35  # NEW: Highest priority - does visual ENTAIL script?
    weight_validation: float = 0.25  # Frame-level visual validation
    weight_grounding: float = 0.15  # Object/action presence check
    weight_semantic: float = 0.10  # REDUCED from 0.25 - embedding similarity alone is insufficient
    weight_temporal: float = 0.10  # Timeline coherence
    weight_coverage: float = 0.05  # Diversity/coverage bonus
    
    def get_validation_fps(self, clip_duration: float) -> float:
        """
        Adaptive FPS based on clip duration to capture actions more accurately.
        
        Args:
            clip_duration: Duration of the clip in seconds
            
        Returns:
            Frames per second to sample for validation
        """
        if clip_duration < 5:
            return 5.0  # Short clips: 5 FPS (0.2s per frame)
        elif clip_duration < 15:
            return 3.0  # Medium clips: 3 FPS (0.33s per frame)
        else:
            return 2.0  # Long clips: 2 FPS (0.5s per frame)


class FeaturesConfig(BaseModel):
    # SceneMatcher Configuration (enabled by default)
    enable_scene_matcher: bool = True
    scene_matcher_confidence_threshold: float = 0.4

    # Copyright Protection Configuration (enabled by default - experimental)
    # Splits clips into <3 second segments with visual transforms for copyright evasion
    # Default ON: pipeline expects this to be enabled for the “protected scenes” stitch path.
    # Can still be disabled via ENABLE_COPYRIGHT_PROTECTION=false if needed.
    enable_copyright_protection: bool = True
    max_clip_duration: float = 2.5  # Max seconds per clip
    transform_intensity: str = "subtle"  # subtle, moderate, aggressive

    # Character Extraction Configuration (enabled by default)
    enable_character_extraction: bool = True

    # Vector Matching / AI-Powered Clip Matching Configuration (enabled by default - experimental)
    vector_matching: VectorMatchingConfig = Field(default_factory=VectorMatchingConfig)


class AppConfig(BaseModel):
    app_name: str = "Agentic Video Editor"
    debug: bool = True
    log_level: str = "info"
    # Comma-separated list of allowed frontend origins for CORS.
    # Example: "https://app.example.com,https://admin.example.com"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


class WebhookConfig(BaseModel):
    base_url: str = ""
    secret: str = ""
    # Optional: override which header to read for webhook signature verification.
    # Example: "X-Memories-Signature"
    signature_header: str = ""


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        env_nested_delimiter="__",
    )

    memories: MemoriesConfig = Field(default_factory=MemoriesConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    elevenlabs: ElevenLabsConfig = Field(default_factory=ElevenLabsConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ffmpeg: FFmpegConfig = Field(default_factory=FFmpegConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    jwt: JwtConfig = Field(default_factory=JwtConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ) -> Tuple[Any, ...]:
        """
        Support BOTH:
        - New nested env vars (e.g., REDIS__HOST) via env_nested_delimiter
        - Existing flat env vars (e.g., REDIS_HOST) via a legacy mapping source

        Priority: init > env > dotenv > legacy > secrets
        """

        def legacy_flat_env_source() -> Dict[str, Any]:
            # We need to support legacy flat keys from BOTH:
            # - real environment variables
            # - the .env file (since pydantic's dotenv loader won't recognize legacy flat
            #   keys for our nested model fields)
            env: Dict[str, str] = {}
            try:
                from dotenv import dotenv_values  # local import to avoid hard dependency at import-time

                env_file = cls.model_config.get("env_file", ".env")
                if env_file:
                    # dotenv_values returns {key: value|None}
                    file_vals = {k: (v or "") for k, v in dotenv_values(env_file).items()}
                    env.update({k: v for k, v in file_vals.items() if k})
            except Exception:
                # If dotenv parsing fails, fall back to environment only.
                pass

            # Environment variables override .env values
            env.update({k: v for k, v in os.environ.items()})

            def get(var: str, default: str = "") -> str:
                v = env.get(var)
                return default if v is None else v

            def get_bool(var: str) -> Any:
                """
                Parse a boolean-like env var value.
                Returns None if missing or unparseable (caller should ignore).
                """
                if env.get(var) is None:
                    return None
                raw = get(var).strip().lower()
                if raw in ("true", "1", "yes", "y", "on"):
                    return True
                if raw in ("false", "0", "no", "n", "off"):
                    return False
                return None

            def get_int(var: str) -> Any:
                if env.get(var) is None:
                    return None
                try:
                    return int(get(var).strip())
                except Exception:
                    return None

            def get_float(var: str) -> Any:
                if env.get(var) is None:
                    return None
                try:
                    return float(get(var).strip())
                except Exception:
                    return None

            out: Dict[str, Any] = {}

            # Helper: set nested path in dict
            def set_path(path: Tuple[str, ...], value: Any) -> None:
                d: Dict[str, Any] = out
                for key in path[:-1]:
                    d = d.setdefault(key, {})
                d[path[-1]] = value

            # Memories.ai (legacy vars)
            if env.get("MEMORIES_AI_API_KEY") is not None:
                set_path(("memories", "api_key"), get("MEMORIES_AI_API_KEY"))
            if env.get("MEMORIES_AI_BASE_URL") is not None:
                set_path(("memories", "base_url"), get("MEMORIES_AI_BASE_URL"))

            # Gemini (legacy vars)
            if env.get("GEMINI_API_KEY") is not None:
                set_path(("gemini", "api_key"), get("GEMINI_API_KEY"))
            if env.get("GEMINI_MAX_FILE_SIZE_GB") is not None:
                set_path(("gemini", "max_file_size_gb"), get("GEMINI_MAX_FILE_SIZE_GB"))
            if env.get("GEMINI_COMPRESSION_CRF") is not None:
                set_path(("gemini", "compression_crf"), get("GEMINI_COMPRESSION_CRF"))
            if env.get("GEMINI_TARGET_BITRATE") is not None:
                set_path(("gemini", "target_bitrate"), get("GEMINI_TARGET_BITRATE"))

            # ElevenLabs (legacy vars)
            if env.get("ELEVENLABS_API_KEY") is not None:
                set_path(("elevenlabs", "api_key"), get("ELEVENLABS_API_KEY"))
            if env.get("ELEVENLABS_VOICE_ID") is not None:
                set_path(("elevenlabs", "voice_id"), get("ELEVENLABS_VOICE_ID"))
            if env.get("ELEVENLABS_MODEL_ID") is not None:
                set_path(("elevenlabs", "model_id"), get("ELEVENLABS_MODEL_ID"))

            # MinIO (legacy vars)
            if env.get("MINIO_ENDPOINT") is not None:
                set_path(("minio", "endpoint"), get("MINIO_ENDPOINT"))
            if env.get("MINIO_ACCESS_KEY") is not None:
                set_path(("minio", "access_key"), get("MINIO_ACCESS_KEY"))
            if env.get("MINIO_SECRET_KEY") is not None:
                set_path(("minio", "secret_key"), get("MINIO_SECRET_KEY"))
            if env.get("MINIO_BUCKET_VIDEOS") is not None:
                set_path(("minio", "bucket_videos"), get("MINIO_BUCKET_VIDEOS"))
            if env.get("MINIO_BUCKET_AUDIO") is not None:
                set_path(("minio", "bucket_audio"), get("MINIO_BUCKET_AUDIO"))
            if env.get("MINIO_BUCKET_OUTPUT") is not None:
                set_path(("minio", "bucket_output"), get("MINIO_BUCKET_OUTPUT"))
            if env.get("MINIO_SECURE") is not None:
                # Convert string to boolean
                secure_val = get("MINIO_SECURE").lower() in ("true", "1", "yes")
                set_path(("minio", "secure"), secure_val)

            # Redis (legacy vars)
            # Support full REDIS_URL (takes precedence)
            if env.get("REDIS_URL") is not None:
                set_path(("redis", "full_url"), get("REDIS_URL"))
            if env.get("REDIS_HOST") is not None:
                set_path(("redis", "host"), get("REDIS_HOST"))
            if env.get("REDIS_PORT") is not None:
                set_path(("redis", "port"), get("REDIS_PORT"))
            if env.get("REDIS_DB") is not None:
                set_path(("redis", "db"), get("REDIS_DB"))
            if env.get("REDIS_PASSWORD") is not None:
                set_path(("redis", "password"), get("REDIS_PASSWORD"))

            # Celery (legacy vars)
            if env.get("CELERY_BROKER_URL") is not None:
                set_path(("celery", "broker_url"), get("CELERY_BROKER_URL"))
            if env.get("CELERY_RESULT_BACKEND") is not None:
                set_path(("celery", "result_backend"), get("CELERY_RESULT_BACKEND"))

            # Storage (legacy vars)
            if env.get("TEMP_STORAGE_PATH") is not None:
                set_path(("storage", "temp_storage_path"), get("TEMP_STORAGE_PATH"))
            if env.get("MAX_VIDEO_SIZE_GB") is not None:
                set_path(("storage", "max_video_size_gb"), get("MAX_VIDEO_SIZE_GB"))

            # FFmpeg (legacy vars)
            if env.get("FFMPEG_THREADS") is not None:
                threads = get_int("FFMPEG_THREADS")
                if threads is not None:
                    set_path(("ffmpeg", "threads"), threads)
            if env.get("VIDEO_OUTPUT_FORMAT") is not None:
                set_path(("ffmpeg", "video_output_format"), get("VIDEO_OUTPUT_FORMAT"))
            if env.get("VIDEO_CODEC") is not None:
                set_path(("ffmpeg", "video_codec"), get("VIDEO_CODEC"))
            if env.get("AUDIO_CODEC") is not None:
                set_path(("ffmpeg", "audio_codec"), get("AUDIO_CODEC"))
            if env.get("VIDEO_BITRATE") is not None:
                set_path(("ffmpeg", "video_bitrate"), get("VIDEO_BITRATE"))

            # Features (legacy vars)
            if env.get("ENABLE_SCENE_MATCHER") is not None:
                val = get_bool("ENABLE_SCENE_MATCHER")
                if val is not None:
                    set_path(("features", "enable_scene_matcher"), val)
            if env.get("SCENE_MATCHER_CONFIDENCE_THRESHOLD") is not None:
                set_path(("features", "scene_matcher_confidence_threshold"), get("SCENE_MATCHER_CONFIDENCE_THRESHOLD"))

            if env.get("ENABLE_COPYRIGHT_PROTECTION") is not None:
                val = get_bool("ENABLE_COPYRIGHT_PROTECTION")
                if val is not None:
                    set_path(("features", "enable_copyright_protection"), val)
            if env.get("MAX_CLIP_DURATION") is not None:
                set_path(("features", "max_clip_duration"), get("MAX_CLIP_DURATION"))
            if env.get("TRANSFORM_INTENSITY") is not None:
                set_path(("features", "transform_intensity"), get("TRANSFORM_INTENSITY"))

            if env.get("ENABLE_CHARACTER_EXTRACTION") is not None:
                val = get_bool("ENABLE_CHARACTER_EXTRACTION")
                if val is not None:
                    set_path(("features", "enable_character_extraction"), val)

            # Agents (legacy vars)
            if env.get("PLANNING_TIMEOUT_SECONDS") is not None:
                v = get_int("PLANNING_TIMEOUT_SECONDS")
                if v is not None:
                    set_path(("agents", "planning", "planning_timeout_seconds"), v)
            if env.get("MAX_STORYBOARD_SCENES") is not None:
                v = get_int("MAX_STORYBOARD_SCENES")
                if v is not None:
                    set_path(("agents", "planning", "max_storyboard_scenes"), v)

            if env.get("RETRIEVAL_BATCH_SIZE") is not None:
                v = get_int("RETRIEVAL_BATCH_SIZE")
                if v is not None:
                    set_path(("agents", "retrieval", "retrieval_batch_size"), v)
            if env.get("CLIP_CACHE_SIZE_GB") is not None:
                v = get_float("CLIP_CACHE_SIZE_GB")
                if v is not None:
                    set_path(("agents", "retrieval", "clip_cache_size_gb"), v)

            if env.get("RENDER_TIMEOUT_SECONDS") is not None:
                v = get_int("RENDER_TIMEOUT_SECONDS")
                if v is not None:
                    set_path(("agents", "rendering", "render_timeout_seconds"), v)
            if env.get("MAX_CONCURRENT_RENDERS") is not None:
                v = get_int("MAX_CONCURRENT_RENDERS")
                if v is not None:
                    set_path(("agents", "rendering", "max_concurrent_renders"), v)

            # JWT (legacy vars)
            if env.get("ALGORITHM") is not None:
                set_path(("jwt", "algorithm"), get("ALGORITHM"))
            if env.get("ACCESS_TOKEN_EXPIRE_MINUTES") is not None:
                v = get_int("ACCESS_TOKEN_EXPIRE_MINUTES")
                if v is not None:
                    set_path(("jwt", "access_token_expire_minutes"), v)

            # App (legacy vars)
            if env.get("APP_NAME") is not None:
                set_path(("app", "app_name"), get("APP_NAME"))
            if env.get("DEBUG") is not None:
                val = get_bool("DEBUG")
                if val is not None:
                    set_path(("app", "debug"), val)
            if env.get("LOG_LEVEL") is not None:
                set_path(("app", "log_level"), get("LOG_LEVEL"))
            if env.get("CORS_ORIGINS") is not None:
                set_path(("app", "cors_origins"), get("CORS_ORIGINS"))

            # Webhook (legacy vars)
            if env.get("WEBHOOK_BASE_URL") is not None:
                set_path(("webhook", "base_url"), get("WEBHOOK_BASE_URL"))
            if env.get("WEBHOOK_SECRET") is not None:
                set_path(("webhook", "secret"), get("WEBHOOK_SECRET"))
            if env.get("WEBHOOK_SIGNATURE_HEADER") is not None:
                set_path(("webhook", "signature_header"), get("WEBHOOK_SIGNATURE_HEADER"))

            return out

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            legacy_flat_env_source,
            file_secret_settings,
        )

    # Convenience computed properties (kept for minimal churn)
    @property
    def redis_url(self) -> str:
        return self.redis.url
    
    @property
    def temp_dir(self) -> str:
        return self.storage.temp_storage_path
    
    @property
    def scenes_dir(self) -> str:
        return f"{self.storage.temp_storage_path}/scenes"
    
    @property
    def audio_dir(self) -> str:
        return f"{self.storage.temp_storage_path}/audio"
    
    @property
    def frames_dir(self) -> str:
        return f"{self.storage.temp_storage_path}/frames"
    
    # Backward compatibility aliases used by existing code paths
    @property
    def memories_api_key(self) -> str:
        return self.memories.api_key
    
    @property
    def memories_base_url(self) -> str:
        return self.memories.base_url


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

