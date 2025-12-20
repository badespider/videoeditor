"""
Video Chunker Service for splitting long videos into segments.

Handles both duration limits (Gemini's ~2M token context = ~1-2 hours)
and file size limits (Gemini's 2GB max file size).
"""

import os
import subprocess
import json
from typing import List, Optional, Tuple
from pathlib import Path

from app.config import get_settings
from app.services.ffmpeg_utils import run_ffmpeg, FFmpegError


class VideoChunker:
    """
    Splits long videos into manageable chunks for processing.
    
    Considers both:
    - Duration: 1-hour segments to stay within Gemini's 2M token context
    - File size: 1.8GB max per chunk to stay under Gemini's 2GB limit
    """
    
    # 1 hour in seconds - safe limit for Gemini context window
    CHUNK_DURATION = 3600
    
    # 1.8GB in bytes - safe limit for Gemini file size (2GB max)
    MAX_CHUNK_SIZE_BYTES = 1.8 * 1024 ** 3
    
    def __init__(self):
        self.settings = get_settings()
        self.temp_dir = self.settings.storage.temp_storage_path
        
        # Create chunks directory
        self.chunks_dir = os.path.join(self.temp_dir, "chunks")
        os.makedirs(self.chunks_dir, exist_ok=True)
    
    def get_duration(self, video_path: str) -> float:
        """
        Get the duration of a video file in seconds.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Duration in seconds
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to get video duration: {result.stderr}")
        
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    
    def get_file_size(self, video_path: str) -> int:
        """
        Get the file size in bytes.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            File size in bytes
        """
        return os.path.getsize(video_path)
    
    def get_bitrate(self, video_path: str) -> int:
        """
        Get the video bitrate in bits per second.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Bitrate in bps
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to get video bitrate: {result.stderr}")
        
        data = json.loads(result.stdout)
        return int(data["format"].get("bit_rate", 0))
    
    def calculate_optimal_chunk_duration(self, video_path: str) -> float:
        """
        Calculate optimal chunk duration considering both time and size limits.
        
        For high-bitrate videos, we may need shorter chunks to stay under 2GB.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Optimal chunk duration in seconds
        """
        file_size = self.get_file_size(video_path)
        duration = self.get_duration(video_path)
        
        if duration <= 0:
            return self.CHUNK_DURATION
        
        # Calculate bytes per second
        bytes_per_second = file_size / duration
        
        # Calculate max duration to stay under size limit
        size_based_duration = self.MAX_CHUNK_SIZE_BYTES / bytes_per_second
        
        # Use the smaller of time-based or size-based limit
        optimal_duration = min(self.CHUNK_DURATION, size_based_duration)
        
        # Ensure minimum chunk duration of 10 minutes
        optimal_duration = max(600, optimal_duration)
        
        if optimal_duration < self.CHUNK_DURATION:
            print(f"📊 High bitrate detected: reducing chunk duration to {optimal_duration/60:.0f} minutes for size limit", flush=True)
        
        return optimal_duration
    
    def split_video(
        self, 
        video_path: str,
        job_id: str = "default"
    ) -> List[str]:
        """
        Split a video into chunks considering both duration and file size limits.
        
        Args:
            video_path: Path to the input video
            job_id: Unique identifier for this job (for temp file naming)
            
        Returns:
            List of chunk file paths (single-item list if no split needed)
        """
        duration = self.get_duration(video_path)
        file_size = self.get_file_size(video_path)
        
        print(f"📏 Video: {duration:.1f}s ({duration/3600:.2f}h), {file_size/(1024**3):.2f}GB", flush=True)
        
        # Calculate optimal chunk duration based on both limits
        chunk_duration = self.calculate_optimal_chunk_duration(video_path)
        
        # Check if chunking is needed
        needs_duration_split = duration > chunk_duration
        needs_size_split = file_size > self.MAX_CHUNK_SIZE_BYTES
        
        if not needs_duration_split and not needs_size_split:
            print(f"✅ Video is under limits, no chunking needed", flush=True)
            return [video_path]
        
        # Calculate number of chunks
        num_chunks = int(duration // chunk_duration) + (1 if duration % chunk_duration > 0 else 0)
        
        reason = []
        if needs_duration_split:
            reason.append(f"duration > {chunk_duration/3600:.1f}h")
        if needs_size_split:
            reason.append(f"size > 1.8GB")
        
        print(f"📦 Splitting into {num_chunks} chunks ({', '.join(reason)})", flush=True)
        
        chunks = []
        job_chunks_dir = os.path.join(self.chunks_dir, job_id)
        os.makedirs(job_chunks_dir, exist_ok=True)
        
        for i in range(num_chunks):
            start_time = i * chunk_duration
            current_chunk_duration = min(chunk_duration, duration - start_time)
            
            chunk_path = os.path.join(job_chunks_dir, f"chunk_{i:02d}.mp4")
            
            print(f"   Extracting chunk {i+1}/{num_chunks}: {start_time:.0f}s - {start_time + current_chunk_duration:.0f}s", flush=True)
            
            self._extract_chunk(video_path, start_time, current_chunk_duration, chunk_path)
            
            # Verify chunk size
            chunk_size = self.get_file_size(chunk_path)
            if chunk_size > self.MAX_CHUNK_SIZE_BYTES:
                print(f"   ⚠️ Chunk {i+1} is {chunk_size/(1024**3):.2f}GB (over limit)", flush=True)
            
            chunks.append(chunk_path)
        
        print(f"✅ Created {len(chunks)} video chunks", flush=True)
        return chunks
    
    def _extract_chunk(
        self,
        input_path: str,
        start_time: float,
        duration: float,
        output_path: str
    ):
        """
        Extract a chunk from a video using FFmpeg.
        
        Uses fast seeking with keyframe alignment for speed.
        Re-encodes to ensure consistent format and reasonable size.
        """
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),  # Seek before input for speed
            "-i", input_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",  # Good balance of speed and compression
            "-crf", "23",       # Reasonable quality
            "-maxrate", "4M",   # Cap bitrate to prevent huge chunks
            "-bufsize", "8M",
            "-loglevel", "error",
            output_path
        ]
        try:
            run_ffmpeg(cmd, timeout=3600)
        except FFmpegError as e:
            print(f"❌ Chunk extraction failed (ffmpeg stderr):\n{e.stderr}", flush=True)
            raise
    
    def cleanup_chunks(self, job_id: str):
        """
        Clean up temporary chunk files for a job.
        
        Args:
            job_id: Job identifier
        """
        job_chunks_dir = os.path.join(self.chunks_dir, job_id)
        
        if os.path.exists(job_chunks_dir):
            import shutil
            shutil.rmtree(job_chunks_dir)
            print(f"🗑️ Cleaned up chunks for job {job_id}", flush=True)
    
    def get_chunk_info(self, video_path: str) -> dict:
        """
        Get information about how a video would be chunked.
        
        Args:
            video_path: Path to the video
            
        Returns:
            Dictionary with chunk information
        """
        duration = self.get_duration(video_path)
        file_size = self.get_file_size(video_path)
        chunk_duration = self.calculate_optimal_chunk_duration(video_path)
        
        needs_duration_split = duration > chunk_duration
        needs_size_split = file_size > self.MAX_CHUNK_SIZE_BYTES
        needs_chunking = needs_duration_split or needs_size_split
        
        if not needs_chunking:
            return {
                "needs_chunking": False,
                "duration_seconds": duration,
                "duration_hours": duration / 3600,
                "file_size_bytes": file_size,
                "file_size_gb": file_size / (1024 ** 3),
                "num_chunks": 1,
                "chunk_duration": duration,
                "reason": None
            }
        
        num_chunks = int(duration // chunk_duration) + (1 if duration % chunk_duration > 0 else 0)
        
        reason = []
        if needs_duration_split:
            reason.append("duration")
        if needs_size_split:
            reason.append("file_size")
        
        return {
            "needs_chunking": True,
            "duration_seconds": duration,
            "duration_hours": duration / 3600,
            "file_size_bytes": file_size,
            "file_size_gb": file_size / (1024 ** 3),
            "num_chunks": num_chunks,
            "chunk_duration": chunk_duration,
            "reason": reason
        }
