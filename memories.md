# Memories.ai API Documentation - Complete Reference

**Base URL:** `https://api.memories.ai`  
**Version:** v1.2  
**Documentation:** https://memories.ai/docs/

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [Upload APIs](#upload-apis)
4. [Search APIs](#search-apis)
5. [Chat APIs](#chat-apis)
6. [Transcription APIs](#transcription-apis)
7. [Utils APIs](#utils-apis)
8. [Response Codes](#response-codes)
9. [Key Parameters](#key-parameters)
10. [Limitations & Rate Limits](#limitations--rate-limits)

---

## Getting Started

- **Sign Up**: Create a Memories.ai account at [Login Page](https://memories.ai/app/login)
- **API Key Setup**: Generate your personal API key from the [API settings](https://memories.ai/app/service/key)
- **Prerequisites**: Valid account & API key, FFmpeg-compatible video formats with audio track

---

## Authentication

- **API Key**: Include in `Authorization` header (without "Bearer" prefix)
- **OAuth2 (O2O)**: Available for business/enterprise

---

## Upload APIs

### Upload Video from File
**Endpoint:** `POST /serve/api/v1/upload`

**Headers:**
- `Authorization` (string, required) — API key

**Body Parameters (multipart/form-data):**
- `file` (binary, required) — Video file
- `callback` (string, optional) — Callback URI for notifications
- `unique_id` (string, optional, default: "default") — User/workspace identifier
- `datetime_taken` (string, optional) — Format: `YYYY-MM-DD HH:MM:SS`
- `camera_model` (string, optional)
- `latitude` (string, optional)
- `longitude` (string, optional)
- `tags` (array[string], optional)
- `retain_original_video` (boolean, optional)
- `video_transcription_prompt` (string, optional)

**Response:**
```json
{
  "code": "0000",
  "msg": "success",
  "data": {
    "videoNo": "VI568102998803353600",
    "videoName": "video_name",
    "videoStatus": "UNPARSE",
    "uploadTime": "1744905509814"
  }
}
```

### Upload Video from URL
**Endpoint:** `POST /serve/api/v1/upload_url`

**Body Parameters (JSON):**
- `url` (string, required) — Direct link to video
- Same optional params as file upload

---

## Search APIs

### Search from Private Library
**Endpoint:** `POST /serve/api/v1/search`

**Headers:**
- `Authorization` (string, required)

**Body (JSON):**
- `search_param` (string, required) — Natural language query
- `search_type` (string, required) — "BY_VIDEO", "BY_AUDIO", or "BY_IMAGE"
- `unique_id` (string, optional, default: "default")
- `top_k` (int, optional) — Number of top results
- `filtering_level` (string, optional) — "low", "medium", or "high"
- `video_nos` (array[string], optional) — Search within specific videos
- `tag` (string, optional)
- `latitude` (float, optional)
- `longitude` (float, optional)

**Response:**
```json
{
  "code": "0000",
  "msg": "success",
  "data": [
    {
      "videoNo": "VI576925607808602112",
      "videoName": "video_name",
      "startTime": "13",
      "endTime": "18",
      "score": 0.5221236659362116
    }
  ]
}
```

---

## Chat APIs

### Video Chat (Non-Stream)
**Endpoint:** `POST /serve/api/v1/chat`

**Headers:**
- `Authorization` (string, required)
- `Content-Type`: "application/json"

**Body (JSON):**
- `video_nos` (array[string], required) — List of video IDs
- `prompt` (string, required) — Query for the chat
- `session_id` (string/int, optional)
- `unique_id` (string, optional)

### Video Chat (Stream)
**Endpoint:** `POST /serve/api/v1/chat_stream`

**Additional Header:**
- `Accept`: "text/event-stream"

---

## Transcription APIs

### Get Video Transcription
**Endpoint:** `GET /serve/api/v1/get_video_transcription`

**Query Parameters:**
- `video_no` (string, required)
- `unique_id` (string, optional)

**Headers:**
- `Authorization` (string, required)

**Response:**
```json
{
  "code": "0000",
  "msg": "success",
  "data": {
    "videoNo": "VI606041694843813888",
    "transcriptions": [
      {
        "index": 0,
        "content": "Transcription text...",
        "startTime": "0",
        "endTime": "8"
      }
    ],
    "createTime": "1758276264066"
  }
}
```

### Get Audio Transcription
**Endpoint:** `GET /serve/api/v1/get_audio_transcription`

**Query Parameters:**
- `video_no` (string, required)
- `unique_id` (string, optional)

### Get Transcription Summary
**Endpoint:** `GET /serve/api/v1/get_transcription_summary`

**Query Parameters:**
- `video_no` (string, required)
- `unique_id` (string, optional)
- `summary_type` (string, optional) — "chapters", "topics", etc.

### Generate Video Summary
**Endpoint:** `GET /serve/api/v1/generate_summary`

Creates a structured summary of a video as either chapters (scene-based) or topics (semantic clusters).

**Prerequisites:**
- Video must be uploaded and fully parsed (status `PARSE`)
- Valid Memories.ai API key

**Headers:**
- `Authorization` (string, required) — API key

**Query Parameters:**
- `video_no` (string, required) — The videoNo from upload/transcription
- `type` (string, required) — `CHAPTER` for scene-based or `TOPIC` for semantic clusters
- `unique_id` (string, optional) — Defaults to "default"

**Response:**
```json
{
  "code": "0000",
  "msg": "success",
  "success": true,
  "failed": false,
  "data": {
    "videoNo": "VI123456789",
    "summary_type": "CHAPTER",
    "summary": [
      {
        "title": "Introduction",
        "start": 0.0,
        "end": 90.5,
        "description": "Character enters the room and looks around."
      },
      {
        "title": "The Confrontation",
        "start": 90.5,
        "end": 180.0,
        "description": "Two characters argue about the missing artifact."
      }
    ]
  }
}
```

**Usage Notes:**
- Use `type=CHAPTER` for scene/shot-style breakdown tracking structural changes
- Use `type=TOPIC` for semantic theme clusters (better for educational content)
- Only call after video has finished processing (status `PARSE`)

---

## Utils APIs

### List Videos
**Endpoint:** `POST /serve/api/v1/list_videos`

**Headers:**
- `Authorization` (string, required)

**Body (JSON):**
- `page` (int, optional, default: 1)
- `size` (int, optional, default: 20)
- `video_name` (string, optional)
- `video_no` (string, optional)
- `unique_id` (string, optional)
- `status` (string, optional) — "PARSE", "UNPARSE", "PARSE_ERROR"

**Response:**
```json
{
  "code": "0000",
  "msg": "success",
  "data": {
    "videos": [
      {
        "duration": "12",
        "size": "3284512",
        "status": "PARSE",
        "cause": "null",
        "video_no": "VI606404158946574336",
        "video_name": "video_name",
        "create_time": "1754037217992"
      }
    ],
    "current_page": 1,
    "page_size": 200,
    "total_count": "3"
  }
}
```

### Get Private Video Detail
**Endpoint:** `GET /serve/api/v1/get_private_video_detail`

**Query Parameters:**
- `video_no` (string, required)
- `unique_id` (string, optional)

### Get Task Status
**Endpoint:** `GET /serve/api/v1/get_task_status`

**Query Parameters:**
- `task_id` (string, required)

### Delete Videos
**Endpoint:** `DELETE /serve/api/v1/delete_videos`

**Body (JSON):**
- `video_nos` (array[string], required)
- `unique_id` (string, optional)

### Other Utils Endpoints:
- **List Chat Sessions:** `POST /serve/api/v1/list_sessions`
- **Get Session Detail:** `GET /serve/api/v1/get_session_detail`
- **Get Public Video Details:** `GET /serve/api/v1/get_public_video_detail`
- **Download Video:** `GET /serve/api/v1/download_video`
- **List Images:** `POST /serve/api/v1/list_images`

---

## Response Codes

| Code | Description | Solution |
|------|-------------|----------|
| `0000` | Success | The API completed successfully |
| `0001` / `0003` | Parameters incorrect | Check all parameters |
| `0429` | Request too busy | System under heavy load, retry later |
| `0409` | Duplicate requests not allowed | Cannot perform same operation twice |
| `0403` | Developer account disabled | Contact support |
| `0401` | Authorization invalid | Re-authenticate |
| `0402` | Insufficient points | Deposit more credits |
| `9009` | Permission denied | Check API key validity |

### VideoStatus Enum Values:
- `PARSE` — Video successfully parsed/indexed
- `UNPARSE` — Video still being processed
- `PARSE_ERROR` — Parsing failed (check encoding)

---

## Key Parameters

- **unique_id**: Logical grouping/container (user/folder/workspace/namespace). Default is `"default"`.
- **callback**: URL endpoint for async notifications on processing.
- **tags**: Array/string for enhanced context (up to 20 tags, GPS, datetime, camera model).
- **video_transcription_prompt**: Custom prompt for guiding video analysis.

---

## Limitations & Rate Limits

| Interface | QPS/QPM Limit |
|-----------|--------------|
| Upload (local/streaming) | 1 QPS |
| Upload (platform/creator) | 1 QPM |
| Search | 10 QPS |
| Chat | 1 QPS |
| Video Marketer | 1 QPS |
| Transcription (Audio) | 5 QPS |
| Caption (Video) | 1 QPS |
| Download Videos | 12 QPM |
| Streaming Caption | 4 concurrent streams |

**Note:** Exceeding rate limits returns `{code: "0429"}` — throttle or upgrade.

---

## Best Practices

- Use `unique_id` parameter for multi-tenant applications
- Provide `callback` URLs for async status updates
- Use `top_k` to limit search results for efficiency
- Adjust `filtering_level` to balance recall and precision
- Video formats must be: h264, h265, vp9, or hevc
- Ensure videos are in `PARSE` status before using in other endpoints

---

## Support

- **Email:** contact@memories.ai
- **Discord:** https://discord.gg/dAqjfdJaQz
- **Documentation:** https://memories.ai/docs/

---

*Generated from official Memories.ai API documentation v1.2*  
*Last Updated: November 15, 2025*
