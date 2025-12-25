from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings


def _default_saas_jobs_url() -> str:
    # Safe production default for this repo; can be overridden via SAAS_WEBHOOK_URL or WEBHOOK__SAAS_JOBS_URL.
    return "https://app.videorecapai.com/api/webhooks/jobs"


def _resolve_saas_config() -> tuple[str, str]:
    """
    Resolve SaaS webhook URL + Bearer secret.

    Priority:
      1) Settings (nested env): WEBHOOK__SAAS_JOBS_URL / WEBHOOK__SAAS_SECRET
      2) Legacy flat env: SAAS_WEBHOOK_URL / SAAS_WEBHOOK_SECRET
      3) Fallback URL for production, empty secret fallback to WEBHOOK_SECRET
    """
    settings = get_settings()

    url = (settings.webhook.saas_jobs_url or "").strip() or os.getenv("SAAS_WEBHOOK_URL", "").strip()
    if not url:
        url = _default_saas_jobs_url()

    secret = (settings.webhook.saas_secret or "").strip() or os.getenv("SAAS_WEBHOOK_SECRET", "").strip()
    if not secret:
        # Back-compat: reuse WEBHOOK_SECRET if provided.
        secret = (settings.webhook.secret or "").strip() or os.getenv("WEBHOOK_SECRET", "").strip()
    if not secret:
        # Last-resort fallback: match the SaaS default to avoid silent 401s when env vars are missing.
        # NOTE: For real security, set WEBHOOK_SECRET in both Railway (backend) and Vercel (saas-frontend).
        secret = "your-webhook-secret"

    return url, secret


async def notify_saas_job_update(payload: Dict[str, Any], *, timeout_seconds: float = 5.0, retries: int = 2) -> None:
    """
    Best-effort notifier: POST job updates to the SaaS webhook.
    Must NEVER raise (should not fail the video processing job).
    """
    url, secret = _resolve_saas_config()
    if not url:
        return

    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    # Ensure the payload always has a completed_at when marking completed.
    if payload.get("status") == "completed" and not payload.get("completed_at"):
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()

    attempt = 0
    last_err: Optional[Exception] = None

    while attempt <= max(0, int(retries)):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                res = await client.post(url, json=payload, headers=headers)
                # Treat 2xx as success; log non-2xx for debugging but don't raise.
                if 200 <= res.status_code < 300:
                    return
                print(f"⚠️ SaaS webhook responded {res.status_code} for status={payload.get('status')}", flush=True)
                # 401/403 are almost always a secret mismatch; don't retry endlessly.
                if res.status_code in (401, 403):
                    return
        except Exception as e:
            last_err = e
        attempt += 1

    # Swallow error; keep minimal signal in stdout for production debugging.
    if last_err:
        print(f"⚠️ SaaS webhook notify failed: {last_err}", flush=True)

