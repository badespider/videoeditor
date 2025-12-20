# Anime Recap Pipeline

An automated video recap generator that uses AI to create narrated summaries of anime episodes.

## Architecture

- **FastAPI Backend** - Orchestrates the pipeline (scene detection, Memories.ai, ElevenLabs, FFmpeg)
- **Redis** - Job queue for async video processing
- **MinIO** - S3-compatible object storage for videos and audio
- **React Frontend** - Dashboard for upload, monitoring, and preview

## Features

- Drag-and-drop video upload
- Automatic scene detection using PySceneDetect
- AI-powered scene descriptions via Memories.ai
- Natural narration generation with ElevenLabs
- Video-audio synchronization ("Linear Lock")
- Real-time progress updates via WebSocket
- Scene timeline with thumbnails
- Video preview and download

## Prerequisites

- Docker and Docker Compose
- Memories.ai API key
- ElevenLabs API key

## Quick Start

Your existing `.env` file already has the required configuration! The pipeline uses these variables from your `.env`:

```env
# Already configured in your .env:
MEMORIES_AI_API_KEY=sk-69e29216602ef29bd284a049d85c6e25
MEMORIES_AI_BASE_URL=https://api.memories.ai
ELEVENLABS_API_KEY=sk_54f0169abb7fc4c69a285296fcb8d03775dfd93b6a5b61de

# Redis (already configured)
REDIS_HOST=localhost
REDIS_PORT=6379

# FFmpeg (already configured)
FFMPEG_THREADS=4
VIDEO_CODEC=libx264
AUDIO_CODEC=aac
VIDEO_BITRATE=2M
```

**Start the services:**

```bash
docker-compose up -d
```

**Access the application:**

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- MinIO Console: http://localhost:9001 (admin: minioadmin/minioadmin)

## Development

### Backend Development

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev
```

### Running the Worker

```bash
cd backend
python -m app.workers.pipeline
```

## API Endpoints

### Videos
- `POST /api/videos/upload` - Upload a video file
- `GET /api/videos/` - List all videos
- `GET /api/videos/{video_id}` - Get video details
- `DELETE /api/videos/{video_id}` - Delete a video

### Jobs
- `GET /api/jobs/{job_id}` - Get job status
- `GET /api/jobs/{job_id}/result` - Get job result
- `GET /api/jobs/` - List all jobs
- `DELETE /api/jobs/{job_id}` - Cancel a job
- `POST /api/jobs/{job_id}/retry` - Retry a failed job
- `WS /api/jobs/{job_id}/ws` - WebSocket for real-time updates

### Preview
- `GET /api/preview/{job_id}/output` - Get output video URL
- `GET /api/preview/{job_id}/scenes` - Get scene timeline
- `GET /api/preview/{job_id}/download` - Get download URL

## Pipeline Flow

1. **Upload** - Video is uploaded to MinIO storage
2. **Scene Detection** - PySceneDetect identifies scene boundaries
3. **Analysis** - Memories.ai analyzes each scene and generates descriptions
4. **Narration** - ElevenLabs converts descriptions to speech
5. **Sync** - Video speed is adjusted to match narration duration
6. **Stitch** - All scenes are combined into the final recap

## Configuration

Key settings in `backend/app/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `scene_detection_threshold` | 30.0 | Sensitivity for scene detection |
| `max_scene_duration` | 30.0 | Maximum scene length in seconds |
| `min_scene_duration` | 2.0 | Minimum scene length in seconds |
| `video_speed_min` | 0.5 | Minimum video speed multiplier |
| `video_speed_max` | 2.0 | Maximum video speed multiplier |

## Troubleshooting

### Video processing fails
- Check that the video format is supported (h264, h265, vp9)
- Ensure the video has an audio track
- Verify API keys are correct

### Scene detection issues
- Adjust `scene_detection_threshold` (lower = more scenes)
- Anime with static frames may need lower thresholds

### Audio sync problems
- Check `video_speed_min` and `video_speed_max` settings
- Very short/long narrations may need manual adjustment

## License

MIT

