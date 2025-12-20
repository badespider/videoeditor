import os
import subprocess
import json
from typing import List, Tuple
from pathlib import Path

import cv2

from app.config import get_settings
from app.models import Scene
from app.services.ffmpeg_utils import run_ffmpeg, run_ffmpeg_capture, FFmpegError, sanitize_ffmpeg_stderr


class SceneDetectorService:
    """Service for detecting and extracting scenes from video files using FFmpeg."""
    
    def __init__(self):
        self.settings = get_settings()
    
    def detect_scenes(self, video_path: str, target_scene_count: int = None) -> List[Tuple[float, float]]:
        """
        Divides video into Fixed Grid of time blocks (Time-Blocked Dubbing method).
        
        Instead of detecting visual scene changes, we use consistent 7-second blocks.
        This ensures narration length matches clip duration for smooth sync.
        
        Args:
            video_path: Path to the video file
            target_scene_count: Ignored - we use fixed block size instead
            
        Returns:
            List of (start_time, end_time) tuples in seconds
        """
        print(f"🎬 Segmenting video: {video_path}", flush=True)
        
        # Get video duration
        duration = self.get_video_duration(video_path)
        print(f"⏱️ Video Duration: {duration:.2f}s ({duration/60:.1f} minutes)", flush=True)
        
        if duration == 0:
            raise ValueError("Could not determine video duration")
        
        # The Golden Number: ~7 seconds per block
        # This allows ~17 words of narration (2.5 words/sec speaking rate)
        BLOCK_SIZE = 7.0
        
        scenes = []
        current_time = 0.0
        
        while current_time < duration:
            end_time = min(current_time + BLOCK_SIZE, duration)
            
            # Avoid tiny tail clips (< 3s) - merge into previous block
            if (end_time - current_time) < 3.0:
                if scenes:
                    prev_start, _ = scenes.pop()
                    scenes.append((prev_start, end_time))
                break
            
            scenes.append((current_time, end_time))
            current_time = end_time
        
        print(f"✅ Generated {len(scenes)} time-blocks of ~{BLOCK_SIZE}s each.", flush=True)
        return scenes
    
    def _generate_smart_segments(self, duration: float, target_count: int) -> List[Tuple[float, float]]:
        """Generate evenly-spaced segments for recap."""
        segment_length = duration / target_count
        scenes = []
        
        for i in range(target_count):
            start = i * segment_length
            end = min((i + 1) * segment_length, duration)
            if end - start >= 5:  # Minimum 5 second scenes
                scenes.append((start, end))
        
        return scenes
    
    def _sample_scenes(self, scenes: List[Tuple[float, float]], target_count: int) -> List[Tuple[float, float]]:
        """Sample scenes evenly to reduce count."""
        if len(scenes) <= target_count:
            return scenes
        
        step = len(scenes) / target_count
        sampled = []
        for i in range(target_count):
            idx = int(i * step)
            sampled.append(scenes[idx])
        
        return sampled
    
    def _detect_with_ffmpeg(self, video_path: str, threshold: float) -> List[float]:
        """Use FFmpeg to detect scene changes."""
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null",
            "-"
        ]

        result = run_ffmpeg_capture(cmd, check=False, timeout=300)
        if result.returncode != 0:
            raise FFmpegError(
                message=f"FFmpeg scene detection failed:\n{sanitize_ffmpeg_stderr(result.stderr or '')}",
                stderr=result.stderr or "",
                cmd=list(cmd),
            )
        
        # Parse scene change times from stderr
        scene_times = [0.0]  # Always start at 0
        
        for line in result.stderr.split('\n'):
            if 'pts_time:' in line:
                try:
                    # Extract pts_time value
                    pts_part = line.split('pts_time:')[1].split()[0]
                    time = float(pts_part)
                    if time > scene_times[-1] + self.settings.min_scene_duration:
                        scene_times.append(time)
                except (IndexError, ValueError):
                    continue
        
        return scene_times
    
    def _generate_time_segments(self, duration: float) -> List[float]:
        """Generate evenly-spaced time segments for the video."""
        segment_length = self.settings.max_scene_duration
        times = [0.0]
        
        current = segment_length
        while current < duration:
            times.append(current)
            current += segment_length
        
        return times
    
    def _times_to_scenes(
        self, 
        scene_times: List[float], 
        total_duration: float
    ) -> List[Tuple[float, float]]:
        """Convert scene change times to (start, end) tuples."""
        scenes = []
        
        for i in range(len(scene_times)):
            start = scene_times[i]
            end = scene_times[i + 1] if i + 1 < len(scene_times) else total_duration
            
            duration = end - start
            
            # Filter by duration constraints
            if duration >= self.settings.min_scene_duration:
                # Split long scenes
                if duration > self.settings.max_scene_duration:
                    scenes.extend(self._split_scene(start, end))
                else:
                    scenes.append((start, end))
        
        return scenes
    
    def _split_scene(self, start: float, end: float) -> List[Tuple[float, float]]:
        """Split a long scene into smaller chunks."""
        chunks = []
        current = start
        max_duration = self.settings.max_scene_duration
        
        while current < end:
            chunk_end = min(current + max_duration, end)
            if chunk_end - current >= self.settings.min_scene_duration:
                chunks.append((current, chunk_end))
            current = chunk_end
        
        return chunks
    
    def extract_scene_clips(
        self, 
        video_path: str, 
        scenes: List[Tuple[float, float]],
        output_dir: str
    ) -> List[Scene]:
        """
        Extract video clips for each detected scene.
        
        Args:
            video_path: Path to the source video
            scenes: List of (start, end) tuples
            output_dir: Directory to save extracted clips
            
        Returns:
            List of Scene objects with video paths populated
        """
        os.makedirs(output_dir, exist_ok=True)
        scene_objects = []
        
        print(f"✂️ Extracting {len(scenes)} scene clips...")
        
        for i, (start, end) in enumerate(scenes):
            output_path = os.path.join(output_dir, f"scene_{i:04d}.mp4")
            
            print(f"  📎 Scene {i+1}/{len(scenes)}: {start:.1f}s - {end:.1f}s")
            
            # Use ffmpeg for precise cutting
            self._extract_clip(video_path, start, end, output_path)
            
            scene = Scene(
                index=i,
                start_time=start,
                end_time=end,
                duration=end - start,
                video_path=output_path
            )
            scene_objects.append(scene)
        
        return scene_objects
    
    def _extract_clip(
        self, 
        input_path: str, 
        start: float, 
        end: float, 
        output_path: str
    ):
        """Extract a clip using ffmpeg with frame-accurate seeking."""
        duration = end - start
        
        # -ss AFTER -i = frame-accurate seeking (slower but exact)
        # This ensures "Scene 5" is actually Scene 5, not Scene 4.5
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,      # Input FIRST
            "-ss", str(start),     # Seek AFTER input (slower but accurate)
            "-t", str(duration),   # Duration to capture
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "ultrafast",
            "-crf", "23",
            "-r", "30",            # Force 30fps NOW to prevent VFR drift later
            "-loglevel", "error",
            output_path
        ]
        
        subprocess.run(
            cmd, 
            capture_output=True, 
            check=True,
            timeout=300  # Increased timeout because accurate seeking is slower
        )
    
    def extract_frame(
        self, 
        video_path: str, 
        timestamp: float, 
        output_path: str
    ) -> str:
        """
        Extract a single frame from the video at the given timestamp.
        
        Args:
            video_path: Path to the video file
            timestamp: Time in seconds
            output_path: Path to save the frame
            
        Returns:
            Path to the saved frame
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-loglevel", "error",
            output_path
        ]

        run_ffmpeg(cmd, timeout=30)
        return output_path
    
    def extract_scene_thumbnails(
        self, 
        scenes: List[Scene], 
        source_video: str,
        output_dir: str
    ) -> List[Scene]:
        """
        Extract a representative thumbnail for each scene.
        
        Args:
            scenes: List of Scene objects
            source_video: Path to the source video
            output_dir: Directory to save thumbnails
            
        Returns:
            Updated Scene objects with frame_path populated
        """
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"🖼️ Extracting {len(scenes)} thumbnails...")
        
        for scene in scenes:
            # Use middle of the scene for thumbnail
            mid_time = (scene.start_time + scene.end_time) / 2
            frame_path = os.path.join(output_dir, f"frame_{scene.index:04d}.jpg")
            
            self.extract_frame(source_video, mid_time, frame_path)
            scene.frame_path = frame_path
        
        return scenes
    
    def get_video_duration(self, video_path: str) -> float:
        """Get the duration of a video file in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
        return 0.0
    
    def get_video_info(self, video_path: str) -> dict:
        """Get detailed information about a video file."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            
            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
            
            if video_stream:
                return {
                    "width": int(video_stream.get("width", 0)),
                    "height": int(video_stream.get("height", 0)),
                    "fps": eval(video_stream.get("r_frame_rate", "0/1")),
                    "duration": float(data.get("format", {}).get("duration", 0))
                }
        
        return {"width": 0, "height": 0, "fps": 0, "duration": 0}
