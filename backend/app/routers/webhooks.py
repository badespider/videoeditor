"""
Webhook endpoints for receiving callbacks from external services.

This module handles callbacks from Memories.ai when video processing completes,
eliminating the need for polling.
"""

import json
import redis
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings


router = APIRouter()
settings = get_settings()


# Redis client for pub/sub
def get_redis_client():
    """Get Redis client for webhook notifications."""
    return redis.Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
        password=settings.redis.password if settings.redis.password else None,
        decode_responses=True
    )


class MemoriesWebhookPayload(BaseModel):
    """Expected payload from Memories.ai webhook callback."""
    video_no: Optional[str] = None
    videoNo: Optional[str] = None  # Alternative field name
    status: Optional[str] = None
    videoStatus: Optional[str] = None  # Alternative field name
    code: Optional[str] = None
    msg: Optional[str] = None
    data: Optional[dict] = None


def _extract_signature_header(request: Request) -> Optional[str]:
    """
    Extract a signature header value from the request.

    Since Memories.ai signature header name is unknown, we support:
    - Override via settings.webhook.signature_header
    - A small set of common headers
    """
    override = (settings.webhook.signature_header or "").strip()
    if override:
        v = request.headers.get(override)
        if v:
            return v

    for h in ("X-Memories-Signature", "X-Webhook-Signature", "X-Signature", "X-Hub-Signature-256"):
        v = request.headers.get(h)
        if v:
            return v
    return None


def _normalize_signature(sig: str) -> str:
    # Support formats like "sha256=<hex>" and raw "<hex>".
    s = (sig or "").strip()
    if "=" in s:
        # e.g. "sha256=abcd..."
        _, val = s.split("=", 1)
        return val.strip()
    return s


def _verify_hmac_sha256(secret: str, raw_body: bytes, provided_sig: str) -> bool:
    """
    Verify HMAC-SHA256 of raw request body.
    """
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = _normalize_signature(provided_sig)
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)


@router.post("/memories")
async def memories_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook endpoint for Memories.ai video processing callbacks.
    
    When a video finishes processing on Memories.ai, they call this endpoint
    with the video status. We then notify the waiting worker via Redis pub/sub.
    
    URL format: /api/webhooks/memories?job_id=xxx&video_no=yyy
    
    Query params:
        job_id: The job ID waiting for this video
        video_no: The Memories.ai video ID
    """
    # Get query parameters
    job_id = request.query_params.get("job_id")
    video_no = request.query_params.get("video_no")
    token = request.query_params.get("token")

    # Read raw body for optional signature verification + JSON parsing
    raw_body = await request.body()
    
    # Parse body
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}") if raw_body else {}
    except Exception:
        body = {}
    
    print(f"\n{'='*60}", flush=True)
    print(f"📥 WEBHOOK RECEIVED: Memories.ai callback", flush=True)
    print(f"   Job ID: {job_id}", flush=True)
    print(f"   Video No: {video_no}", flush=True)
    print(f"   Body: {json.dumps(body, indent=2)}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    # Validate we have required info
    if not job_id:
        print(f"⚠️ Webhook missing job_id parameter", flush=True)
        raise HTTPException(status_code=400, detail="Missing job_id parameter")

    # Token verification (always required)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        redis_client = get_redis_client()
        expected_token = redis_client.get(f"memories:webhook_token:{job_id}") or ""
        if not hmac.compare_digest(str(expected_token), str(token)):
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Token verification error: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Token verification failed")

    # Optional signature verification (only when signature header present + WEBHOOK_SECRET set)
    sig_header_val = _extract_signature_header(request)
    if sig_header_val and settings.webhook.secret:
        if not _verify_hmac_sha256(settings.webhook.secret, raw_body, sig_header_val):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Extract video_no from body if not in query params
    if not video_no:
        video_no = body.get("videoNo") or body.get("video_no")
        if body.get("data"):
            video_no = video_no or body["data"].get("videoNo") or body["data"].get("video_no")
    
    # Extract status from body
    status = body.get("videoStatus") or body.get("status")
    if body.get("data"):
        status = status or body["data"].get("videoStatus") or body["data"].get("status")
    
    # Default to PARSE if we got a successful callback (code 0000)
    code = body.get("code")
    if code == "0000" and not status:
        status = "PARSE"
    
    print(f"📊 Extracted: video_no={video_no}, status={status}", flush=True)
    
    # Publish notification to Redis
    try:
        redis_client = get_redis_client()
        
        # Create notification payload
        notification = {
            "job_id": job_id,
            "video_no": video_no,
            "status": status or "PARSE",  # Default to PARSE for successful callback
            "code": code,
            "msg": body.get("msg", ""),
            "timestamp": str(int(__import__("time").time()))
        }
        
        # Publish to job-specific channel
        channel = f"memories:webhook:{job_id}"
        redis_client.publish(channel, json.dumps(notification))
        
        # Also store in a key for workers that might have missed the pub/sub
        key = f"memories:status:{job_id}"
        redis_client.setex(key, 3600, json.dumps(notification))  # Expire in 1 hour
        
        print(f"✅ Published webhook notification to channel: {channel}", flush=True)
        print(f"✅ Stored status in key: {key}", flush=True)
        
    except Exception as e:
        print(f"❌ Failed to publish webhook notification: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Failed to process webhook: {e}")
    
    return {
        "status": "received",
        "job_id": job_id,
        "video_no": video_no,
        "processed_status": status
    }


@router.get("/memories/test")
async def test_webhook():
    """
    Test endpoint to verify webhook is accessible.
    
    Use this to verify your webhook URL is publicly accessible.
    """
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",
        "webhook_url": f"{settings.webhook.base_url}/api/webhooks/memories" if settings.webhook.base_url else "Not configured"
    }

