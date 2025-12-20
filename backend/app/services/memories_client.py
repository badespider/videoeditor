import asyncio
import httpx
from typing import Optional, List, Tuple
from pathlib import Path

from app.config import get_settings
from app.models import MemoriesUploadResponse, VideoStatus


class MemoriesAIClient:
    """
    Client for interacting with Memories.ai API.
    
    Handles video upload, status polling, and scene description generation.
    Based on Memories.ai API v1.2 documentation.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = f"{self.settings.memories.base_url}/serve/api/v1"
        self.headers = {
            "Authorization": self.settings.memories.api_key  # No "Bearer" prefix
        }
    
    async def upload_video(
        self, 
        file_path: str,
        unique_id: str = "default",
        tags: Optional[List[str]] = None,
        callback_url: Optional[str] = None
    ) -> MemoriesUploadResponse:
        """
        Upload a video file to Memories.ai for processing.
        
        Args:
            file_path: Path to the video file
            unique_id: Workspace/user identifier
            tags: Optional tags for the video
            callback_url: Optional webhook URL for processing completion notification
            
        Returns:
            MemoriesUploadResponse with video_no and status
        """
        print(f"📤 Uploading video to Memories.ai: {file_path}", flush=True)
        print(f"📡 API URL: {self.base_url}/upload", flush=True)
        if callback_url:
            print(f"🔔 Callback URL: {callback_url}", flush=True)
        
        async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout for large uploads
            with open(file_path, "rb") as f:
                files = {"file": (Path(file_path).name, f, "video/mp4")}
                form_data = {"unique_id": unique_id}
                
                if tags:
                    form_data["tags"] = tags
                
                # Add callback URL if provided (enables webhook notifications)
                if callback_url:
                    form_data["callback"] = callback_url
                
                try:
                    response = await client.post(
                        f"{self.base_url}/upload",
                        headers=self.headers,
                        files=files,
                        data=form_data
                    )
                    
                    print(f"📥 Response status: {response.status_code}", flush=True)
                    
                    # Log full response for debugging
                    result = response.json()
                    print(f"📥 Response body: {result}", flush=True)
                    
                    response.raise_for_status()
                    
                    if result.get("code") != "0000":
                        raise Exception(f"Upload failed: {result.get('msg', 'Unknown error')}")
                    
                    resp_data = result.get("data", {})
                    
                    # Handle different response formats
                    video_no = resp_data.get("videoNo") or resp_data.get("video_no", "")
                    video_name = resp_data.get("videoName") or resp_data.get("video_name", Path(file_path).name)
                    video_status = resp_data.get("videoStatus") or resp_data.get("video_status") or resp_data.get("status", "UNPARSE")
                    upload_time = resp_data.get("uploadTime") or resp_data.get("upload_time", "")
                    
                    print(f"✅ Upload successful! Video No: {video_no}", flush=True)
                    
                    return MemoriesUploadResponse(
                        video_no=video_no,
                        video_name=video_name,
                        video_status=video_status,
                        upload_time=upload_time
                    )
                    
                except httpx.HTTPStatusError as e:
                    print(f"❌ HTTP Error: {e.response.status_code} - {e.response.text}", flush=True)
                    raise
                except Exception as e:
                    print(f"❌ Upload error: {str(e)}", flush=True)
                    raise
    
    async def get_video_status(
        self, 
        video_no: str,
        unique_id: str = "default",
        max_retries: int = 3
    ) -> Tuple[VideoStatus, Optional[str]]:
        """
        Get the processing status of an uploaded video using list_videos endpoint.
        
        Args:
            video_no: The video ID from upload
            unique_id: Workspace/user identifier
            max_retries: Number of retries for network errors
            
        Returns:
            VideoStatus enum value
        """
        print(f"🔍 Checking status for video: {video_no}", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # Use list_videos endpoint to get video status
                    response = await client.post(
                        f"{self.base_url}/list_videos",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_no": video_no,
                            "unique_id": unique_id,
                            "page": 1,
                            "size": 1
                        }
                    )
                    
                    print(f"📥 Status response: {response.status_code}", flush=True)
                    response.raise_for_status()
                    
                    result = response.json()
                    print(f"📥 Status body: {result}", flush=True)
                    
                    # Handle transient network errors from Memories.ai
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "abnormal" in msg.lower() or "try again" in msg.lower():
                            print(f"⚠️ Network error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Status check failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff
                            continue
                        raise Exception(f"Status check failed: {msg}")
                    
                    videos = result.get("data", {}).get("videos", [])
                    if not videos:
                        # Video not found yet, might still be processing
                        return (VideoStatus.UNPARSE, None)
                    
                    video_data = videos[0]
                    status_str = video_data.get("status", "UNPARSE")
                    cause = video_data.get("cause")  # Get the cause/error message from API
                    print(f"📊 Video status: {status_str}", flush=True)
                    if cause and cause != "null":
                        print(f"📊 Video cause: {cause}", flush=True)
                    
                    # Map API status strings to VideoStatus enum values
                    status_mapping = {
                        "UNPARSE": VideoStatus.UNPARSE,
                        "PARSE": VideoStatus.PARSE,
                        "PARSE_ERROR": VideoStatus.PARSE_ERROR,
                        "FAIL": VideoStatus.PARSE_ERROR,  # Map FAIL to PARSE_ERROR
                        "FAILED": VideoStatus.PARSE_ERROR,  # Map FAILED to PARSE_ERROR
                        "ERROR": VideoStatus.PARSE_ERROR,  # Map ERROR to PARSE_ERROR
                    }
                    
                    # Get mapped status or default to UNPARSE
                    mapped_status = status_mapping.get(status_str.upper(), VideoStatus.UNPARSE)
                    return (mapped_status, cause if cause and cause != "null" else None)
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                if "Status check failed" in str(e):
                    raise  # Re-raise non-transient errors
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # If all retries failed, raise the last error
        if last_error:
            raise last_error
        return (VideoStatus.UNPARSE, None)  # Return default on failure
    
    async def wait_for_processing(
        self, 
        video_no: str,
        unique_id: str = "default",
        max_wait_seconds: int = 600,
        poll_interval: int = 10
    ) -> bool:
        """
        Wait for a video to finish processing (POLLING MODE - FALLBACK).
        
        Args:
            video_no: The video ID
            unique_id: Workspace/user identifier
            max_wait_seconds: Maximum time to wait
            poll_interval: Seconds between status checks
            
        Returns:
            True if processing completed, False if timeout or error
        """
        elapsed = 0
        last_status = None
        last_log_time = 0
        
        while elapsed < max_wait_seconds:
            status, cause = await self.get_video_status(video_no, unique_id)
            
            # Log status changes and periodically log UNPARSE status every 60 seconds
            should_log = (
                status != last_status or 
                (elapsed - last_log_time >= 60 and status == VideoStatus.UNPARSE) or
                (elapsed - last_log_time >= 120)  # Log every 2 minutes for any status
            )
            
            if should_log:
                status_str = status.value if hasattr(status, 'value') else str(status)
                elapsed_min = elapsed // 60
                elapsed_sec = elapsed % 60
                print(f"📊 Video status check ({elapsed_min:.0f}m {elapsed_sec:.0f}s): {status_str}", flush=True)
                if cause and cause != "null":
                    print(f"   Cause: {cause}", flush=True)
                last_status = status
                last_log_time = elapsed
            
            if status == VideoStatus.PARSE:
                print(f"✅ Video parsing completed in {elapsed//60:.0f}m {elapsed%60:.0f}s", flush=True)
                return True
            elif status == VideoStatus.PARSE_ERROR:
                error_msg = f"Video parsing failed for {video_no}"
                if cause:
                    error_msg += f": {cause}"
                raise Exception(error_msg)
            
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        
        # Timeout reached - log final status
        final_status, final_cause = await self.get_video_status(video_no, unique_id)
        status_str = final_status.value if hasattr(final_status, 'value') else str(final_status)
        print(f"⏱️ Processing timeout after {max_wait_seconds//60:.0f} minutes. Final status: {status_str}", flush=True)
        if final_cause and final_cause != "null":
            print(f"   Cause: {final_cause}", flush=True)
        
        return False
    
    async def wait_for_processing_webhook(
        self,
        video_no: str,
        job_id: str,
        unique_id: str = "default",
        max_wait_seconds: int = 3600,
        check_interval: int = 5
    ) -> bool:
        """
        Wait for video processing using webhook notification (NO POLLING!).
        
        This method listens for webhook callbacks via Redis pub/sub instead of
        polling the API repeatedly. Much more efficient!
        
        🚀 OPTIMIZATION: 0 API calls while waiting (vs 6-360 calls with polling)
        
        Args:
            video_no: The video ID
            job_id: The job ID (used for webhook channel)
            unique_id: Workspace/user identifier
            max_wait_seconds: Maximum time to wait
            check_interval: How often to check Redis for status (not API!)
            
        Returns:
            True if processing completed, False if timeout or error
        """
        import redis
        import json
        
        print(f"\n{'='*60}", flush=True)
        print(f"🔔 WEBHOOK MODE: Waiting for processing notification", flush=True)
        print(f"   Video: {video_no}", flush=True)
        print(f"   Job: {job_id}", flush=True)
        print(f"   Max wait: {max_wait_seconds}s ({max_wait_seconds/60:.0f} min)", flush=True)
        print(f"   NO POLLING - waiting for webhook callback!", flush=True)
        print(f"{'='*60}\n", flush=True)
        
        # Connect to Redis
        redis_client = redis.Redis(
            host=self.settings.redis.host,
            port=self.settings.redis.port,
            db=self.settings.redis.db,
            password=self.settings.redis.password if self.settings.redis.password else None,
            decode_responses=True
        )
        
        # Subscribe to the job-specific channel
        pubsub = redis_client.pubsub()
        channel = f"memories:webhook:{job_id}"
        pubsub.subscribe(channel)
        
        print(f"📡 Subscribed to channel: {channel}", flush=True)
        
        elapsed = 0
        status_key = f"memories:status:{job_id}"
        
        try:
            while elapsed < max_wait_seconds:
                # Check for pub/sub messages (non-blocking)
                message = pubsub.get_message(timeout=check_interval)
                
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        status = data.get("status", "").upper()
                        
                        print(f"📥 Received webhook notification: status={status}", flush=True)
                        
                        if status == "PARSE":
                            print(f"✅ Video processing complete (via webhook)!", flush=True)
                            return True
                        elif status == "PARSE_ERROR":
                            raise Exception(f"Video parsing failed for {video_no}")
                    except json.JSONDecodeError:
                        pass
                
                # Also check the Redis key (in case we missed the pub/sub message)
                stored_status = redis_client.get(status_key)
                if stored_status:
                    try:
                        data = json.loads(stored_status)
                        status = data.get("status", "").upper()
                        
                        if status == "PARSE":
                            print(f"✅ Video processing complete (from Redis key)!", flush=True)
                            return True
                        elif status == "PARSE_ERROR":
                            raise Exception(f"Video parsing failed for {video_no}")
                    except json.JSONDecodeError:
                        pass
                
                elapsed += check_interval
                
                # Log progress every minute
                if elapsed % 60 == 0:
                    print(f"⏳ Still waiting for webhook... ({elapsed}s / {max_wait_seconds}s)", flush=True)
            
            print(f"⚠️ Webhook wait timed out after {max_wait_seconds}s", flush=True)
            return False
            
        finally:
            # Clean up subscription
            pubsub.unsubscribe(channel)
            pubsub.close()
    
    async def get_full_story_summary(
        self,
        video_no: str,
        unique_id: str = "default",
        max_retries: int = 3
    ) -> str:
        """
        Get a comprehensive story summary of the entire video.
        
        Args:
            video_no: The video ID
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            Full story summary with character names and plot
        """
        prompt = (
            "Watch this entire video and provide a detailed story summary. "
            "Include: 1) All character names mentioned or shown, "
            "2) The main plot points in chronological order, "
            "3) Key events and turning points, "
            "4) The setting/world. "
            "Be thorough - I need to understand the full story to create a recap narration."
        )
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error getting story (attempt {attempt + 1}): {msg}", flush=True)
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Story summary failed: {msg}")
                    
                    data = result.get("data", {})
                    content = data.get("content") or data.get("answer", "")
                    if content:
                        print(f"📖 Got story summary ({len(content)} chars)", flush=True)
                        return content
                    return ""
                    
            except Exception as e:
                print(f"⚠️ Error getting story (attempt {attempt + 1}): {e}", flush=True)
                await asyncio.sleep(5 * (attempt + 1))
        
        return ""
    
    async def get_visual_description(
        self,
        video_no: str,
        start_time: float,
        end_time: float,
        unique_id: str = "default",
        max_retries: int = 3,
        custom_prompt: str = None
    ) -> str:
        """
        Get raw visual facts from Memories.ai for a specific timestamp range.
        
        This method is designed for the hybrid pipeline where Memories.ai
        provides factual visual descriptions, and Gemini transforms them
        into dramatic narration.
        
        Args:
            video_no: The video ID from Memories.ai
            start_time: Scene start in seconds
            end_time: Scene end in seconds
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            custom_prompt: Optional custom prompt for frame-specific queries
            
        Returns:
            Raw visual description (factual, no storytelling)
        """
        # Use custom prompt if provided, otherwise use default factual prompt
        if custom_prompt:
            prompt = custom_prompt
        else:
            # Simple factual prompt - no drama, just observations
            prompt = (
                f"Describe exactly what happens visually from {start_time:.1f}s to {end_time:.1f}s. "
                f"Include: character names (if known), their actions, facial expressions, "
                f"body language, locations, and any important objects. "
                f"Be factual and detailed. Do NOT add drama, interpretation, or storytelling. "
                f"Just describe what you see like a court reporter."
            )
        
        print(f"👁️ Getting visual facts: {start_time:.1f}s - {end_time:.1f}s", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    # Check for transient errors that should be retried
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower() or result.get("code") == "0429":
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Chat failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Chat failed: {msg}")
                    
                    # Extract the response text
                    data = result.get("data", {})
                    answer = data.get("content") or data.get("answer", "")
                    if answer:
                        print(f"👁️ Got visual facts ({len(answer)} chars)", flush=True)
                        return answer
                    
                    print(f"⚠️ Empty response, retrying...", flush=True)
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # Return empty string on failure (pipeline will handle)
        print(f"❌ Failed to get visual facts after {max_retries} retries", flush=True)
        return ""
    
    async def get_visual_description_batch(
        self,
        video_no: str,
        batch_segments: List[Tuple[float, float]],
        unique_id: str = "default",
        max_retries: int = 3
    ) -> List[str]:
        """
        Get raw visual facts for multiple segments in ONE API call.
        
        This is the batch version for efficiency - instead of N calls,
        we make 1 call and parse the response.
        
        Args:
            video_no: The video ID from Memories.ai
            batch_segments: List of (start_time, end_time) tuples
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            List of visual descriptions, one per segment
        """
        # Build segment list for prompt
        segment_text = "\n".join([
            f"Segment {i+1}: {s:.1f}s to {e:.1f}s"
            for i, (s, e) in enumerate(batch_segments)
        ])
        
        # Simple factual prompt for batch
        prompt = (
            f"For each segment below, describe exactly what happens visually.\n"
            f"Include: character names, actions, expressions, locations, objects.\n"
            f"Be factual - NO drama, NO storytelling, NO interpretation.\n\n"
            f"SEGMENTS:\n{segment_text}\n\n"
            f"Return a JSON array with one description per segment:\n"
            f"[\"description 1\", \"description 2\", ...]\n\n"
            f"JSON array:"
        )
        
        print(f"👁️ Batch visual request: {len(batch_segments)} segments", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Batch visual failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Batch visual failed: {msg}")
                    
                    # Parse response
                    raw_response = result.get("data", {}).get("content", "")
                    
                    # Try to extract JSON array from response
                    descriptions = self._parse_batch_response(raw_response, len(batch_segments))
                    
                    print(f"👁️ Batch visual success: got {len(descriptions)} descriptions", flush=True)
                    return descriptions
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # If batch fails, return empty strings
        print(f"❌ Batch visual failed after {max_retries} retries", flush=True)
        return ["" for _ in batch_segments]
    
    async def describe_scene(
        self,
        video_no: str,
        start_time: float,
        end_time: float,
        unique_id: str = "default",
        character_name: Optional[str] = None,
        max_retries: int = 3,
        story_context: str = "",
        scene_index: int = 0,
        total_scenes: int = 1,
        previous_narration: str = ""
    ) -> str:
        """
        Get a storytelling narration for a specific scene segment.
        
        Args:
            video_no: The video ID
            start_time: Scene start in seconds
            end_time: Scene end in seconds
            unique_id: Workspace/user identifier
            character_name: Optional main character name to focus on
            max_retries: Number of retries for transient errors
            story_context: Full story summary for context
            scene_index: Which scene this is (0-based)
            total_scenes: Total number of scenes
            previous_narration: The narration from the previous scene
            
        Returns:
            Storytelling narration for the scene
        """
        # Calculate duration and strict word limit
        # 2.5 words/second is standard speaking rate for narration
        duration = end_time - start_time
        word_limit = max(10, int(duration * 2.5))  # Minimum 10 words
        
        # Build context with previous narration for story continuity
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        prev_info = ""
        if previous_narration:
            prev_info = f"PREVIOUS LINE: \"{previous_narration}\"\n\n"
        
        # Chronological factual narrator prompt - natural storytelling style
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Convert scene descriptions into continuous story flow.\n\n"
            f"{context_info}"
            f"{prev_info}"
            f"SCENE: {start_time:.1f}s - {end_time:.1f}s (Max {word_limit} words)\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought' or 'Yuji is fighting'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined', 'feels the weight'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence they appear in video\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character', 'a person'\n"
            f"7. TIME MARKERS: Use exact timestamps for major scene changes (e.g., 'At minute 12')\n"
            f"8. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone' or 'he sees looking upset'\n"
            f"9. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context. Say what it is.\n\n"
            f"EXAMPLE TRANSFORMATIONS:\n"
            f"❌ BAD: 'Realizing the gravity of the situation, Yuji suddenly decides...'\n"
            f"✅ GOOD: 'Yuji decides to fight the curse at minute 12.'\n"
            f"\n❌ BAD: 'The young man is caught off guard by a shocking discovery...'\n"
            f"✅ GOOD: 'Yuji finds out his grandfather died at minute 8.'\n"
            f"\n❌ BAD: 'With determination burning in his eyes, he prepares for battle...'\n"
            f"✅ GOOD: 'Yuji prepares his magic for the upcoming fight at minute 15.'\n\n"
            f"OUTPUT: Write the story as it happens, not how it feels. No quotes, no labels."
        )
        
        print(f"📝 Requesting narration: {duration:.1f}s clip, max {word_limit} words", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    # Check for transient errors that should be retried
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        # Retry on network/temporary errors
                        if "network" in msg.lower() or "busy" in msg.lower() or result.get("code") == "0429":
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Chat failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff
                            continue
                        raise Exception(f"Chat failed: {msg}")
                    
                    # Extract the response text (API returns "content", not "answer")
                    data = result.get("data", {})
                    answer = data.get("content") or data.get("answer", "")
                    if answer:
                        return answer
                    
                    # Empty response, use fallback
                    print(f"⚠️ Empty response from chat API, data: {data}", flush=True)
                    return f"Scene from {start_time:.0f}s to {end_time:.0f}s."
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # If all retries failed, raise exception to prevent bad video
        print(f"❌ All retries failed - stopping to prevent garbage output", flush=True)
        raise Exception(f"Narration generation failed after {max_retries} retries for scene {start_time:.0f}s-{end_time:.0f}s")
    
    async def describe_scene_batch(
        self,
        video_no: str,
        batch_segments: List[Tuple[float, float]],
        story_context: str = "",
        unique_id: str = "default",
        max_retries: int = 3
    ) -> List[str]:
        """
        Process multiple segments in ONE API call to save credits.
        
        Instead of 240 calls for a 24-min video, we batch 10 segments per call = 24 calls.
        ~90% reduction in API credit usage.
        
        Args:
            video_no: The video ID
            batch_segments: List of (start_time, end_time) tuples
            story_context: Full story summary for context
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            List of narration strings, one per segment
        """
        # Build segment list for prompt
        segment_text = "\n".join([
            f"Segment {i+1}: {s:.1f}s to {e:.1f}s ({e-s:.1f}s duration)"
            for i, (s, e) in enumerate(batch_segments)
        ])
        
        # Calculate word limits per segment
        word_limits = [max(10, int((e - s) * 2.5)) for s, e in batch_segments]
        avg_word_limit = sum(word_limits) // len(word_limits)
        
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        # Chronological factual narrator prompt for batch
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Convert scene descriptions into continuous story flow.\n\n"
            f"{context_info}"
            f"SCENES to narrate:\n{segment_text}\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence they appear in video\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character'\n"
            f"7. TIME MARKERS: Use exact timestamps for major scene changes\n"
            f"8. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone'\n"
            f"9. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context\n"
            f"10. ~{avg_word_limit} words per segment.\n\n"
            f"❌ BAD: 'Realizing the gravity of the situation, Yuji suddenly decides...'\n"
            f"✅ GOOD: 'Yuji decides to fight the curse at minute 12.'\n\n"
            f"Return a JSON array with one narration string per segment:\n"
            f"[\"narration 1\", \"narration 2\", ...]\n\n"
            f"JSON array:"
        )
        
        print(f"📦 Batch request: {len(batch_segments)} segments in one call", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Batch chat failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Batch chat failed: {msg}")
                    
                    # Parse response
                    raw_response = result.get("data", {}).get("content", "")
                    
                    # Try to extract JSON array from response
                    narrations = self._parse_batch_response(raw_response, len(batch_segments))
                    
                    print(f"✅ Batch success: got {len(narrations)} narrations", flush=True)
                    return narrations
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # If batch fails, raise exception
        print(f"❌ Batch failed after {max_retries} retries", flush=True)
        raise Exception(f"Batch narration generation failed after {max_retries} retries")
    
    def _parse_batch_response(self, raw_response: str, expected_count: int) -> List[str]:
        """
        Parse the JSON array response from batch narration request.
        Falls back to splitting by newlines if JSON parsing fails.
        """
        import json
        import re
        
        # Try to find JSON array in response
        try:
            # Look for JSON array pattern
            json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
            if json_match:
                narrations = json.loads(json_match.group())
                if isinstance(narrations, list) and len(narrations) == expected_count:
                    return [str(n) for n in narrations]
        except json.JSONDecodeError:
            pass
        
        # Fallback: try to split by numbered segments
        lines = raw_response.strip().split('\n')
        narrations = []
        for line in lines:
            # Remove segment numbers like "1. " or "Segment 1: "
            cleaned = re.sub(r'^(\d+[\.\):]?\s*|Segment\s*\d+:\s*)', '', line.strip())
            if cleaned and not cleaned.startswith('[') and not cleaned.startswith('{'):
                narrations.append(cleaned)
        
        if len(narrations) >= expected_count:
            return narrations[:expected_count]
        
        # Fail fast instead of returning garbage
        print(f"❌ Batch parsing failed: only got {len(narrations)}/{expected_count} narrations", flush=True)
        print(f"❌ Raw response: {raw_response[:500]}...", flush=True)
        raise Exception(f"Batch parsing failed: only got {len(narrations)}/{expected_count} narrations")
    
    async def get_transcription(
        self,
        video_no: str,
        unique_id: str = "default"
    ) -> List[dict]:
        """
        Get the video transcription with timestamps (visual/OCR based).
        
        Args:
            video_no: The video ID
            unique_id: Workspace/user identifier
            
        Returns:
            List of transcription segments with timestamps
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/get_video_transcription",
                headers=self.headers,
                params={
                    "video_no": video_no,
                    "unique_id": unique_id
                }
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") != "0000":
                raise Exception(f"Transcription failed: {result.get('msg')}")
            
            return result.get("data", {}).get("transcriptions", [])
    
    async def get_audio_transcription(
        self,
        video_no: str,
        unique_id: str = "default",
        max_retries: int = 3
    ) -> List[dict]:
        """
        Get direct audio transcription with precise timestamps.
        
        API: GET /serve/api/v1/get_audio_transcription
        
        This provides accurate audio-to-text transcription directly from the audio track,
        which is more reliable than AI-inferred dialogue from Chat API.
        
        Args:
            video_no: The video ID from Memories.ai
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            List of transcription segments with start, end, text
            Format: [
                {
                    "text": "Transcription text...",
                    "start": 0.0,
                    "end": 8.0,
                    "speaker": "Speaker 1" (if speaker recognition available)
                }
            ]
        """
        import json
        
        print(f"🎤 Getting audio transcription for {video_no}...", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.get(
                        f"{self.base_url}/get_audio_transcription",
                        headers=self.headers,
                        params={
                            "video_no": video_no,
                            "unique_id": unique_id
                        }
                    )
                    
                    print(f"📥 Audio transcription response: {response.status_code}", flush=True)
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    # 🔍 PRINT FULL RESPONSE JSON FOR DEBUGGING
                    print(f"\n{'='*80}", flush=True)
                    print(f"📥 FULL AUDIO TRANSCRIPTION API RESPONSE:", flush=True)
                    print(f"{'='*80}", flush=True)
                    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
                    print(f"{'='*80}\n", flush=True)
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "Unknown error")
                        print(f"⚠️ Audio transcription error (attempt {attempt + 1}): {msg}", flush=True)
                        
                        # Retry on transient errors
                        if "network" in msg.lower() or "busy" in msg.lower() or "try again" in msg.lower():
                            last_error = Exception(f"Audio transcription failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        
                        raise Exception(f"Audio transcription failed: {msg}")
                    
                    # Extract transcription data
                    data = result.get("data", {})
                    
                    # Check different possible response structures
                    transcriptions = data.get("transcriptions", [])
                    if not transcriptions:
                        # Try alternative field names
                        transcriptions = data.get("transcription", [])
                    if not transcriptions and isinstance(data, list):
                        transcriptions = data
                    
                    if not transcriptions:
                        print(f"⚠️ No transcription data in response", flush=True)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(5)
                            continue
                        return []
                    
                    # Normalize transcription format
                    normalized = []
                    for item in transcriptions:
                        if isinstance(item, dict):
                            # Handle different possible field names
                            text = item.get("text") or item.get("content") or item.get("transcription", "")
                            start = item.get("startTime") or item.get("start") or item.get("start_time", 0)
                            end = item.get("endTime") or item.get("end") or item.get("end_time", 0)
                            speaker = item.get("speaker") or item.get("speakerLabel") or item.get("speaker_label")
                            
                            # Convert string timestamps to float if needed
                            if isinstance(start, str):
                                start = float(start) if start.replace('.', '').isdigit() else 0.0
                            if isinstance(end, str):
                                end = float(end) if end.replace('.', '').isdigit() else 0.0
                            
                            if text:
                                normalized.append({
                                    "text": str(text).strip(),
                                    "start": float(start),
                                    "end": float(end),
                                    "speaker": str(speaker) if speaker else None
                                })
                    
                    if normalized:
                        # Log summary
                        speakers = set(seg.get("speaker") for seg in normalized if seg.get("speaker"))
                        print(f"✅ Got {len(normalized)} audio transcription segments", flush=True)
                        if speakers:
                            print(f"   Speakers detected: {len(speakers)} ({', '.join(sorted(speakers)[:5])}{'...' if len(speakers) > 5 else ''})", flush=True)
                        else:
                            print(f"   ⚠️ No speaker labels in transcription (may need speaker recognition mode)", flush=True)
                        
                        # Log first few segments for debugging
                        for i, seg in enumerate(normalized[:3]):
                            speaker_label = f" [{seg['speaker']}]" if seg.get('speaker') else ""
                            print(f"   [{i+1}] {seg['start']:.1f}s-{seg['end']:.1f}s{speaker_label}: \"{seg['text'][:50]}...\"", flush=True)
                        
                        return normalized
                    else:
                        print(f"⚠️ Could not normalize transcription data, retrying...", flush=True)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(5)
                            continue
                        return []
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                if "Audio transcription failed" in str(e):
                    raise
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        print(f"⚠️ Audio transcription failed after {max_retries} retries", flush=True)
        if last_error:
            raise last_error
        return []
    
    async def map_speakers_to_characters(
        self,
        video_no: str,
        audio_transcript: List[dict],
        unique_id: str = "default"
    ) -> dict:
        """
        Map generic speaker labels (Speaker 1, Speaker 2) to actual character names.
        
        Uses Video Chat API to analyze the video and identify who each speaker is
        based on visual context and dialogue content.
        
        Args:
            video_no: The video ID
            audio_transcript: List of transcription segments with speaker labels
            unique_id: Workspace/user identifier
            
        Returns:
            Dict mapping speaker labels to character names:
            {
                "Speaker 1": "Dek",
                "Speaker 2": "Thea",
                ...
            }
        """
        import json
        
        print(f"🎭 Mapping speakers to character names...", flush=True)
        
        # Extract unique speakers and sample dialogue for each
        speakers = {}
        for seg in audio_transcript[:100]:  # Limit to first 100 segments for prompt size
            speaker = seg.get("speaker")
            if speaker and speaker not in speakers:
                speakers[speaker] = []
            
            if speaker and seg.get("text"):
                speakers[speaker].append({
                    "text": seg.get("text", ""),
                    "start": seg.get("start", 0)
                })
        
        if not speakers:
            print(f"   ⚠️ No speakers to map", flush=True)
            return {}
        
        # Build prompt with sample dialogue for each speaker
        speaker_samples = []
        for speaker, samples in speakers.items():
            sample_texts = [s["text"] for s in samples[:5]]  # First 5 samples per speaker
            speaker_samples.append(f"{speaker}:\n" + "\n".join(f'  - "{text}"' for text in sample_texts))
        
        mapping_prompt = f"""Analyze this video and identify the character names for each speaker label.

SPEAKER DIALOGUE SAMPLES:
{chr(10).join(speaker_samples)}

TASK: Map each speaker label to their actual character name.

RULES:
1. Use actual character names from the video (names mentioned in dialogue, shown on screen, or from context)
2. If you can't determine a name, use a descriptive label like "Narrator", "Young Woman", "Old Man"
3. Be consistent - the same character should always get the same name

Return ONLY a JSON object mapping speaker labels to character names:
{{
  "Speaker 1": "Character Name",
  "Speaker 2": "Another Character",
  ...
}}

IMPORTANT: Return ONLY the JSON object, no other text."""
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat",
                    headers={
                        **self.headers,
                        "Content-Type": "application/json"
                    },
                    json={
                        "video_nos": [video_no],
                        "prompt": mapping_prompt,
                        "unique_id": unique_id
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                if result.get("code") != "0000":
                    msg = result.get("msg", "Unknown error")
                    print(f"   ⚠️ Speaker mapping failed: {msg}", flush=True)
                    return {}
                
                content = result.get("data", {}).get("content", "")
                if not content:
                    print(f"   ⚠️ Empty response from Video Chat", flush=True)
                    return {}
                
                # Parse JSON from response
                if "{" in content and "}" in content:
                    start_idx = content.find("{")
                    end_idx = content.rfind("}") + 1
                    json_str = content[start_idx:end_idx]
                    try:
                        mapping = json.loads(json_str)
                        if isinstance(mapping, dict):
                            print(f"   ✅ Mapped {len(mapping)} speakers", flush=True)
                            return mapping
                    except json.JSONDecodeError:
                        pass
                
                print(f"   ⚠️ Could not parse speaker mapping from response", flush=True)
                return {}
                
        except Exception as e:
            print(f"   ⚠️ Speaker mapping failed: {e}", flush=True)
            return {}
    
    async def get_dialogue_transcript(
        self,
        video_no: str,
        unique_id: str = "default",
        max_retries: int = 3
    ) -> List[dict]:
        """
        Get dialogue transcript with CHARACTER NAMES using the Chat API.
        
        Uses Memories.ai's Chat API to analyze the video and extract dialogue
        with actual character names (not generic "Speaker 1" labels). The Chat
        API can see both video (faces, context) and audio to infer who is speaking.
        
        Args:
            video_no: The video ID
            unique_id: Workspace/user identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            List of dialogue segments with character names:
            [
                {
                    "text": "Teach me the ways of magic.",
                    "start": 10.5,
                    "end": 12.0,
                    "speaker": "Doctor Strange"
                },
                {
                    "text": "You are not ready.",
                    "start": 12.0,
                    "end": 14.0,
                    "speaker": "The Ancient One"
                }
            ]
        """
        print(f"🎭 Getting dialogue transcript with character names for {video_no}...", flush=True)
        
        # Prompt designed to extract dialogue with character names
        prompt = """Provide a complete dialogue transcript of this video.

TASK: Extract ALL spoken dialogue and identify WHO is speaking using their CHARACTER NAME.

RULES:
1. Use actual character names, NOT "Speaker 1" or "Person A"
2. Identify characters from: faces shown, dialogue mentions, on-screen text/titles, context
3. If you can't determine a name, use a descriptive label like "Narrator" or "Young Woman"
4. Include timestamps for each line
5. Include ALL dialogue, not just main characters

FORMAT YOUR RESPONSE AS A JSON ARRAY:
[
  {"start": 0.0, "end": 2.5, "speaker": "Character Name", "text": "What they said"},
  {"start": 2.5, "end": 5.0, "speaker": "Another Character", "text": "Their response"}
]

IMPORTANT: Return ONLY the JSON array, no other text or explanation.
Start your response with [ and end with ]"""

        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    
                    print(f"📥 Dialogue transcript response: {response.status_code}", flush=True)
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Dialogue transcript failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Dialogue transcript failed: {msg}")
                    
                    # Extract the response content
                    content = result.get("data", {}).get("content", "")
                    
                    if not content:
                        print(f"⚠️ Empty response, retrying...", flush=True)
                        await asyncio.sleep(5)
                        continue
                    
                    # Parse the JSON response
                    dialogue = self._parse_dialogue_response(content)
                    
                    if dialogue:
                        # Count unique speakers
                        speakers = set(d["speaker"] for d in dialogue if d.get("speaker"))
                        print(f"✅ Got {len(dialogue)} dialogue lines with {len(speakers)} characters", flush=True)
                        
                        # Log first few for debugging
                        for i, seg in enumerate(dialogue[:5]):
                            text_preview = seg['text'][:40] + "..." if len(seg['text']) > 40 else seg['text']
                            print(f"    [{seg['speaker']}] {seg['start']:.1f}s: \"{text_preview}\"", flush=True)
                        if len(dialogue) > 5:
                            print(f"    ... and {len(dialogue) - 5} more lines", flush=True)
                        
                        return dialogue
                    else:
                        print(f"⚠️ Could not parse dialogue, retrying...", flush=True)
                        await asyncio.sleep(5)
                        continue
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                if "Dialogue transcript failed" in str(e):
                    raise
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        print(f"⚠️ Dialogue transcript failed after {max_retries} retries, returning empty", flush=True)
        return []  # Return empty list instead of raising - this is non-critical
    
    def _parse_dialogue_response(self, content: str) -> List[dict]:
        """
        Parse the Chat API response into structured dialogue segments.
        
        Handles various response formats:
        - Clean JSON array
        - JSON with markdown code blocks
        - Fallback text parsing
        
        Args:
            content: Raw response from Chat API
            
        Returns:
            List of dialogue dicts with text, start, end, speaker
        """
        import json
        import re
        
        # Clean up the response
        content = content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```"):
            # Remove ```json or ``` at start and ``` at end
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        
        # Try to find JSON array in the response
        try:
            # Look for JSON array pattern
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                dialogue = json.loads(json_match.group())
                if isinstance(dialogue, list) and len(dialogue) > 0:
                    # Normalize the format
                    normalized = []
                    for item in dialogue:
                        if isinstance(item, dict) and item.get("text"):
                            normalized.append({
                                "text": str(item.get("text", "")),
                                "start": float(item.get("start", 0)),
                                "end": float(item.get("end", item.get("start", 0) + 2)),
                                "speaker": str(item.get("speaker", "Unknown"))
                            })
                    return normalized
        except json.JSONDecodeError:
            pass
        
        # Fallback: Try to parse line-by-line format
        # Format: [0:15] Character Name: "Dialogue"
        dialogue = []
        lines = content.split('\n')
        
        timestamp_pattern = r'\[?(\d+(?::\d+)?(?:\.\d+)?)\]?\s*'
        speaker_pattern = r'([^:]+):\s*["\']?(.+?)["\']?\s*$'
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Try to extract timestamp
            ts_match = re.match(timestamp_pattern, line)
            start_time = 0.0
            if ts_match:
                ts_str = ts_match.group(1)
                line = line[ts_match.end():]
                
                # Parse timestamp (could be "90.5" or "1:30" or "1:30.5")
                try:
                    if ':' in ts_str:
                        parts = ts_str.split(':')
                        if len(parts) == 2:
                            start_time = float(parts[0]) * 60 + float(parts[1])
                        elif len(parts) == 3:
                            start_time = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    else:
                        start_time = float(ts_str)
                except ValueError:
                    pass
            
            # Try to extract speaker and text
            speaker_match = re.match(speaker_pattern, line)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                text = speaker_match.group(2).strip()
                
                if text and speaker:
                    dialogue.append({
                        "text": text,
                        "start": start_time,
                        "end": start_time + 3.0,  # Estimate 3s per line
                        "speaker": speaker
                    })
        
        return dialogue
    
    async def search_video(
        self,
        query: str,
        video_nos: Optional[List[str]] = None,
        unique_id: str = "default",
        top_k: int = 10
    ) -> List[dict]:
        """
        Search within uploaded videos.
        
        Args:
            query: Natural language search query
            video_nos: Optional list of video IDs to search within
            unique_id: Workspace/user identifier
            top_k: Number of results to return
            
        Returns:
            List of search results with timestamps
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = {
                "search_param": query,
                "search_type": "BY_VIDEO",
                "unique_id": unique_id,
                "top_k": top_k
            }
            
            if video_nos:
                payload["video_nos"] = video_nos
            
            response = await client.post(
                f"{self.base_url}/search",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") != "0000":
                raise Exception(f"Search failed: {result.get('msg')}")
            
            return result.get("data", [])
    
    async def search_video_windowed(
        self,
        query: str,
        video_no: str,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        unique_id: str = "default",
        top_k: int = 10,
        min_confidence: float = 0.0
    ) -> List[dict]:
        """
        Search within a specific time window of a video.
        
        This is Layer A of the Visual Hunter - constrained semantic search.
        
        Args:
            query: Natural language search query
            video_no: Video ID to search within
            time_start: Start of search window (seconds)
            time_end: End of search window (seconds)
            unique_id: Workspace/user identifier
            top_k: Number of results to return
            min_confidence: Minimum confidence score (0-1) to accept results
            
        Returns:
            List of search results within the time window, sorted by confidence
        """
        # First, get all search results
        all_results = await self.search_video(
            query=query,
            video_nos=[video_no],
            unique_id=unique_id,
            top_k=top_k * 3  # Get more results to filter
        )
        
        if not all_results:
            return []
        
        # Filter by time window if specified
        filtered = []
        for result in all_results:
            result_start = float(result.get("start", result.get("start_time", 0)))
            result_end = float(result.get("end", result.get("end_time", result_start + 5)))
            confidence = float(result.get("score", result.get("confidence", 0.5)))
            
            # Check time window
            in_window = True
            if time_start is not None and result_end < time_start:
                in_window = False
            if time_end is not None and result_start > time_end:
                in_window = False
            
            # Check confidence
            if confidence < min_confidence:
                continue
            
            if in_window:
                # Add normalized confidence score
                result["confidence"] = confidence
                filtered.append(result)
        
        # Sort by confidence (highest first)
        filtered.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return filtered[:top_k]
    
    async def search_video_keywords(
        self,
        keywords: List[str],
        video_no: str,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        unique_id: str = "default",
        top_k: int = 5
    ) -> List[dict]:
        """
        Search using simplified keywords (Layer B of Visual Hunter).
        
        Fallback when semantic search fails - uses simpler keyword-based query.
        
        Args:
            keywords: List of keywords to search for
            video_no: Video ID to search within
            time_start: Start of search window (seconds)
            time_end: End of search window (seconds)
            unique_id: Workspace/user identifier
            top_k: Number of results to return
            
        Returns:
            List of search results
        """
        # Build keyword query
        keyword_query = ", ".join(keywords)
        
        return await self.search_video_windowed(
            query=keyword_query,
            video_no=video_no,
            time_start=time_start,
            time_end=time_end,
            unique_id=unique_id,
            top_k=top_k,
            min_confidence=0.0  # Accept any match for keywords
        )
    
    async def delete_video(
        self,
        video_no: str,
        unique_id: str = "default"
    ) -> bool:
        """
        Delete a video from Memories.ai.
        
        Args:
            video_no: The video ID to delete
            unique_id: Workspace/user identifier
            
        Returns:
            True if deletion was successful
        """
        import json
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Use request() method since delete() doesn't support json parameter
            response = await client.request(
                "DELETE",
                f"{self.base_url}/delete_videos",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                content=json.dumps({
                    "video_nos": [video_no],
                    "unique_id": unique_id
                })
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get("code") == "0000"

    async def generate_summary(
        self, 
        video_no: str, 
        unique_id: str = "default",
        summary_type: str = "CHAPTER"
    ) -> List[dict]:
        """
        Get structured video summary with timestamps.
        
        Uses Memories.ai's generate_summary endpoint to get pre-grouped
        segments (chapters or topics) with accurate timestamps.
        
        API: GET /serve/api/v1/generate_summary
        Host: https://api.memories.ai
        
        Args:
            video_no: The video ID from Memories.ai (must be in PARSE status)
            unique_id: Workspace identifier (default: "default")
            summary_type: "CHAPTER" for scene-based or "TOPIC" for semantic clusters
            
        Returns:
            List of segments with title, start, end, description fields
            Example: [
                {
                    "title": "Introduction",
                    "start": 0.0,
                    "end": 90.5, 
                    "description": "Character enters the room and looks around."
                },
                ...
            ]
        """
        print(f"📖 Fetching {summary_type} summary for {video_no}...", flush=True)

        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                # Use /serve/api/v1/generate_summary endpoint
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.get(
                        f"{self.base_url}/generate_summary",
                        headers=self.headers,
                        params={
                            "video_no": video_no,
                            "type": summary_type,
                            "unique_id": unique_id,
                        },
                    )

                print(f"📥 Summary response: {response.status_code}", flush=True)

                if response.status_code != 200:
                    print(f"❌ Summary failed: {response.text}", flush=True)
                    if attempt < max_retries - 1:
                        print(
                            f"⏳ Retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})",
                            flush=True,
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    return []

                result = response.json()
                print(f"📥 Summary body: {str(result)[:500]}", flush=True)

                # API-level error handling (Memories.ai style: code/msg)
                error_code = result.get("code")
                error_msg = result.get("msg", "") or ""
                if error_code and error_code != "0000":
                    print(f"❌ Summary error (code {error_code}): {error_msg}", flush=True)
                    is_temporary = (
                        "network" in error_msg.lower()
                        or "try again" in error_msg.lower()
                        or error_code in {"0001", "0429"}
                    )
                    if is_temporary and attempt < max_retries - 1:
                        print(
                            f"⏳ Temporary API error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})",
                            flush=True,
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    return []

                data = result.get("data", {}) or {}
                segments = data.get("items") or data.get("chapters") or []

                if not segments:
                    print(
                        f"❌ No segments found in response. Data keys: {list(data.keys()) if data else 'None'}",
                        flush=True,
                    )
                    return []

                print(f"✅ Got {len(segments)} segments", flush=True)
                for i, seg in enumerate(segments[:3]):
                    if isinstance(seg, dict):
                        print(
                            f"    [{i+1}] {seg.get('start', '?')}s: {str(seg.get('title', 'Untitled'))[:40]}",
                            flush=True,
                        )
                    else:
                        print(f"    [{i+1}] Unexpected segment type: {type(seg)}", flush=True)

                return segments

            except Exception as e:
                print(f"❌ Summary request failed: {e}", flush=True)
                if attempt < max_retries - 1:
                    print(
                        f"⏳ Retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})",
                        flush=True,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                return []

        return []

    async def identify_characters(
        self, 
        video_no: str, 
        unique_id: str = "default",
        max_retries: int = 3
    ) -> str:
        """
        Ask Memories.ai to identify and name the main characters in the video.
        
        Uses the chat endpoint to analyze the video and extract character
        information, providing a character guide for the narration rewriter.
        
        Args:
            video_no: The video ID from Memories.ai
            unique_id: Workspace identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            Character guide string formatted as:
            "Bald woman in yellow robes = The Ancient One
            Man with goatee = Doctor Strange (Stephen Strange)
            Bald man with dark markings = Kaecilius"
            
            Returns empty string if identification fails.
        """
        prompt = """
Analyze this video and identify ALL main characters that appear.

For EACH character, provide:
1. A brief physical description (hair color, clothing, distinguishing features)
2. Their name if mentioned in dialogue, visible text, or if you recognize them

Format your response EXACTLY as:
[Physical Description] = [Character Name]

Examples:
Bald woman in yellow robes = The Ancient One
Man with goatee and grey temples = Doctor Strange
Young woman with brown hair = Christine Palmer

RULES:
- One character per line
- If you don't know a character's name, use a descriptive label like "Mysterious Woman" or "Young Hero"
- Include ALL characters that have speaking roles or significant screen time
- Be specific about physical features to help distinguish characters

List ALL characters now:
"""
        
        print(f"🎭 Identifying characters in video {video_no}...", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Character identification failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        print(f"⚠️ Character identification error: {msg}", flush=True)
                        return ""
                    
                    content = result.get("data", {}).get("content", "")
                    
                    if content:
                        # Clean up the response - extract just the character lines
                        lines = []
                        for line in content.strip().split("\n"):
                            line = line.strip()
                            # Only keep lines that look like "Description = Name"
                            if "=" in line and len(line) > 5:
                                lines.append(line)
                        
                        character_guide = "\n".join(lines)
                        
                        if character_guide:
                            print(f"🎭 Identified {len(lines)} characters:", flush=True)
                            for line in lines[:5]:  # Log first 5
                                print(f"    {line}", flush=True)
                            if len(lines) > 5:
                                print(f"    ... and {len(lines) - 5} more", flush=True)
                            return character_guide
                        else:
                            print(f"⚠️ No character mappings found in response", flush=True)
                            return ""
                    
                    print(f"⚠️ Empty response from character identification", flush=True)
                    return ""
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        print(f"❌ Character identification failed after {max_retries} retries", flush=True)
        return ""

    async def get_plot_summary(
        self, 
        video_no: str, 
        unique_id: str = "default",
        max_retries: int = 3
    ) -> str:
        """
        Ask Memories.ai to generate a comprehensive plot summary of the entire video.
        
        Uses the chat endpoint to analyze the full video and extract plot information,
        including character arcs, deaths, major events, and story structure.
        
        Args:
            video_no: The video ID from Memories.ai
            unique_id: Workspace identifier
            max_retries: Number of retries for transient errors
            
        Returns:
            Plot summary string containing:
            - Main characters and their roles
            - Character arcs (who dies, who survives, transformations)
            - Villain/antagonist identification
            - Major plot points and twists
            - Story ending
            
            Returns empty string if summary generation fails.
        """
        prompt = """
Analyze this entire video and provide a comprehensive plot summary.

Include the following information:

1. MAIN CHARACTERS:
   - List all main characters and their roles (hero, villain, mentor, etc.)
   - Describe their relationships to each other

2. CHARACTER ARCS:
   - What happens to each main character throughout the story?
   - Who dies? When and how?
   - Who survives?
   - Any character transformations or major changes?

3. VILLAIN/ANTAGONIST:
   - Who is the main villain or antagonist?
   - What is their goal or motivation?

4. MAJOR PLOT POINTS:
   - What are the key events in the story?
   - Any major twists or revelations?
   - What is the climax of the story?

5. ENDING:
   - How does the story end?
   - What is the resolution?

Format your response as a clear, structured summary that can be used as story context for narration.
Be specific about character deaths, relationships, and plot progression.
"""
        
        print(f"📖 Generating plot summary for video {video_no}...", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Plot summary failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        print(f"⚠️ Plot summary error: {msg}", flush=True)
                        return ""
                    
                    content = result.get("data", {}).get("content", "")
                    
                    if content:
                        # Clean up the response
                        plot_summary = content.strip()
                        
                        if plot_summary:
                            # Log first few lines for debugging
                            lines = plot_summary.split("\n")[:10]
                            print(f"📖 Generated plot summary ({len(plot_summary)} chars):", flush=True)
                            for line in lines:
                                if line.strip():
                                    print(f"    {line[:80]}...", flush=True)
                            if len(plot_summary.split("\n")) > 10:
                                print(f"    ... and more", flush=True)
                            return plot_summary
                        else:
                            print(f"⚠️ Empty plot summary in response", flush=True)
                            return ""
                    
                    print(f"⚠️ Empty response from plot summary", flush=True)
                    return ""
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        print(f"❌ Plot summary failed after {max_retries} retries", flush=True)
        return ""

    async def identify_key_moments(
        self,
        video_no: str,
        chapters: List[dict],
        unique_id: str = "default",
        max_clips: int = 5,
        max_retries: int = 3
    ) -> List[dict]:
        """
        Use Chat API to identify important dialogue moments from chapters.
        
        Passes chapter data to Chat API so it can pick moments that:
        - Are emotionally powerful
        - Contain plot revelations or twists
        - Have iconic/memorable lines
        - Are better heard in actor's voice than narrated
        
        Args:
            video_no: The video ID from Memories.ai
            chapters: List of chapter dicts from generate_summary
            unique_id: Workspace identifier
            max_clips: Maximum number of key moments to identify
            max_retries: Number of retries for transient errors
            
        Returns:
            List of key moment dicts with timestamps guaranteed within chapter ranges:
            [
                {
                    "chapter_index": 1,
                    "start": 95.2,
                    "end": 98.5,
                    "speaker": "Character Name",
                    "dialogue": "The exact line",
                    "importance": "Why this matters",
                    "lead_in": "And then Character reveals..."
                }
            ]
        """
        import json
        
        print(f"🎬 Identifying key moments for original audio (max {max_clips})...", flush=True)
        
        # Format chapters for the prompt
        chapters_json = json.dumps(chapters, indent=2, default=str)
        
        prompt = f"""Analyze this video and identify the {max_clips} most IMPORTANT dialogue moments that should play as original audio instead of narration.

Here are the chapters from this video:
{chapters_json}

TASK: Select the most impactful dialogue moments where hearing the ORIGINAL ACTOR'S VOICE would be more powerful than a narrator describing it.

CRITERIA for selection:
- Emotionally powerful moments (confessions, revelations, confrontations)
- Plot-critical dialogue (twists, reveals, character deaths)
- Iconic or memorable lines
- Moments where tone/delivery matters (whispers, screams, emotional breaks)

For EACH key moment, provide:
1. chapter_index: Which chapter (0-based index) contains this moment
2. start: Exact start timestamp in seconds (must be WITHIN the chapter's time range)
3. end: Exact end timestamp in seconds (must be WITHIN the chapter's time range)
4. speaker: Who is speaking (character name)
5. dialogue: The exact words spoken
6. importance: Brief explanation of why this moment matters
7. lead_in: A narrator lead-in phrase like "And then [Name] reveals the truth..." or "In that moment, [Name] speaks..."

IMPORTANT:
- The start/end timestamps MUST fall within the chapter's start/end range
- Keep each clip SHORT (2-8 seconds) - just the key line, not long conversations
- Pick at most {max_clips} moments total
- If no dialogue is important enough, return an empty array

Return ONLY a JSON array, no other text:
[
  {{
    "chapter_index": 1,
    "start": 95.2,
    "end": 98.5,
    "speaker": "Character Name",
    "dialogue": "I am your father",
    "importance": "Major plot revelation",
    "lead_in": "And then Vader speaks the words that change everything..."
  }}
]

Start with [ and end with ]"""

        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    
                    print(f"📥 Key moments response: {response.status_code}", flush=True)
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}/{max_retries}): {msg}", flush=True)
                            last_error = Exception(f"Key moments failed: {msg}")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Key moments failed: {msg}")
                    
                    content = result.get("data", {}).get("content", "")
                    
                    if not content:
                        print(f"⚠️ Empty response, retrying...", flush=True)
                        await asyncio.sleep(5)
                        continue
                    
                    # Parse the JSON response
                    key_moments = self._parse_key_moments_response(content, chapters)
                    
                    if key_moments:
                        print(f"✅ Identified {len(key_moments)} key moments for original audio:", flush=True)
                        for i, moment in enumerate(key_moments):
                            print(f"    {i+1}. [{moment['speaker']}] {moment['start']:.1f}s-{moment['end']:.1f}s: \"{moment['dialogue'][:40]}...\"", flush=True)
                        return key_moments
                    else:
                        print(f"⚠️ No key moments identified or could not parse response", flush=True)
                        return []
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                if "Key moments failed" in str(e):
                    raise
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        print(f"⚠️ Key moments identification failed after {max_retries} retries, returning empty", flush=True)
        return []
    
    def _parse_key_moments_response(self, content: str, chapters: List[dict]) -> List[dict]:
        """
        Parse the Chat API response for key moments.
        
        Validates that timestamps fall within chapter ranges.
        
        Args:
            content: Raw response from Chat API
            chapters: Original chapter list for validation
            
        Returns:
            List of validated key moment dicts
        """
        import json
        import re
        
        # Try to extract JSON array from response
        content = content.strip()
        
        # Find JSON array in response
        json_match = re.search(r'\[[\s\S]*\]', content)
        if not json_match:
            print(f"⚠️ No JSON array found in key moments response", flush=True)
            return []
        
        try:
            moments = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parse error in key moments: {e}", flush=True)
            return []
        
        if not isinstance(moments, list):
            return []
        
        # Validate and clean each moment
        validated_moments = []
        
        for moment in moments:
            if not isinstance(moment, dict):
                continue
            
            # Required fields
            chapter_idx = moment.get("chapter_index")
            start = moment.get("start")
            end = moment.get("end")
            speaker = moment.get("speaker", "Unknown")
            dialogue = moment.get("dialogue", "")
            importance = moment.get("importance", "")
            lead_in = moment.get("lead_in", f"And then {speaker} says...")
            
            # Validate chapter index
            if chapter_idx is None or not isinstance(chapter_idx, int):
                continue
            if chapter_idx < 0 or chapter_idx >= len(chapters):
                print(f"⚠️ Invalid chapter_index {chapter_idx}, skipping moment", flush=True)
                continue
            
            # Validate timestamps
            try:
                start = float(start)
                end = float(end)
            except (TypeError, ValueError):
                continue
            
            if end <= start:
                continue
            
            # Validate timestamps are within chapter range
            chapter = chapters[chapter_idx]
            chapter_start = self._parse_timestamp(chapter.get("start", 0))
            chapter_end = self._parse_timestamp(chapter.get("end", 0))
            
            # Allow some tolerance (1 second) for edge cases
            if start < chapter_start - 1 or end > chapter_end + 1:
                print(f"⚠️ Moment timestamps {start:.1f}-{end:.1f} outside chapter range {chapter_start:.1f}-{chapter_end:.1f}, adjusting", flush=True)
                # Clamp to chapter range
                start = max(start, chapter_start)
                end = min(end, chapter_end)
                if end <= start:
                    continue
            
            # Ensure clip isn't too long (max 15 seconds)
            if end - start > 15:
                end = start + 15
            
            validated_moments.append({
                "chapter_index": chapter_idx,
                "start": start,
                "end": end,
                "speaker": speaker,
                "dialogue": dialogue,
                "importance": importance,
                "lead_in": lead_in
            })
        
        return validated_moments
    
    def _parse_timestamp(self, time_val) -> float:
        """Parse various timestamp formats to float seconds."""
        if isinstance(time_val, (int, float)):
            return float(time_val)
        
        if not time_val:
            return 0.0
        
        time_str = str(time_val).strip()
        
        # Try direct float
        try:
            return float(time_str)
        except ValueError:
            pass
        
        # Parse MM:SS or HH:MM:SS
        parts = time_str.split(":")
        try:
            if len(parts) == 3:
                h, m, s = parts
                return float(h) * 3600 + float(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return float(m) * 60 + float(s)
        except (ValueError, TypeError):
            pass
        
        return 0.0
    
    async def extract_structured_movie_data(
        self,
        video_no: str,
        chapters: List[dict],
        unique_id: str = "default",
        max_retries: int = 3
    ) -> dict:
        """
        Extract structured movie data in a SINGLE API call.
        
        This extracts:
        - Main characters with names, species/type, and roles
        - Key locations in the movie
        - Important relationships between characters
        
        This data is then used to improve narration consistency.
        
        Args:
            video_no: The video ID from Memories.ai
            chapters: List of chapter dicts (used to understand movie scope)
            unique_id: Workspace/user identifier
            max_retries: Number of retries for failed calls
            
        Returns:
            Dict with structured movie data:
            {
                "characters": [{"name": "Dek", "type": "Yautja", "role": "Hunter protagonist"}],
                "locations": ["Yautja Prime", "Planet Gena", "Weyland-Yutani Lab"],
                "relationships": ["Dek captures Thea", "Tessa works for Weyland-Yutani"],
                "factions": ["Yautja Clan", "Weyland-Yutani Corporation", "Humans"]
            }
        """
        import json
        
        print(f"🎬 Extracting structured movie data from video...", flush=True)
        
        # Build a detailed chapter list with timestamps for scene mapping
        chapter_list = []
        for i, ch in enumerate(chapters):
            start = ch.get("start", "0:00")
            end = ch.get("end", "0:00")
            title = ch.get("title", f"Chapter {i+1}")
            desc = ch.get("description", "") or ch.get("summary", "")
            chapter_list.append(f"Chapter {i+1} [{start}-{end}]: {desc[:200]}")
        
        chapters_context = "\n".join(chapter_list)
        
        extraction_prompt = f"""Analyze this video and extract structured data. Focus on ACTUAL NAMES, not descriptions.

CHAPTERS:
{chapters_context}

Return ONLY valid JSON:

{{
  "title": "Movie title",
  "characters": [
    {{"name": "Dek", "type": "Yautja", "role": "Hunter", "appearance": "Tribal markings, dreadlocks"}},
    {{"name": "Thea", "type": "Human", "role": "Survivor", "appearance": "Blonde hair"}},
    {{"name": "Tessa", "type": "Synthetic", "role": "Operative", "appearance": "Pale skin"}}
  ],
  "locations": [
    {{"name": "Yautja Prime", "description": "Alien homeworld"}},
    {{"name": "Planet Gena", "description": "Hostile desert planet"}},
    {{"name": "Weyland-Yutani Lab", "description": "Corporate facility"}}
  ],
  "factions": [
    {{"name": "Yautja Clan", "members": ["Dek", "Kwei"]}},
    {{"name": "Weyland-Yutani", "members": ["Tessa"]}}
  ],
  "scenes": [
    {{"chapter": 1, "location": "Yautja Prime", "characters_present": ["Dek"], "action": "Receives mission"}},
    {{"chapter": 5, "location": "Planet Gena", "characters_present": ["Thea", "Tessa"], "action": "Arrives on planet"}}
  ],
  "plot_summary": "Brief plot"
}}

🚨 CRITICAL - USE ACTUAL NAMES, NOT DESCRIPTIONS:

❌ BAD location names (DO NOT USE):
- "Desolate Landscape" → Use actual planet name like "Planet Gena"
- "Rocky Terrain" → Use actual place name
- "Forest Area" → Use "Jungle of Gena" or actual name
- "Dark Environment" → Use "Yautja Ship" or actual location

✅ GOOD location names:
- "Yautja Prime" (planet name)
- "Planet Gena" (planet name)  
- "Weyland-Yutani Lab" (facility name)
- "The Hive" (specific place)

❌ BAD character references (DO NOT USE):
- "A figure" / "The warrior" / "The protagonist"
- "Someone" / "A creature" / "The hunter"

✅ GOOD character names:
- "Dek" / "Thea" / "Tessa" / "Kwei" / "Gena"
- Use names from dialogue or credits

For LOCATIONS: Use proper nouns (planet names, facility names) NOT visual descriptions.
For CHARACTERS: Use actual names heard in dialogue or shown in credits.

Return ONLY the JSON."""

        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Prepare request payload
                request_payload = {
                    "video_nos": [video_no],
                    "prompt": extraction_prompt,
                    "unique_id": unique_id
                }
                
                # 🔍 PRINT REQUEST JSON
                print(f"\n{'='*80}", flush=True)
                print(f"📤 VIDEO CHAT REQUEST JSON (Structured Data Extraction):", flush=True)
                print(f"{'='*80}", flush=True)
                print(json.dumps(request_payload, indent=2, ensure_ascii=False), flush=True)
                print(f"{'='*80}\n", flush=True)
                
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json=request_payload
                    )
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    # 🔍 PRINT FULL RESPONSE JSON
                    print(f"\n{'='*80}", flush=True)
                    print(f"📥 FULL VIDEO CHAT RESPONSE JSON:", flush=True)
                    print(f"{'='*80}", flush=True)
                    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
                    print(f"{'='*80}\n", flush=True)
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "Unknown error")
                        print(f"⚠️ Extraction error (attempt {attempt + 1}): {msg}", flush=True)
                        last_error = Exception(msg)
                        await asyncio.sleep(3)
                        continue
                    
                    # Extract content from response
                    data = result.get("data", {})
                    content = data.get("content", "")
                    
                    # 🔍 PRINT RAW CONTENT (text response from AI)
                    print(f"\n{'='*80}", flush=True)
                    print(f"📝 RAW CONTENT FROM VIDEO CHAT:", flush=True)
                    print(f"{'='*80}", flush=True)
                    print(f"{content}", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    
                    if not content:
                        print(f"⚠️ Empty response from Video Chat", flush=True)
                        continue
                    
                    # Parse JSON from response
                    # Try to find JSON in the response (might have extra text)
                    json_match = None
                    if "{" in content and "}" in content:
                        start_idx = content.find("{")
                        end_idx = content.rfind("}") + 1
                        json_str = content[start_idx:end_idx]
                        try:
                            json_match = json.loads(json_str)
                            # 🔍 PRINT PARSED JSON
                            print(f"\n{'='*80}", flush=True)
                            print(f"✅ PARSED STRUCTURED DATA JSON:", flush=True)
                            print(f"{'='*80}", flush=True)
                            print(json.dumps(json_match, indent=2), flush=True)
                            print(f"{'='*80}\n", flush=True)
                        except json.JSONDecodeError as je:
                            print(f"⚠️ JSON parse error: {je}", flush=True)
                            pass
                    
                    if not json_match:
                        print(f"⚠️ Could not parse JSON from response: {content[:500]}", flush=True)
                        continue
                    
                    # Validate structure
                    structured_data = {
                        "title": json_match.get("title", "Unknown"),
                        "characters": json_match.get("characters", []),
                        "locations": json_match.get("locations", []),
                        "factions": json_match.get("factions", []),
                        "relationships": json_match.get("relationships", []),
                        "scenes": json_match.get("scenes", []),  # Scene-by-scene mapping
                        "plot_summary": json_match.get("plot_summary", "")
                    }
                    
                    # 🔍 PRINT FINAL STRUCTURED DATA OBJECT
                    print(f"\n{'='*80}", flush=True)
                    print(f"✅ FINAL STRUCTURED DATA OBJECT (Validated & Formatted):", flush=True)
                    print(f"{'='*80}", flush=True)
                    print(json.dumps(structured_data, indent=2, ensure_ascii=False), flush=True)
                    print(f"{'='*80}\n", flush=True)
                    
                    # Log summary
                    print(f"📊 Structured Data Summary:", flush=True)
                    print(f"   Title: {structured_data['title']}", flush=True)
                    print(f"   Characters: {len(structured_data['characters'])}", flush=True)
                    for char in structured_data['characters'][:5]:
                        print(f"      - {char.get('name', '?')}: {char.get('type', '?')} ({char.get('role', '?')})", flush=True)
                    print(f"   Locations: {len(structured_data['locations'])}", flush=True)
                    print(f"   Scenes mapped: {len(structured_data['scenes'])}", flush=True)
                    if structured_data['scenes']:
                        # Show first few scene mappings
                        for scene in structured_data['scenes'][:3]:
                            ch = scene.get('chapter', '?')
                            loc = scene.get('location', '?')
                            chars = ', '.join(scene.get('characters_present', [])[:2])
                            print(f"      Ch{ch}: {loc} [{chars}]", flush=True)
                    print(f"   Factions: {len(structured_data['factions'])}", flush=True)
                    
                    return structured_data
                    
            except Exception as e:
                print(f"❌ Extraction request failed (attempt {attempt + 1}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(3)
        
        # Return empty structure on failure (non-critical)
        print(f"⚠️ Could not extract structured data after {max_retries} attempts", flush=True)
        return {
            "title": "Unknown",
            "characters": [],
            "locations": [],
            "factions": [],
            "relationships": [],
            "scenes": [],
            "plot_summary": ""
        }
    
    def format_structured_data_for_prompt(
        self, 
        structured_data: dict,
        chapter_start: int = None,
        chapter_end: int = None
    ) -> str:
        """
        Format extracted structured data into a prompt section for narration.
        
        Args:
            structured_data: Dict from extract_structured_movie_data()
            chapter_start: Optional start chapter number (1-indexed) for scene context
            chapter_end: Optional end chapter number (1-indexed) for scene context
            
        Returns:
            Formatted string to include in narration prompts
        """
        if not structured_data or not structured_data.get("characters"):
            return ""
        
        sections = []
        
        # Title
        if structured_data.get("title") and structured_data["title"] != "Unknown":
            sections.append(f"MOVIE: {structured_data['title']}")
        
        # Characters
        if structured_data.get("characters"):
            char_lines = ["CHARACTERS (use these EXACT names):"]
            for char in structured_data["characters"]:
                name = char.get("name", "Unknown")
                char_type = char.get("type", "")
                role = char.get("role", "")
                appearance = char.get("appearance", "")
                
                line = f"• {name}"
                if char_type:
                    line += f" ({char_type})"
                if role:
                    line += f" - {role}"
                if appearance:
                    line += f" [{appearance}]"
                char_lines.append(line)
            sections.append("\n".join(char_lines))
        
        # Locations (with descriptions if available)
        if structured_data.get("locations"):
            loc_lines = ["LOCATIONS:"]
            for loc in structured_data["locations"][:8]:
                if isinstance(loc, dict):
                    name = loc.get("name", "Unknown")
                    desc = loc.get("description", "")
                    if desc:
                        loc_lines.append(f"• {name}: {desc}")
                    else:
                        loc_lines.append(f"• {name}")
                else:
                    loc_lines.append(f"• {loc}")
            sections.append("\n".join(loc_lines))
        
        # Factions
        if structured_data.get("factions"):
            faction_lines = ["FACTIONS:"]
            for faction in structured_data["factions"]:
                name = faction.get("name", "Unknown")
                members = faction.get("members", [])
                if members:
                    faction_lines.append(f"• {name}: {', '.join(members[:4])}")
                else:
                    faction_lines.append(f"• {name}")
            sections.append("\n".join(faction_lines))
        
        # Key relationships
        if structured_data.get("relationships"):
            rel_lines = ["KEY RELATIONSHIPS:"]
            for rel in structured_data["relationships"][:5]:
                rel_lines.append(f"• {rel}")
            sections.append("\n".join(rel_lines))
        
        # Scene-by-scene context for the specific chapters being processed
        if structured_data.get("scenes") and chapter_start is not None and chapter_end is not None:
            scene_lines = [f"SCENE CONTEXT FOR CHAPTERS {chapter_start}-{chapter_end}:"]
            scene_lines.append("(Use this to know WHO is on screen and WHERE the action takes place)")
            scene_lines.append("")
            
            for scene in structured_data["scenes"]:
                ch_num = scene.get("chapter", 0)
                # Check if this scene is in our chapter range
                if chapter_start <= ch_num <= chapter_end:
                    location = scene.get("location", "Unknown")
                    chars = scene.get("characters_present", [])
                    action = scene.get("action", "")
                    
                    chars_str = ", ".join(chars) if chars else "Unknown"
                    scene_lines.append(f"  Chapter {ch_num}:")
                    scene_lines.append(f"    📍 Location: {location}")
                    scene_lines.append(f"    👥 On screen: {chars_str}")
                    if action:
                        scene_lines.append(f"    🎬 Action: {action}")
                    scene_lines.append("")
            
            if len(scene_lines) > 3:  # Only add if we found relevant scenes
                sections.append("\n".join(scene_lines))
        
        if not sections:
            return ""
        
        return "═══════════════════════════════════════════════════════════════════\n" + \
               "📋 MOVIE DATA (extracted from video - USE THIS INFO):\n" + \
               "═══════════════════════════════════════════════════════════════════\n\n" + \
               "\n\n".join(sections) + "\n"
    
    async def rewrite_chapters_with_video_chat(
        self,
        video_no: str,
        chapters: List[dict],
        target_words_per_chapter: int = 45,
        unique_id: str = "default",
        max_retries: int = 3,
        batch_size: int = 20,
        structured_data: dict = None
    ) -> List[str]:
        """
        Use Video Chat to rewrite ALL chapter summaries into engaging narration.
        
        This is more accurate than using a text-only AI because Video Chat
        has actually seen the video and knows exactly what happens.
        
        Batches chapters to minimize API calls while staying within limits.
        
        Args:
            video_no: The video ID from Memories.ai
            chapters: List of chapter dicts with title, description/summary, start, end
            target_words_per_chapter: Target word count per chapter narration
            unique_id: Workspace/user identifier
            max_retries: Number of retries for failed calls
            batch_size: Number of chapters per API call (default 20)
            structured_data: Optional pre-extracted movie data (characters, locations, etc.)
            
        Returns:
            List of narration strings, one per chapter (in same order as input)
        """
        import json
        import re
        
        total_chapters = len(chapters)
        all_narrations = [""] * total_chapters  # Pre-allocate to maintain order
        
        # Track characters across batches for consistency (fallback if no structured data)
        character_roster = ""
        
        # Check if we have structured data with scene mapping
        has_structured_data = structured_data and (structured_data.get("characters") or structured_data.get("scenes"))
        if has_structured_data:
            print(f"📋 Using pre-extracted structured movie data for narration", flush=True)
            if structured_data.get("scenes"):
                print(f"   📍 Scene mapping available for {len(structured_data['scenes'])} chapters", flush=True)
        
        print(f"🎬 Rewriting {total_chapters} chapters using Video Chat (batch size: {batch_size})...", flush=True)
        
        # Process in batches
        for batch_start in range(0, total_chapters, batch_size):
            batch_end = min(batch_start + batch_size, total_chapters)
            batch_chapters = chapters[batch_start:batch_end]
            
            # Chapter numbers are 1-indexed
            chapter_start_num = batch_start + 1
            chapter_end_num = batch_end
            
            print(f"⚡ Processing chapters {chapter_start_num}-{chapter_end_num} with Video Chat...", flush=True)
            
            # Build the chapter list for the prompt
            chapter_list = []
            for i, ch in enumerate(batch_chapters):
                idx = batch_start + i + 1
                start = ch.get("start", "0:00")
                end = ch.get("end", "0:00")
                title = ch.get("title", f"Chapter {idx}")
                summary = ch.get("description", "") or ch.get("summary", "")
                chapter_list.append(f'{idx}. [{start}-{end}] "{title}": {summary}')
            
            chapters_text = "\n".join(chapter_list)
            
            # Build context section - prefer structured data with scene context for THIS batch
            context_section = ""
            if has_structured_data:
                # Use pre-extracted structured data with scene-specific context
                context_section = self.format_structured_data_for_prompt(
                    structured_data,
                    chapter_start=chapter_start_num,
                    chapter_end=chapter_end_num
                )
            elif character_roster and batch_start > 0:
                # Fallback: use character roster from first batch
                context_section = f"""
═══════════════════════════════════════════════════════════════════
📋 ESTABLISHED CHARACTERS (from previous chapters - USE THESE EXACT NAMES):
═══════════════════════════════════════════════════════════════════
{character_roster}

⚠️ CRITICAL: Continue using these EXACT character names for consistency!
Do NOT introduce new names for the same characters.
Do NOT use vague terms like "a figure" or "a creature" for characters already named above.

"""
            
            prompt = f"""You are a dramatic movie narrator for YouTube. Write IMMERSIVE narration that makes viewers feel like they're IN the story.

For EACH chapter, write {target_words_per_chapter}-{target_words_per_chapter + 10} words.
{context_section}

═══════════════════════════════════════════════════════════════════
⚠️ VISUAL ACCURACY - MOST IMPORTANT RULE:
═══════════════════════════════════════════════════════════════════

Your narration MUST match what's ACTUALLY HAPPENING on screen:
• DESCRIBE what you SEE in the video for this timestamp
• If someone is walking, say they're walking - not running
• If someone is talking, describe what they're saying
• If there's a fight, describe the fight as it happens
• Do NOT invent actions, emotions, or events not visible in the video

🚫 NEVER INVENT:
• Actions not shown: "He punches" when he's just standing
• Emotions not visible: "Fear fills her eyes" when her face is neutral
• Future events: "Little does he know..." (you don't know the future)
• Internal thoughts: "She wonders if..." (you can't read minds)

✅ STAY GROUNDED:
• Describe what's VISIBLE: movements, dialogue, expressions you can SEE
• Add drama through WORD CHOICE, not invented details
• Use the chapter timestamp to describe THAT SPECIFIC MOMENT

═══════════════════════════════════════════════════════════════════
🚫 IGNORE ON-SCREEN TEXT - DO NOT READ OR NARRATE:
═══════════════════════════════════════════════════════════════════

Do NOT narrate or describe ANY text on screen:
• Subtitles or closed captions - IGNORE completely
• Credits (actor names, "Directed by", studio logos) - SKIP
• Title cards or chapter titles - Don't read them
• Any text overlays on the video - Pretend they don't exist
• NEVER say "Text appears..." or "The subtitle says..."

Focus ONLY on the STORY and CHARACTERS, not text on screen.

❌ BAD: "Text appears: 'Three days earlier.' The scene shifts to a forest."
✅ GOOD: "Three days earlier. Thea arrives at the forest compound."

❌ BAD: "The credits roll, showing 'Starring John Smith as Dek'"
✅ GOOD: (Skip credits entirely - do not narrate them at all)

❌ BAD: "A subtitle reads 'Planet Gena' as the ship descends."
✅ GOOD: "The ship descends toward Planet Gena."

═══════════════════════════════════════════════════════════════════
🎬 CHAPTER 1-2: INTRODUCE THE CHARACTERS
═══════════════════════════════════════════════════════════════════

In the FIRST 1-2 chapters, you MUST introduce the main characters:
• State their NAME and WHO they are: "Meet Dek, a Yautja hunter bound by an ancient code."
• Explain their ROLE: "Thea, a human survivor stranded on an alien world."
• Hint at their GOAL: "Tessa, a synthetic with a hidden mission."
• Set up RELATIONSHIPS: "Dek needs Thea. Thea needs to escape. Neither trusts the other."

EXAMPLE INTRO (Chapter 1):
"On a world where death is the only currency, three souls collide. Dek—a Yautja warrior, exiled and hunting for redemption. Thea—a human woman, broken but refusing to die. And Tessa—a synthetic with orders that could doom them all. Their fates are now intertwined. None of them will survive alone."

═══════════════════════════════════════════════════════════════════
🎭 CHARACTER IDENTIFICATION - CRITICAL:
═══════════════════════════════════════════════════════════════════

You have ACCESS to the video. USE IT to identify characters:
• Watch the video and identify character names from dialogue, credits, or context
• ALWAYS use specific names: "Thea", "Dek", "Kaliska" - NOT "a figure", "a creature", "a warrior"
• When someone speaks, tell us WHO: "Dek turns to her. 'You are useful,' he growls."
• First time a character appears, briefly identify them: "Dek, the Yautja hunter, emerges from the shadows."
• Track relationships: "Thea, the human survivor" / "Dek, the Yautja hunter" / "Tessa, the synthetic"

🏷️ USE SPECIES/ROLE DESCRIPTORS FOR VARIETY:
• Mix names with species: "Dek" → "the Yautja", "the hunter", "the Predator"
• Mix names with roles: "Thea" → "the human", "the survivor", "the woman"
• Mix names with roles: "Tessa" → "the synthetic", "the android"
• Example: "Dek grabs her arm. The Yautja's grip is iron. 'You are useful,' he growls."
• Example: "Thea struggles, but the hunter won't let go."
• This adds variety and reminds viewers WHO/WHAT the characters are

═══════════════════════════════════════════════════════════════════
🚨 FORBIDDEN META-LANGUAGE - INSTANT FAIL:
═══════════════════════════════════════════════════════════════════

NEVER use these phrases - they break immersion completely:
• "The video/scene/shot shows..." 
• "The scene transitions/cuts/shifts to..."
• "Focus shifts to..." / "The focus remains on..."
• "The camera pans/pulls back/reveals..."
• "We see..." / "The viewer sees..."
• "A figure/creature/character appears..."
• "The setting transforms..." / "The landscape shifts..."
• "The narrative continues..." / "The story unfolds..."
• "The environment/atmosphere/tone..." 
• Any reference to this being a video, scene, or shot

YOU ARE THE NARRATOR - Tell the story as if YOU ARE THERE watching it happen!

❌ DOCUMENTARY STYLE (FORBIDDEN):
"The scene transitions to Yautja Prime, a desolate planet, where various creatures are shown."

✅ STORYTELLING STYLE (REQUIRED):
"Yautja Prime. A world of ash and bone. Here, the hunters gather. Here, the weak are devoured."

❌ DOCUMENTARY STYLE (FORBIDDEN):
"The scene cuts to a cavernous interior filled with conflict, figures battling with glowing red weapons."

✅ STORYTELLING STYLE (REQUIRED):
"Deep in the cavern, chaos erupts. Warriors clash, their blades burning red. Blood stains the ancient stone."

❌ DOCUMENTARY STYLE (FORBIDDEN):
"Focus shifts to a forest setting, highlighting a warrior-like figure with dreadlocks."

✅ STORYTELLING STYLE (REQUIRED):
"In the heart of the jungle, Dek moves like a ghost. His dreadlocks sway. His eyes burn with purpose."

═══════════════════════════════════════════════════════════════════
STORYTELLING STYLE - BE THE NARRATOR:
═══════════════════════════════════════════════════════════════════

Write as if you're telling a friend about an epic movie:
• Start with ACTION or LOCATION: "Deep in the jungle..." / "Dek strikes first..."
• Use SHORT, PUNCHY sentences: "He runs. They follow. No escape."
• Name characters IMMEDIATELY: "Dek" not "a warrior" / "Tessa" not "a synthetic"
• Describe what characters DO, not what "the scene shows"
• Add tension through word choice: "stalks" not "walks" / "erupts" not "starts"

✅ GOOD NARRATION EXAMPLES:
• "Yautja Prime. A world without mercy. Dek arrives, his mission clear: hunt or be hunted."
• "The jungle burns. Tessa runs, her synthetic legs carrying her through the flames."
• "Dek's blade finds its mark. The creature falls. But more are coming."
• "'You are useful,' Dek growls, lifting Thea from the mud. She has no choice but to follow."
• "Blood. Fire. Screams. The hunt has begun, and no one is safe."

═══════════════════════════════════════════════════════════════════
CHAPTERS TO REWRITE:
{chapters_text}

Return ONLY a JSON array:
[
  {{"chapter": 1, "narration": "INTRODUCE CHARACTERS BY NAME here..."}},
  {{"chapter": 2, "narration": "Continue intro or start story with named characters..."}},
  ...
]"""

            # Call Video Chat API
            narrations_batch = await self._call_video_chat_for_narration(
                video_no=video_no,
                prompt=prompt,
                unique_id=unique_id,
                max_retries=max_retries,
                expected_count=len(batch_chapters),
                batch_start=batch_start
            )
            
            # Map results back to the correct positions
            for i, narration in enumerate(narrations_batch):
                global_idx = batch_start + i
                if global_idx < total_chapters:
                    all_narrations[global_idx] = narration
            
            # After first batch, extract character roster for subsequent batches
            if batch_start == 0 and narrations_batch and not character_roster:
                try:
                    # Combine first batch narrations to extract character names
                    first_batch_text = " ".join(narrations_batch[:10])  # First 10 chapters max
                    
                    roster_prompt = f"""Based on this narration, list the MAIN CHARACTERS with their roles.
Format EXACTLY as shown (one per line, dash prefix):
- [Name]: [Role/Species]

Example format:
- Thea: Human survivor, blonde woman
- Dek: Yautja hunter, the main Predator  
- Tessa: Synthetic android, Weyland-Yutani operative
- Jack: Human crew member

Extract characters from this narration (list 3-8 main characters):
{first_batch_text[:3000]}"""
                    
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        roster_headers = {**self.headers, "Content-Type": "application/json"}
                        roster_payload = {
                            "video_nos": [video_no],
                            "prompt": roster_prompt,
                            "unique_id": unique_id
                        }
                        roster_response = await client.post(
                            f"{self.base_url}/chat",
                            headers=roster_headers,
                            json=roster_payload
                        )
                        
                        if roster_response.status_code == 200:
                            roster_result = roster_response.json()
                            if roster_result.get("code") == "0000":
                                roster_data = roster_result.get("data", {})
                                character_roster = roster_data.get("content", "").strip()
                                if character_roster:
                                    print(f"📋 Character roster extracted for consistency:", flush=True)
                                    for line in character_roster.split("\\n")[:6]:
                                        if line.strip():
                                            print(f"   {line.strip()}", flush=True)
                except Exception as roster_error:
                    print(f"⚠️ Could not extract character roster (non-critical): {roster_error}", flush=True)
                    # Continue without roster - not critical
            
            # Small delay between batches to avoid rate limits
            if batch_end < total_chapters:
                print(f"⏳ Waiting 3s before next batch...", flush=True)
                await asyncio.sleep(3)
        
        # Fill any empty narrations with fallback
        for i, narration in enumerate(all_narrations):
            if not narration:
                # Use original summary as fallback
                ch = chapters[i]
                all_narrations[i] = ch.get("description", "") or ch.get("summary", f"Chapter {i+1}")
                print(f"⚠️ Chapter {i+1} using fallback narration", flush=True)
        
        print(f"✅ Video Chat narration complete: {len(all_narrations)} chapters", flush=True)
        return all_narrations
    
    async def _call_video_chat_for_narration(
        self,
        video_no: str,
        prompt: str,
        unique_id: str,
        max_retries: int,
        expected_count: int,
        batch_start: int
    ) -> List[str]:
        """
        Make a single Video Chat API call for narration and parse the response.
        
        Args:
            video_no: Video ID
            prompt: The full prompt with chapters
            unique_id: User/workspace ID
            max_retries: Number of retries
            expected_count: Expected number of narrations in response
            batch_start: Starting chapter index (for logging)
            
        Returns:
            List of narration strings for this batch
        """
        import json
        import re
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json={
                            "video_nos": [video_no],
                            "prompt": prompt,
                            "unique_id": unique_id
                        }
                    )
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "Unknown error")
                        if "network" in msg.lower() or "busy" in msg.lower():
                            print(f"⚠️ Transient error (attempt {attempt + 1}): {msg}", flush=True)
                            last_error = Exception(msg)
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Video Chat failed: {msg}")
                    
                    # Extract response content
                    content = result.get("data", {}).get("content", "")
                    
                    if not content:
                        print(f"⚠️ Empty response from Video Chat", flush=True)
                        last_error = Exception("Empty response")
                        continue
                    
                    # Parse the JSON response
                    narrations = self._parse_narration_response(content, expected_count, batch_start)
                    
                    if len(narrations) == expected_count:
                        filled = sum(1 for n in narrations if n)
                        print(f"✅ Got {filled}/{expected_count} narrations from Video Chat", flush=True)
                        return narrations
                    else:
                        print(f"⚠️ Expected {expected_count} narrations, got {len(narrations)}", flush=True)
                        # Pad with empty strings if we got fewer
                        while len(narrations) < expected_count:
                            narrations.append("")
                        return narrations
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(3)
        
        # All retries failed
        print(f"❌ Video Chat failed after {max_retries} attempts: {last_error}", flush=True)
        return [""] * expected_count
    
    def _parse_narration_response(self, content: str, expected_count: int, batch_start: int) -> List[str]:
        """
        Parse Video Chat response containing narration JSON.
        
        Args:
            content: Raw response content
            expected_count: Expected number of narrations
            batch_start: Starting chapter index
            
        Returns:
            List of narration strings
        """
        import json
        import re
        
        narrations = [""] * expected_count
        
        # Try to extract JSON array from response
        content = content.strip()
        
        # Find JSON array in response (might have extra text around it)
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            json_str = json_match.group()
            try:
                data = json.loads(json_str)
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            # Get chapter number (1-indexed in response)
                            chapter_num = item.get("chapter", 0)
                            narration = item.get("narration", "")
                            
                            # Convert to 0-indexed position within this batch
                            batch_idx = chapter_num - batch_start - 1
                            
                            if 0 <= batch_idx < expected_count and narration:
                                # Clean up the narration
                                narration = narration.strip().strip('"\'')
                                narrations[batch_idx] = narration
                    
                    # Count how many we got
                    filled = sum(1 for n in narrations if n)
                    print(f"📝 Parsed {filled}/{expected_count} narrations from JSON", flush=True)
                    return narrations
                    
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON parse error: {e}", flush=True)
        
        # Fallback: try to extract narrations line by line
        print(f"⚠️ Falling back to line-by-line parsing", flush=True)
        lines = content.split('\n')
        current_idx = 0
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('[') or line.startswith(']'):
                continue
            
            # Try to extract chapter number and narration
            match = re.match(r'(\d+)[.:\)]\s*(.+)', line)
            if match and current_idx < expected_count:
                narrations[current_idx] = match.group(2).strip().strip('"\'')
                current_idx += 1
        
        return narrations

    async def extract_all_movie_data_unified(
        self,
        video_no: str,
        chapters: List[dict],
        audio_transcript: List[dict] = None,
        unique_id: str = "default",
        max_retries: int = 3
    ) -> dict:
        """
        🚀 OPTIMIZED: Extract ALL movie data in a SINGLE API call.
        
        This REPLACES the following separate calls:
        - identify_characters() 
        - get_plot_summary()
        - identify_key_moments()
        - extract_structured_movie_data()
        - map_speakers_to_characters()
        
        SAVINGS: 5 API calls → 1 API call (80% reduction)
        
        Args:
            video_no: The video ID from Memories.ai
            chapters: List of chapter dicts (used to understand movie scope)
            audio_transcript: Optional audio transcript with speaker labels to map
            unique_id: Workspace/user identifier
            max_retries: Number of retries for failed calls
            
        Returns:
            Dict with ALL movie data:
            {
                "title": "Movie Title",
                "characters": [{"name": "Dek", "type": "Yautja", "role": "Hunter", "appearance": "..."}],
                "character_guide": "Physical description = Character Name format string",
                "locations": [{"name": "Planet Gena", "description": "..."}],
                "factions": [{"name": "Yautja Clan", "members": ["Dek"]}],
                "relationships": ["Dek captures Thea", ...],
                "scenes": [{"chapter": 1, "location": "...", "characters_present": [...]}],
                "plot_summary": "Full plot summary with character arcs...",
                "key_moments": [{"chapter_index": 5, "start": 120.0, "end": 125.0, "speaker": "Dek", "dialogue": "..."}],
                "speaker_mapping": {"Speaker 1": "Dek", "Speaker 2": "Thea"}
            }
        """
        import json
        
        print(f"\n{'='*80}", flush=True)
        print(f"🚀 UNIFIED DATA EXTRACTION (1 call instead of 5)", flush=True)
        print(f"{'='*80}", flush=True)
        
        # Build chapter context
        chapter_list = []
        for i, ch in enumerate(chapters):
            start = ch.get("start", "0:00")
            end = ch.get("end", "0:00")
            title = ch.get("title", f"Chapter {i+1}")
            desc = ch.get("description", "") or ch.get("summary", "")
            chapter_list.append(f"Chapter {i+1} [{start}-{end}]: {desc[:150]}")
        
        chapters_context = "\n".join(chapter_list[:50])  # Limit to first 50 chapters
        
        # Build speaker samples if we have audio transcript
        speaker_samples = ""
        unique_speakers = []
        if audio_transcript:
            speakers = {}
            for seg in audio_transcript[:80]:  # Limit for prompt size
                speaker = seg.get("speaker")
                if speaker:
                    if speaker not in speakers:
                        speakers[speaker] = []
                        unique_speakers.append(speaker)
                    if len(speakers[speaker]) < 3:  # 3 samples per speaker
                        speakers[speaker].append(seg.get("text", "")[:100])
            
            if speakers:
                samples = []
                for speaker, texts in speakers.items():
                    samples.append(f"{speaker}: {' | '.join(texts)}")
                speaker_samples = f"""
SPEAKER LABELS TO MAP (from audio transcription):
{chr(10).join(samples)}

Map each speaker label to their actual character name in the speaker_mapping field.
"""

        # Unified mega-prompt
        unified_prompt = f"""Analyze this ENTIRE video and extract ALL of the following data in ONE response.

CHAPTERS:
{chapters_context}
{speaker_samples}

══════════════════════════════════════════════════════════════════════════════
RETURN A SINGLE JSON OBJECT WITH ALL OF THE FOLLOWING:
══════════════════════════════════════════════════════════════════════════════

{{
  "title": "The actual movie/video title",
  
  "characters": [
    {{"name": "Dek", "type": "Yautja", "role": "Hunter protagonist", "appearance": "Tribal markings, dreadlocks"}},
    {{"name": "Thea", "type": "Human", "role": "Survivor", "appearance": "Blonde hair, athletic"}},
    {{"name": "Tessa", "type": "Synthetic", "role": "Corporate operative", "appearance": "Pale, blonde"}}
  ],
  
  "character_guide": "Creature with dreadlocks and tribal markings = Dek\\nBlonde woman = Thea\\nPale synthetic woman = Tessa",
  
  "locations": [
    {{"name": "Yautja Prime", "description": "Alien homeworld, rocky terrain"}},
    {{"name": "Planet Gena", "description": "Hostile desert planet, dangerous wildlife"}}
  ],
  
  "factions": [
    {{"name": "Yautja Clan", "members": ["Dek", "Kwei"]}},
    {{"name": "Weyland-Yutani", "members": ["Tessa"]}}
  ],
  
  "relationships": [
    "Dek hunts Thea but develops respect for her",
    "Tessa works for Weyland-Yutani and is searching for Thea"
  ],
  
  "scenes": [
    {{"chapter": 1, "location": "Yautja Prime", "characters_present": ["Dek"], "action": "Receives mission"}},
    {{"chapter": 5, "location": "Planet Gena", "characters_present": ["Thea", "Tessa"], "action": "Confrontation"}}
  ],
  
  "plot_summary": "A comprehensive plot summary covering: main characters and their roles, what happens to each character (who dies, who survives), the villain's goal, major plot points and twists, and how the story ends.",
  
  "key_moments": [
    {{"chapter_index": 5, "start": 120.0, "end": 125.0, "speaker": "Dek", "dialogue": "You are worthy prey", "importance": "Turning point", "lead_in": "And then Dek speaks..."}}
  ],
  
  "speaker_mapping": {{
    "Speaker 1": "Dek",
    "Speaker 2": "Thea",
    "Speaker 3": "Tessa"
  }}
}}

══════════════════════════════════════════════════════════════════════════════
CRITICAL RULES:
══════════════════════════════════════════════════════════════════════════════

1. USE ACTUAL NAMES from dialogue/credits - NOT descriptions like "A figure" or "The warrior"
2. For locations, use proper nouns (planet names, facility names) NOT visual descriptions
3. For key_moments, pick 3-5 emotionally powerful dialogue moments (2-8 seconds each)
4. For speaker_mapping, map ANY generic labels (Speaker 1, Speaker 2) to character names
5. For plot_summary, include WHO DIES and WHO SURVIVES
6. For scenes, map each chapter to its location and characters present

Return ONLY the JSON object. Start with {{ and end with }}"""

        last_error = None
        
        for attempt in range(max_retries):
            try:
                request_payload = {
                    "video_nos": [video_no],
                    "prompt": unified_prompt,
                    "unique_id": unique_id
                }
                
                print(f"📤 Sending unified extraction request (attempt {attempt + 1}/{max_retries})...", flush=True)
                
                async with httpx.AsyncClient(timeout=180.0) as client:  # Longer timeout for comprehensive analysis
                    response = await client.post(
                        f"{self.base_url}/chat",
                        headers={
                            **self.headers,
                            "Content-Type": "application/json"
                        },
                        json=request_payload
                    )
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("code") != "0000":
                        msg = result.get("msg", "Unknown error")
                        print(f"⚠️ API error (attempt {attempt + 1}): {msg}", flush=True)
                        
                        if "network" in msg.lower() or "busy" in msg.lower() or "try again" in msg.lower():
                            last_error = Exception(msg)
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        raise Exception(f"Unified extraction failed: {msg}")
                    
                    content = result.get("data", {}).get("content", "")
                    
                    if not content:
                        print(f"⚠️ Empty response, retrying...", flush=True)
                        await asyncio.sleep(5)
                        continue
                    
                    # Parse JSON from response
                    json_match = None
                    if "{" in content and "}" in content:
                        start_idx = content.find("{")
                        end_idx = content.rfind("}") + 1
                        json_str = content[start_idx:end_idx]
                        try:
                            json_match = json.loads(json_str)
                        except json.JSONDecodeError as je:
                            print(f"⚠️ JSON parse error: {je}", flush=True)
                    
                    if not json_match:
                        print(f"⚠️ Could not parse JSON, retrying...", flush=True)
                        await asyncio.sleep(3)
                        continue
                    
                    # Build unified result with all fields
                    unified_data = {
                        "title": json_match.get("title", "Unknown"),
                        "characters": json_match.get("characters", []),
                        "character_guide": json_match.get("character_guide", ""),
                        "locations": json_match.get("locations", []),
                        "factions": json_match.get("factions", []),
                        "relationships": json_match.get("relationships", []),
                        "scenes": json_match.get("scenes", []),
                        "plot_summary": json_match.get("plot_summary", ""),
                        "key_moments": json_match.get("key_moments", []),
                        "speaker_mapping": json_match.get("speaker_mapping", {})
                    }
                    
                    # Log summary
                    print(f"\n✅ UNIFIED EXTRACTION COMPLETE:", flush=True)
                    print(f"   📽️ Title: {unified_data['title']}", flush=True)
                    print(f"   👥 Characters: {len(unified_data['characters'])}", flush=True)
                    print(f"   📍 Locations: {len(unified_data['locations'])}", flush=True)
                    print(f"   🎬 Scenes mapped: {len(unified_data['scenes'])}", flush=True)
                    print(f"   🎯 Key moments: {len(unified_data['key_moments'])}", flush=True)
                    print(f"   🔊 Speaker mappings: {len(unified_data['speaker_mapping'])}", flush=True)
                    print(f"   📖 Plot summary: {len(unified_data['plot_summary'])} chars", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    
                    return unified_data
                    
            except httpx.HTTPStatusError as e:
                print(f"⚠️ HTTP error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                if "Unified extraction failed" in str(e):
                    raise
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(3)
        
        # Return empty structure on failure
        print(f"⚠️ Unified extraction failed after {max_retries} attempts", flush=True)
        return {
            "title": "Unknown",
            "characters": [],
            "character_guide": "",
            "locations": [],
            "factions": [],
            "relationships": [],
            "scenes": [],
            "plot_summary": "",
            "key_moments": [],
            "speaker_mapping": {}
        }

