"""
Video Compressor Service for handling oversized videos.

Compresses videos that exceed Gemini API's 2GB file size limit using FFmpeg.
Uses adaptive resolution scaling based on source video dimensions.
"""

import os
import subprocess
import json
from typing import Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services.ffmpeg_utils import run_ffmpeg, FFmpegError


@dataclass
class VideoInfo:
    """Information about a video file."""
    file_path: str
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    bitrate_kbps: int
    codec: str
    fps: float
    
    @property
    def file_size_gb(self) -> float:
        return self.file_size_bytes / (1024 ** 3)
    
    @property
    def file_size_mb(self) -> float:
        return self.file_size_bytes / (1024 ** 2)
    
    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"
    
    @property
    def duration_hours(self) -> float:
        return self.duration_seconds / 3600


class VideoCompressor:
    """
    Compresses videos to meet Gemini API file size limits.
    
    Uses adaptive resolution scaling:
    - 4K (3840x2160) -> 1080p (1920x1080)
    - 1440p (2560x1440) -> 720p (1280x720)  
    - 1080p or lower -> keep resolution, reduce bitrate only
    """
    
    # Gemini API limit with safety margin
    MAX_FILE_SIZE_BYTES = 1.9 * 1024 ** 3  # 1.9GB (safety margin from 2GB)
    
    # Resolution thresholds for adaptive scaling
    RESOLUTION_4K = 2160
    RESOLUTION_1440P = 1440
    RESOLUTION_1080P = 1080
    RESOLUTION_720P = 720
    
    def __init__(self):
        self.settings = get_settings()
        self.temp_dir = self.settings.storage.temp_storage_path
        
        # Create compressed directory
        self.compressed_dir = os.path.join(self.temp_dir, "compressed")
        os.makedirs(self.compressed_dir, exist_ok=True)
    
    def get_video_info(self, video_path: str) -> VideoInfo:
        """
        Get detailed information about a video file.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            VideoInfo dataclass with file details
        """
        # Get file size
        file_size = os.path.getsize(video_path)
        
        # Get video metadata via ffprobe
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to get video info: {result.stderr}")
        
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if not video_stream:
            raise Exception("No video stream found in file")
        
        # Extract metadata
        format_info = data.get("format", {})
        duration = float(format_info.get("duration", 0))
        bitrate = int(format_info.get("bit_rate", 0)) // 1000  # Convert to kbps
        
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        codec = video_stream.get("codec_name", "unknown")
        
        # Parse frame rate (can be "30/1" or "29.97")
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        else:
            fps = float(fps_str)
        
        return VideoInfo(
            file_path=video_path,
            file_size_bytes=file_size,
            duration_seconds=duration,
            width=width,
            height=height,
            bitrate_kbps=bitrate,
            codec=codec,
            fps=fps
        )
    
    def needs_compression(self, video_path: str) -> bool:
        """
        Check if a video needs compression to meet Gemini limits.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            True if file exceeds 2GB limit
        """
        file_size = os.path.getsize(video_path)
        return file_size > self.MAX_FILE_SIZE_BYTES
    
    def calculate_target_resolution(self, info: VideoInfo) -> Tuple[int, int]:
        """
        Calculate target resolution using adaptive scaling.
        
        Scaling rules:
        - 4K (height >= 2160) -> 1080p
        - 1440p (height >= 1440) -> 720p
        - 1080p or lower -> keep original
        
        Args:
            info: VideoInfo for the source video
            
        Returns:
            Tuple of (width, height) for target resolution
        """
        height = info.height
        width = info.width
        aspect_ratio = width / height if height > 0 else 16/9
        
        if height >= self.RESOLUTION_4K:
            # 4K -> 1080p
            target_height = self.RESOLUTION_1080P
            target_width = int(target_height * aspect_ratio)
            # Ensure even dimensions for codec compatibility
            target_width = target_width - (target_width % 2)
            print(f"📐 Adaptive scaling: {info.resolution} -> {target_width}x{target_height} (4K to 1080p)", flush=True)
            return (target_width, target_height)
        
        elif height >= self.RESOLUTION_1440P:
            # 1440p -> 720p
            target_height = self.RESOLUTION_720P
            target_width = int(target_height * aspect_ratio)
            target_width = target_width - (target_width % 2)
            print(f"📐 Adaptive scaling: {info.resolution} -> {target_width}x{target_height} (1440p to 720p)", flush=True)
            return (target_width, target_height)
        
        else:
            # 1080p or lower - keep original resolution
            print(f"📐 Keeping original resolution: {info.resolution} (bitrate reduction only)", flush=True)
            return (width, height)
    
    def estimate_compressed_size(
        self, 
        info: VideoInfo, 
        target_bitrate_kbps: int
    ) -> float:
        """
        Estimate compressed file size based on target bitrate.
        
        Args:
            info: Source video info
            target_bitrate_kbps: Target bitrate in kbps
            
        Returns:
            Estimated file size in bytes
        """
        # Size = bitrate * duration / 8 (bits to bytes)
        # Add 10% overhead for container/audio
        estimated_bytes = (target_bitrate_kbps * 1000 * info.duration_seconds) / 8
        return estimated_bytes * 1.1
    
    def calculate_target_bitrate(self, info: VideoInfo, target_size_bytes: int) -> int:
        """
        Calculate target bitrate to achieve desired file size.
        
        Args:
            info: Source video info
            target_size_bytes: Desired file size in bytes
            
        Returns:
            Target bitrate in kbps
        """
        # Remove 10% for overhead
        available_bytes = target_size_bytes * 0.9
        # bitrate = (size * 8) / duration
        target_bitrate = int((available_bytes * 8) / info.duration_seconds / 1000)
        
        # Clamp to reasonable range (500kbps - 8000kbps)
        return max(500, min(8000, target_bitrate))
    
    def compress_video(
        self,
        video_path: str,
        output_path: Optional[str] = None,
        target_size_bytes: Optional[int] = None,
        crf: int = 28,
        job_id: str = "default"
    ) -> str:
        """
        Compress a video using FFmpeg with adaptive settings.
        
        Args:
            video_path: Path to source video
            output_path: Optional output path (auto-generated if None)
            target_size_bytes: Target file size (defaults to 1.8GB)
            crf: Constant Rate Factor (18-28, higher = smaller file)
            job_id: Job identifier for temp file naming
            
        Returns:
            Path to compressed video
        """
        info = self.get_video_info(video_path)
        
        print(f"🎬 Source video: {info.resolution}, {info.file_size_gb:.2f}GB, {info.duration_hours:.2f}h", flush=True)
        print(f"   Bitrate: {info.bitrate_kbps}kbps, Codec: {info.codec}", flush=True)
        
        # Calculate target resolution
        target_width, target_height = self.calculate_target_resolution(info)
        
        # Calculate target bitrate if size limit specified
        if target_size_bytes is None:
            target_size_bytes = int(self.MAX_FILE_SIZE_BYTES * 0.95)  # 95% of limit
        
        target_bitrate = self.calculate_target_bitrate(info, target_size_bytes)
        
        print(f"🎯 Target: {target_width}x{target_height}, ~{target_bitrate}kbps, CRF={crf}", flush=True)
        
        # Generate output path
        if output_path is None:
            job_compressed_dir = os.path.join(self.compressed_dir, job_id)
            os.makedirs(job_compressed_dir, exist_ok=True)
            output_path = os.path.join(job_compressed_dir, "compressed.mp4")
        
        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vf", f"scale={target_width}:{target_height}",
            "-c:v", "libx264",
            "-preset", "medium",  # Balance between speed and compression
            "-crf", str(crf),
            "-maxrate", f"{target_bitrate}k",
            "-bufsize", f"{target_bitrate * 2}k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",  # Enable streaming
            "-loglevel", "warning",
            "-stats",
            output_path
        ]
        
        print(f"🔄 Compressing video...", flush=True)
        
        try:
            run_ffmpeg(cmd, timeout=3600)
        except FFmpegError as e:
            print(f"❌ Compression failed (ffmpeg stderr):\n{e.stderr}", flush=True)
            raise
        
        # Verify output
        output_info = self.get_video_info(output_path)
        
        print(f"✅ Compressed: {output_info.resolution}, {output_info.file_size_gb:.2f}GB", flush=True)
        print(f"   Reduction: {(1 - output_info.file_size_bytes/info.file_size_bytes)*100:.1f}%", flush=True)
        
        # Warn if still too large
        if output_info.file_size_bytes > self.MAX_FILE_SIZE_BYTES:
            print(f"⚠️ Warning: Compressed file still exceeds limit ({output_info.file_size_gb:.2f}GB > 1.9GB)", flush=True)
            print(f"   Video will need to be chunked into smaller segments", flush=True)
        
        return output_path
    
    def compress_if_needed(
        self,
        video_path: str,
        job_id: str = "default"
    ) -> Tuple[str, bool]:
        """
        Compress video only if it exceeds the size limit.
        
        Args:
            video_path: Path to source video
            job_id: Job identifier
            
        Returns:
            Tuple of (output_path, was_compressed)
        """
        if not self.needs_compression(video_path):
            info = self.get_video_info(video_path)
            print(f"✅ Video is under size limit ({info.file_size_gb:.2f}GB < 1.9GB), no compression needed", flush=True)
            return (video_path, False)
        
        info = self.get_video_info(video_path)
        print(f"📦 Video exceeds size limit ({info.file_size_gb:.2f}GB > 1.9GB), compressing...", flush=True)
        
        compressed_path = self.compress_video(video_path, job_id=job_id)
        return (compressed_path, True)
    
    def cleanup_compressed(self, job_id: str):
        """
        Clean up compressed files for a job.
        
        Args:
            job_id: Job identifier
        """
        job_compressed_dir = os.path.join(self.compressed_dir, job_id)
        
        if os.path.exists(job_compressed_dir):
            import shutil
            shutil.rmtree(job_compressed_dir)
            print(f"🗑️ Cleaned up compressed files for job {job_id}", flush=True)

