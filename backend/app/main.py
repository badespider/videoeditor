from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.config import get_settings
from app.services.storage import StorageService
from app.routers import videos, jobs, preview, webhooks, characters

# Try to import script_matching - it requires sentence_transformers which may not be installed
try:
    from app.routers import script_matching
    SCRIPT_MATCHING_AVAILABLE = True
    print("✅ Script matching module loaded (sentence_transformers available)", flush=True)
except ImportError as e:
    SCRIPT_MATCHING_AVAILABLE = False
    print(f"⚠️ Script matching module not available: {e}", flush=True)
    print("   Video processing will work, but script-to-clip matching is disabled.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: Initialize storage buckets
    settings = get_settings()
    storage = StorageService()
    storage_ready = storage.ensure_buckets()
    app.state.storage_ready = bool(storage_ready)
    if storage_ready:
        print("✅ Storage buckets initialized", flush=True)
    else:
        # Common Railway cause: MINIO_ENDPOINT not set and default points to docker host `minio`
        # Keep app running so other endpoints can work; storage-dependent endpoints should fail gracefully.
        print(
            "⚠️ Storage is not ready. Configure MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY (or S3-compatible endpoint).",
            flush=True,
        )
    
    yield
    
    # Shutdown: Cleanup if needed
    print("👋 Shutting down...")


app = FastAPI(
    title="Video Recap AI Pipeline",
    description="Automated video recap generator using AI",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
settings = get_settings()
origins = [o.strip() for o in (settings.app.cors_origins or "").split(",") if o.strip()]
if not origins:
    # Safe defaults for local dev + production frontend.
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "https://app.videorecapai.com",
        "https://www.videorecapai.com",
    ]

# Safety: If CORS_ORIGINS is set incorrectly in production (common misconfig on Railway),
# ensure our official origins are still allowed. This prevents uploads from failing with
# opaque browser "network/CORS error" messages.
#
# We only add *our* domains + local dev, not a wildcard.
if "*" not in origins:
    required_origins = {
        "https://app.videorecapai.com",
        "https://videorecapai.com",
        "https://www.videorecapai.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    }
    origins = sorted(set(origins).union(required_origins))

# Note: Wildcard + credentials is not valid CORS. If user sets '*', disable credentials.
allow_credentials = True
if "*" in origins:
    origins = ["*"]
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(videos.router, prefix="/api/videos", tags=["Videos"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(preview.router, prefix="/api/preview", tags=["Preview"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(characters.router, prefix="/api/characters", tags=["Characters"])

# Only include script_matching if the module is available
if SCRIPT_MATCHING_AVAILABLE:
    app.include_router(script_matching.router, prefix="/api/script-matching", tags=["Script Matching"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Video Recap AI Pipeline",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    settings = get_settings()
    return {
        "status": "healthy",
        "services": {
            "memories_configured": bool(settings.memories.api_key),
            "elevenlabs_configured": bool(settings.elevenlabs.api_key),
            "minio_endpoint": settings.minio.endpoint,
            "storage_ready": bool(getattr(app.state, "storage_ready", False)),
            "redis_url": settings.redis_url,
            "script_matching_available": SCRIPT_MATCHING_AVAILABLE
        }
    }


@app.get("/debug/config")
async def debug_config():
    """Debug endpoint to check configuration (remove in production)."""
    settings = get_settings()
    # Safety: disable in production unless explicitly enabled.
    enable_debug = bool(settings.app.debug) or (os.getenv("ENABLE_DEBUG_ENDPOINT", "").strip().lower() in ("true", "1", "yes"))
    if not enable_debug:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "minio": {
            "endpoint": settings.minio.endpoint,
            "access_key_set": bool(settings.minio.access_key and settings.minio.access_key != "minioadmin"),
            "secret_key_set": bool(settings.minio.secret_key and settings.minio.secret_key != "minioadmin"),
            "bucket_videos": settings.minio.bucket_videos,
            "bucket_audio": settings.minio.bucket_audio,
            "bucket_output": settings.minio.bucket_output,
            "secure": settings.minio.secure,
        },
        "redis": {
            "url": settings.redis_url,
        }
    }
