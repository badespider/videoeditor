import json
import uuid
from datetime import datetime
from typing import Optional, List, Callable, Any, Dict

import redis
from redis.exceptions import WatchError

from app.config import get_settings
from app.models import JobStatus, JobProgress, JobResult, Scene


class JobManager:
    """
    Manages job state and progress in Redis.
    
    Provides methods for creating, updating, and querying jobs.
    """
    
    def __init__(self):
        self.settings = get_settings()
        # Build Redis URL from settings
        redis_url = self.settings.redis_url
        self.redis = redis.from_url(redis_url)
        self.job_prefix = "job:"
        self.queue_name = "pipeline_queue"
        self.priority_queue_name = "pipeline_queue_priority"  # Studio plan jobs

        # Treat COMPLETED/FAILED as terminal states (no further updates).
        self._terminal_statuses = {JobStatus.COMPLETED.value, JobStatus.FAILED.value}

    def _job_key(self, job_id: str) -> str:
        return f"{self.job_prefix}{job_id}"

    def _publish_payload(self, job_data: dict) -> str:
        # Keep websocket payload small and consistent.
        return json.dumps(
            {
                "job_id": job_data.get("job_id"),
                "status": job_data.get("status"),
                "progress": job_data.get("progress"),
                "current_step": job_data.get("current_step"),
            }
        )

    def _update_job_atomic(
        self,
        job_id: str,
        apply_fn: Callable[[dict], bool],
        max_retries: int = 10,
    ) -> bool:
        """
        Atomically update a job using Redis WATCH/MULTI.

        Guardrail: once a job is terminal (COMPLETED/FAILED), we ignore all future updates.

        Returns:
            True if an update was applied, False if job missing, terminal, or no-op.
        """
        key = self._job_key(job_id)

        for _ in range(max_retries):
            pipe = self.redis.pipeline()
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw:
                    pipe.unwatch()
                    return False

                job_data = json.loads(raw)
                current_status = job_data.get("status")
                if current_status in self._terminal_statuses:
                    pipe.unwatch()
                    return False

                changed = apply_fn(job_data)
                if not changed:
                    pipe.unwatch()
                    return False

                job_data["updated_at"] = datetime.utcnow().isoformat()

                pipe.multi()
                pipe.set(key, json.dumps(job_data))
                pipe.publish(f"job_updates:{job_id}", self._publish_payload(job_data))
                result = pipe.execute()
                print(f"✅ Job {job_id} updated in Redis (status: {job_data.get('status', 'unknown')}, progress: {job_data.get('progress', 0)}%)", flush=True)
                return True
            except WatchError:
                # Another writer updated the key; retry.
                continue
            finally:
                try:
                    pipe.reset()
                except Exception:
                    pass

        return False
    
    def create_job(
        self,
        video_id: str,
        filename: str,
        target_duration_minutes: Optional[float] = None,
        character_guide: Optional[str] = None,
        enable_scene_matcher: bool = False,
        enable_copyright_protection: bool = False,
        series_id: Optional[str] = None,
        user_id: Optional[str] = None,
        plan_tier: str = "none",
        is_priority: bool = False
    ) -> str:
        """
        Create a new processing job.
        
        Args:
            video_id: ID of the video to process
            filename: Original filename
            target_duration_minutes: Optional target duration for final recap (allows ~10% over)
            character_guide: Optional character name mapping for narration
            enable_scene_matcher: Enable AI-powered clip matching (experimental)
            enable_copyright_protection: Enable copyright protection (clip splitting & transforms)
            series_id: Optional series ID for character persistence across episodes
            user_id: Optional user ID for multi-tenant support
            plan_tier: User's subscription plan tier ("none", "creator", "studio")
            is_priority: Whether job should be processed with priority (Studio plan)
            
        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        job_data = {
            "job_id": job_id,
            "video_id": video_id,
            "filename": filename,
            "status": JobStatus.PENDING.value,
            "progress": 0,
            "current_step": "Queued",
            "total_scenes": 0,
            "processed_scenes": 0,
            "error_message": None,
            "output_url": None,
            "scenes": [],
            "target_duration_minutes": target_duration_minutes,
            "character_guide": character_guide,
            "enable_scene_matcher": enable_scene_matcher,
            "enable_copyright_protection": enable_copyright_protection,
            "has_script": False,
            "series_id": series_id,
            "user_id": user_id,
            "plan_tier": plan_tier,
            "is_priority": is_priority,
            "created_at": now,
            "updated_at": now
        }
        
        self.redis.set(
            f"{self.job_prefix}{job_id}",
            json.dumps(job_data)
        )
        
        # Add to appropriate queue based on priority
        # Priority jobs go to a separate queue that workers check first
        queue_name = self.priority_queue_name if is_priority else self.queue_name
        self.redis.lpush(queue_name, job_id)
        
        if is_priority:
            print(f"⚡ Job {job_id} added to PRIORITY queue (plan: {plan_tier})", flush=True)
        
        return job_id
    
    def get_job(self, job_id: str) -> Optional[dict]:
        """
        Get job data by ID.
        
        Args:
            job_id: The job ID
            
        Returns:
            Job data dict or None
        """
        data = self.redis.get(self._job_key(job_id))
        if data:
            return json.loads(data)
        return None
    
    def update_job(
        self,
        job_id: str,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        total_scenes: Optional[int] = None,
        processed_scenes: Optional[int] = None,
        error_message: Optional[str] = None,
        output_url: Optional[str] = None,
        scenes: Optional[List[dict]] = None,
        has_script: Optional[bool] = None
    ):
        """
        Update job state.
        
        Args:
            job_id: The job ID
            status: New status
            progress: Progress percentage (0-100)
            current_step: Description of current step
            total_scenes: Total number of scenes
            processed_scenes: Number of processed scenes
            error_message: Error message if failed
            output_url: URL to final output
            scenes: Scene data list
        """
        def apply(job_data: Dict[str, Any]) -> bool:
            changed = False
        
            if status is not None and job_data.get("status") != status.value:
                old_status = job_data.get("status", "unknown")
                job_data["status"] = status.value
                print(f"🔄 Job {job_id} status change: {old_status} -> {status.value}", flush=True)
                changed = True
            if progress is not None and job_data.get("progress") != progress:
                job_data["progress"] = progress
                changed = True
            if current_step is not None and job_data.get("current_step") != current_step:
                job_data["current_step"] = current_step
                changed = True
            if total_scenes is not None and job_data.get("total_scenes") != total_scenes:
                job_data["total_scenes"] = total_scenes
                changed = True
            if processed_scenes is not None and job_data.get("processed_scenes") != processed_scenes:
                job_data["processed_scenes"] = processed_scenes
                changed = True
            if error_message is not None and job_data.get("error_message") != error_message:
                job_data["error_message"] = error_message
                changed = True
            if output_url is not None and job_data.get("output_url") != output_url:
                job_data["output_url"] = output_url
                changed = True
            if scenes is not None and job_data.get("scenes") != scenes:
                job_data["scenes"] = scenes
                changed = True
            if has_script is not None and job_data.get("has_script") != bool(has_script):
                job_data["has_script"] = bool(has_script)
                changed = True

            return changed

        self._update_job_atomic(job_id, apply_fn=apply)

    def fail_job_if_not_completed(
        self,
        job_id: str,
        error_message: str,
        current_step: str = "Failed",
    ) -> bool:
        """
        Only set FAILED if current status is not COMPLETED.

        Returns True if update applied, False if job missing or already terminal.
        """

        def apply(job_data: Dict[str, Any]) -> bool:
            if job_data.get("status") == JobStatus.COMPLETED.value:
                return False
            job_data["status"] = JobStatus.FAILED.value
            job_data["current_step"] = current_step
            job_data["error_message"] = error_message
            return True

        return self._update_job_atomic(job_id, apply_fn=apply)

    def complete_job_if_not_failed(
        self,
        job_id: str,
        output_url: Optional[str] = None,
        scenes: Optional[List[dict]] = None,
        progress: float = 100,
        current_step: str = "Complete!",
        processed_scenes: Optional[int] = None,
    ) -> bool:
        """
        Only set COMPLETED if current status is not FAILED.

        Returns True if update applied, False if job missing or already terminal.
        """

        def apply(job_data: Dict[str, Any]) -> bool:
            if job_data.get("status") == JobStatus.FAILED.value:
                return False
            job_data["status"] = JobStatus.COMPLETED.value
            job_data["progress"] = progress
            job_data["current_step"] = current_step
            if processed_scenes is not None:
                job_data["processed_scenes"] = processed_scenes
            if output_url is not None:
                job_data["output_url"] = output_url
            if scenes is not None:
                job_data["scenes"] = scenes
            return True

        return self._update_job_atomic(job_id, apply_fn=apply)
    
    def get_job_progress(self, job_id: str) -> Optional[JobProgress]:
        """
        Get job progress info.
        
        Args:
            job_id: The job ID
            
        Returns:
            JobProgress object or None
        """
        job_data = self.get_job(job_id)
        if not job_data:
            return None
        
        return JobProgress(
            job_id=job_data["job_id"],
            status=JobStatus(job_data["status"]),
            progress=job_data["progress"],
            current_step=job_data["current_step"],
            total_scenes=job_data["total_scenes"],
            processed_scenes=job_data["processed_scenes"],
            error_message=job_data.get("error_message"),
            created_at=datetime.fromisoformat(job_data["created_at"]),
            updated_at=datetime.fromisoformat(job_data["updated_at"])
        )
    
    def get_job_result(self, job_id: str) -> Optional[JobResult]:
        """
        Get completed job result.
        
        Args:
            job_id: The job ID
            
        Returns:
            JobResult object or None
        """
        job_data = self.get_job(job_id)
        if not job_data:
            return None
        
        scenes = [
            Scene(**s) for s in job_data.get("scenes", [])
        ]
        
        return JobResult(
            job_id=job_data["job_id"],
            video_id=job_data["video_id"],
            status=JobStatus(job_data["status"]),
            output_url=job_data.get("output_url"),
            scenes=scenes,
            error_message=job_data.get("error_message")
        )
    
    def get_next_job(self) -> Optional[str]:
        """
        Get the next job ID from the queue.
        
        Priority queue is checked first (Studio plan jobs),
        then the standard queue (Creator plan jobs).
        
        Returns:
            Job ID or None if both queues are empty
        """
        # Check priority queue first (Studio plan)
        result = self.redis.rpop(self.priority_queue_name)
        if result:
            job_id = result.decode("utf-8")
            print(f"⚡ Processing PRIORITY job: {job_id}", flush=True)
            return job_id
        
        # Fall back to standard queue (Creator plan)
        result = self.redis.rpop(self.queue_name)
        if result:
            return result.decode("utf-8")
        
        return None
    
    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> List[dict]:
        """
        List jobs, optionally filtered by status and user.
        
        Args:
            status: Optional status filter
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip (for pagination)
            user_id: Optional user ID filter (for multi-tenant support)
            
        Returns:
            List of job data dicts
        """
        jobs = []
        cursor = 0
        
        while True:
            cursor, keys = self.redis.scan(
                cursor,
                match=f"{self.job_prefix}*",
                count=100
            )
            
            for key in keys:
                data = self.redis.get(key)
                if data:
                    job_data = json.loads(data)
                    
                    # Apply status filter
                    if status is not None and job_data["status"] != status.value:
                        continue
                    
                    # Apply user filter
                    if user_id is not None and job_data.get("user_id") != user_id:
                        continue
                    
                    jobs.append(job_data)
            
            if cursor == 0:
                break
        
        # Sort by created_at descending
        jobs.sort(key=lambda x: x["created_at"], reverse=True)
        
        # Apply pagination
        return jobs[offset:offset + limit]
    
    def delete_job(self, job_id: str):
        """
        Delete a job from Redis.
        
        Args:
            job_id: The job ID to delete
        """
        self.redis.delete(self._job_key(job_id))
    
    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """
        Clean up old completed/failed jobs.
        
        Args:
            max_age_hours: Maximum age in hours for jobs to keep
        """
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        jobs = self.list_jobs(limit=1000)
        
        for job in jobs:
            if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                created = datetime.fromisoformat(job["created_at"])
                if created < cutoff:
                    self.delete_job(job["job_id"])

