"""
Video format converter for Memories.ai compatibility.

Memories.ai supports: h264, h265, vp9, hevc codecs.
This service checks video codecs and converts unsupported formats.
"""

import os
import subprocess
import json
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.services.ffmpeg_utils import run_ffmpeg, FFmpegError


class VideoConverterService:
    """
    Service for checking and converting video formats.
    
    Ensures videos are in a format compatible with Memories.ai before upload.
    """
    
    # Codecs supported by Memories.ai
    SUPPORTED_CODECS = [
        "h264", "avc1", "avc",      # H.264/AVC variants
        "h265", "hevc", "hev1",     # H.265/HEVC variants
        "vp9", "vp09",              # VP9 variants
    ]
    
    def __init__(self):
        self.settings = get_settings()
    
    def get_video_codec(self, file_path: str) -> Optional[str]:
        """
        Get the video codec of a file using ffprobe.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            Codec name (lowercase) or None if unable to determine
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "v:0",  # First video stream
            file_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                print(f"⚠️ ffprobe failed: {result.stderr[:200]}", flush=True)
                return None
            
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            
            if not streams:
                print(f"⚠️ No video streams found in {file_path}", flush=True)
                return None
            
            codec = streams[0].get("codec_name", "").lower()
            print(f"📹 Video codec detected: {codec}", flush=True)
            return codec
            
        except subprocess.TimeoutExpired:
            print(f"⚠️ ffprobe timed out for {file_path}", flush=True)
            return None
        except json.JSONDecodeError:
            print(f"⚠️ Failed to parse ffprobe output", flush=True)
            return None
        except Exception as e:
            print(f"⚠️ Error getting codec: {e}", flush=True)
            return None
    
    def needs_conversion(self, file_path: str) -> bool:
        """
        Check if video needs conversion for Memories.ai compatibility.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            True if conversion needed, False if already compatible
        """
        codec = self.get_video_codec(file_path)
        
        if codec is None:
            # If we can't determine codec, try to convert to be safe
            print(f"⚠️ Could not determine codec, will attempt conversion", flush=True)
            return True
        
        # Check if codec is in supported list
        is_supported = codec in self.SUPPORTED_CODECS
        
        if is_supported:
            print(f"✅ Video codec '{codec}' is supported by Memories.ai", flush=True)
        else:
            print(f"⚠️ Video codec '{codec}' is NOT supported, conversion needed", flush=True)
            
        return not is_supported
    
    def convert_to_h264(self, input_path: str, output_path: Optional[str] = None) -> str:
        """
        Convert video to H.264 format using FFmpeg.
        
        Args:
            input_path: Path to the input video
            output_path: Optional output path (auto-generated if not provided)
            
        Returns:
            Path to the converted video
            
        Raises:
            Exception: If conversion fails
        """
        if output_path is None:
            # Generate output path next to input
            input_file = Path(input_path)
            output_path = str(input_file.parent / f"{input_file.stem}_h264.mp4")
        
        print(f"🔄 Converting video to H.264: {input_path}", flush=True)
        print(f"📁 Output: {output_path}", flush=True)
        
        # FFmpeg command for H.264 conversion
        # Using libx264 with reasonable quality settings
        cmd = [
            "ffmpeg",
            "-y",                       # Overwrite output
            "-i", input_path,           # Input file
            "-c:v", "libx264",          # H.264 video codec
            "-preset", "medium",        # Balance speed/quality
            "-crf", "23",               # Quality (lower = better, 23 is default)
            "-c:a", "aac",              # AAC audio codec
            "-b:a", "192k",             # Audio bitrate
            "-movflags", "+faststart",  # Web optimization
            "-max_muxing_queue_size", "1024",  # Prevent muxing errors
            output_path
        ]
        
        try:
            run_ffmpeg(cmd, timeout=3600)
            
            # Verify output exists and has content
            if not os.path.exists(output_path):
                raise Exception("Conversion produced no output file")
            
            output_size = os.path.getsize(output_path)
            if output_size == 0:
                raise Exception("Conversion produced empty file")
            
            print(f"✅ Conversion complete: {output_size / (1024*1024):.1f} MB", flush=True)
            return output_path
        except FFmpegError as e:
            # Full stderr stays in server logs (printed); sanitized message is exception str(e)
            print(f"❌ Conversion failed (ffmpeg stderr):\n{e.stderr}", flush=True)
            raise
    
    def ensure_compatible(self, file_path: str) -> str:
        """
        Ensure video is in a Memories.ai compatible format.
        
        Checks the video codec and converts if necessary.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            Path to a compatible video (original if already compatible, 
            or path to converted file)
        """
        print(f"🔍 Checking video format compatibility: {file_path}", flush=True)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file not found: {file_path}")
        
        if not self.needs_conversion(file_path):
            # Already compatible, return original path
            return file_path
        
        # Convert to H.264
        converted_path = self.convert_to_h264(file_path)
        
        return converted_path
    
    def cleanup_converted(self, original_path: str, converted_path: str):
        """
        Clean up converted file if it's different from original.
        
        Call this after successful processing to remove temporary converted files.
        
        Args:
            original_path: Path to original video
            converted_path: Path returned by ensure_compatible()
        """
        if converted_path != original_path and os.path.exists(converted_path):
            try:
                os.remove(converted_path)
                print(f"🗑️ Cleaned up converted file: {converted_path}", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to cleanup converted file: {e}", flush=True)


