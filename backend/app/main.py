from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings
from app.services.storage import StorageService
from app.routers import videos, jobs, preview, webhooks, characters, script_matching


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: Initialize storage buckets
    settings = get_settings()
    storage = StorageService()
    storage.ensure_buckets()
    print("✅ Storage buckets initialized")
    
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
            "redis_url": settings.redis_url
        }
    }

