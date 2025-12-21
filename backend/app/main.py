from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.config import get_settings
from app.services.storage import StorageService
from app.routers import videos, jobs, preview, webhooks, characters, script_matching


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
    title="Anime Recap Pipeline",
    description="Automated anime recap video generator using Memories.ai and ElevenLabs",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
settings = get_settings()
origins = [o.strip() for o in (settings.app.cors_origins or "").split(",") if o.strip()]
if not origins:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

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
app.include_router(script_matching.router, prefix="/api/script-matching", tags=["Script Matching"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Anime Recap Pipeline",
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
            "redis_url": settings.redis_url
        }
    }

