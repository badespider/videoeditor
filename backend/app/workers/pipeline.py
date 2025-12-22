"""
Pipeline Worker - Chapter-Based Architecture

Processes video recap jobs using Memories.ai's CHAPTER endpoint:
1. Upload video to Memories.ai
2. Get structured chapters with timestamps (generate_summary)
3. Rewrite each chapter to dramatic narration (Gemini)
4. Generate TTS audio for each chapter (ElevenLabs)
5. Elastic stitch: speed-adjust video to match audio duration

This removes the complex "Visual Hunter" search logic and instead
trusts the timestamps from Memories.ai's chapter grouping.
"""

import os
import re
import sys
import time
import asyncio
import traceback as tb
import secrets
import json
import json as _json
from typing import List, Optional
from pathlib import Path
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


from app.config import get_settings
from app.models import JobStatus
from app.services.job_manager import JobManager
from app.services.storage import StorageService
from app.services.memories_client import MemoriesAIClient
from app.services.script_generator import ScriptGenerator
from app.services.elevenlabs_client import ElevenLabsClient
from app.services.video_editor import VideoEditorService
from app.services.video_compressor import VideoCompressor
from app.services.audio_segmenter import AudioSegmenter
from app.services.video_converter import VideoConverterService
from app.services.copyright_protector import CopyrightProtector, ProtectedScene
from app.services.character_extractor import CharacterExtractor
from app.services.character_database import CharacterDatabase
from app.services.ffmpeg_utils import run_ffmpeg_capture, FFmpegError, sanitize_ffmpeg_stderr
# VideoIndexer (sentence_transformers) is optional; import lazily when needed.


@dataclass
class ChapterScene:
    """A processed chapter ready for stitching."""
    id: int
    title: str
    narration: str
    audio_path: str
    audio_duration: float
    video_start: float  # From chapter timestamp
    video_end: float    # From chapter timestamp
    

def parse_time(time_str: str) -> float:
    """
    Convert timestamp string to seconds.
    
    Handles formats:
    - "00:01:30" (HH:MM:SS)
    - "01:30" (MM:SS)
    - "90" (seconds)
    - "1:30.5" (MM:SS.ms)
    
    Args:
        time_str: Timestamp string
        
    Returns:
        Time in seconds as float
    """
    if not time_str:
        return 0.0
    
    # Already a number
    if isinstance(time_str, (int, float)):
        return float(time_str)
    
    time_str = str(time_str).strip()
    
    # Try direct float conversion first
    try:
        return float(time_str)
    except ValueError:
        pass
    
    # Parse HH:MM:SS or MM:SS format
    parts = time_str.split(":")
    
    try:
        if len(parts) == 3:
            # HH:MM:SS
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            # MM:SS
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        else:
            return float(time_str)
    except (ValueError, TypeError):
        return 0.0


def parse_original_audio_marker(narration: str) -> tuple:
    """
    Parse ORIGINAL_AUDIO marker from narration text.
    
    Marker format: [ORIGINAL_AUDIO:start:end:speaker]
    
    Args:
        narration: Narration text that may contain a marker
        
    Returns:
        Tuple of (narration_text, marker_info) where:
        - narration_text: Text without the marker
        - marker_info: Dict with start, end, speaker or None if no marker
    """
    import re
    
    # Pattern: [ORIGINAL_AUDIO:start:end:speaker]
    pattern = r'\[ORIGINAL_AUDIO:([\d.]+):([\d.]+):([^\]]+)\]'
    
    match = re.search(pattern, narration)
    
    if not match:
        return (narration, None)
    
    start = float(match.group(1))
    end = float(match.group(2))
    speaker = match.group(3)
    
    # Remove the marker from narration
    narration_text = narration[:match.start()].rstrip()
    
    marker_info = {
        "start": start,
        "end": end,
        "speaker": speaker
    }
    
    return (narration_text, marker_info)


class PipelineWorker:
    """
    Worker that processes video recap jobs using Chapter-Based architecture.
    
    The workflow:
    1. Upload to Memories.ai -> Process video
    2. Get Chapters (generate_summary) -> Timestamped story segments
    3. Rewrite (Gemini) -> Dramatic narration
    4. Generate Audio (ElevenLabs) -> TTS with timing
    5. Elastic Stitch (FFmpeg) -> Speed-adjust video to match audio
    
    Key insight: We TRUST the chapter timestamps from Memories.ai,
    eliminating the need for complex visual search.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.job_manager = JobManager()
        self.storage = StorageService()
        self.memories_client = MemoriesAIClient()
        self.script_generator = ScriptGenerator()
        self.elevenlabs = ElevenLabsClient()
        self.video_editor = VideoEditorService()
        self.video_compressor = VideoCompressor()
        self.audio_segmenter = AudioSegmenter()
        self.video_converter = VideoConverterService()
        self.character_extractor = CharacterExtractor()
    
    def _clean_narrations(self, narrations: List[str]) -> List[str]:
        """
        Post-process ALL narrations to remove meta-language and clean up text.
        
        This is a safety net that cleans up narration regardless of source
        (Gemini, Video Chat, or raw summaries).
        
        Enhanced with deflowering filter to remove all cringey dramatic language.
        
        Args:
            narrations: List of narration strings
            
        Returns:
            Cleaned narration strings
        """
        import re
        
        cleaned = []
        
        # Daily dose of cringe - dramatic words/phrases to remove
        DAILY_DOSE_OF_CRINGE = [
            'suddenly', 'shocked', 'realizing', 'determination', 
            'heart pounding', 'blood boiling', 'tears streaming',
            'eyes wide', 'gasps', 'dramatically', 'emotionally',
            'some stories are meant to be told', 'heart heavy',
            'weight of', 'burning in his eyes', 'burning in her eyes',
            'steeled himself', 'steeled herself', 'visibly shaken',
            'visibly upset', 'visibly shocked', 'caught off guard',
            'completely off guard', 'shocking discovery', 'devastating',
            'unleashes', 'unleashing', 'realizes', 'realization',
            'determined resolve', 'with determination', 'feels the weight',
            'weight of responsibility', 'heavy with', 'etched with',
            'filled with', 'showing', 'betraying nothing', 'a mixture of'
        ]
        
        # Patterns to remove (meta-language about the video/film/scene)
        meta_patterns = [
            # Opening phrases - documentary/screenplay style
            r'^The (video|film|movie|scene|camera|shot|footage|screen|show) (opens?|shows?|begins?|starts?|depicts?|displays?|reveals?|focuses?|cuts?|transitions?|shifts?|pans?|zooms?|plunges?|flickers?)[^.]{0,200}\.\s*',
            r'^(We see|We watch|We observe|The viewer sees|The audience sees)[^.]{0,200}\.\s*',
            r'^(This section|This scene|This part|This chapter|This segment)[^.]{0,200}\.\s*',
            r'^(In a dimly lit|In the dimly lit|In a dark|In the dark)[^.]{0,200}\.\s*',
            r'^The bustling[^.]{0,200}\.\s*',
            
            # Mid-sentence meta-language (expanded)
            r'[,.]?\s*(the scene|the camera|the shot|the video|the film|the screen|the show) (shows?|reveals?|depicts?|displays?|cuts? to|transitions? to|shifts? to|pans? to|focuses? on|plunges? into|flickers?)[^,.]{0,200}[,.]',
            r'[,.]?\s*(we see|we watch|we observe|the viewer sees)[^,.]{0,200}[,.]',
            r'[,.]?\s*on[- ]?screen[^,.]{0,200}[,.]',
            r'[,.]?\s*their expressions? suggesting[^,.]{0,200}[,.]',
            r'[,.]?\s*his (face|expression) (etched|filled|showing)[^,.]{0,200}[,.]',
            r'[,.]?\s*her (face|expression) (etched|filled|showing)[^,.]{0,200}[,.]',
            
            # Documentary-style openings (these should be storytelling, not scene descriptions)
            r'^The bustling streets of[^.]{0,200}\.\s*',
            r'^The (setting|narrative|focus) (abruptly |suddenly |)?(changes?|shifts?|takes?|moves?)[^.]{0,200}\.\s*',
            r'^(Amidst|Amongst|Amid) the[^.]{0,200}\.\s*',
            
            # Ending commentary
            r'\.\s*(This creates?|This establishes?|This suggests?|This hints?|This implies?|This indicates?)[^.]{0,200}\.?$',
            r'\.\s*(What will happen|What next|Who will|Is this)[^.]{0,200}\??$',
            
            # Chapter labels
            r'^CHAPTER\s*\d+\s*(\[[^\]]*\])?\s*:?\s*',
            r'^Ch\.\s*\d+\s*:?\s*',
            
            # On-screen text references
            r"['\"][^'\"]*Studios['\"][^.]*\.",
            r'[Tt]ext (appears?|displays?|reads?|states?|shows?)[^.]{0,200}\.',
            r'[Ss]ubtitles? (reveal|show|state|indicate|read)[^.]{0,200}\.',
            r'[Rr]ussian (text|subtitles?|words?)[^.]{0,200}\.',
            r'The (words?|text|title|message|screen) ["\'][^"\']*["\'][^.]{0,200}\.',
            
            # Passive visual descriptions
            r', (who is then|which is then|that is then)[^,.]{0,200}[,.]',
        ]
        
        # Phrases to replace with better alternatives
        replacements = [
            # Generic descriptions -> remove or simplify
            (r'[Aa] figure (with|in|wearing)[^,.]* ', ''),
            (r'[Aa] person (with|in|wearing)[^,.]* ', ''),
            (r'[Tt]he protagonist ', ''),
            (r'[Tt]he character ', ''),
            (r'[Ss]omeone ', ''),
            (r'[Aa] creature ', 'the creature '),
            
            # Vague references that should be character names
            # These are common patterns from Memories.ai descriptions
            (r'[Tt]he youth,? ', ''),  # Remove "the youth" - often overused
            (r'[Tt]he young person,? ', ''),
            (r'[Aa] youth,? ', ''),
            (r'[Aa] young person,? ', ''),
            (r'[Aa] man in a (white |black |sharp |sharply tailored |)suit,? ', ''),
            (r'[Tt]he man in a (white |black |sharp |sharply tailored |)suit,? ', ''),
            (r'[Aa] man in a fedora,? ', ''),
            (r'[Tt]he man in a fedora,? ', ''),
            (r'[Aa] woman in [^,.]+ ', ''),
            (r'[Tt]he woman in [^,.]+ ', ''),
            (r'[Aa] man with (messy |)[a-z]+ hair,? ', ''),
            (r'[Tt]he man with (messy |)[a-z]+ hair,? ', ''),
            
            # Passive visual descriptions -> active
            (r'appears to be ', 'is '),
            (r'seems to be ', 'is '),
            (r'is shown ', ''),
            (r'is seen ', ''),
            (r'is displayed ', ''),
            (r'is revealed ', ''),
            (r'is depicted ', ''),
            (r'can be seen ', ''),
            (r'is engrossed in ', ''),
            (r', his brow furrowed with concern', ''),
            (r', her brow furrowed with concern', ''),
            (r'their expressions? suggesting[^,.]*', ''),
            (r'his expression betraying nothing', ''),
            (r'his expression (a mixture|filled|showing)[^,.]*', ''),
            (r'her expression (a mixture|filled|showing)[^,.]*', ''),
            
            # Scene-setting to remove
            (r', leaving (him|her|them) visibly[^,.]*', ''),
            (r', (a|an) vulnerable figure[^,.]*', ''),
            (r', casting[^,.]*shadows[^,.]*', ''),
            (r', its (purpose|significance|meaning)[^,.]*', ''),
            (r', adding another layer[^,.]*', ''),
            
            # Cleanup
            (r'\s+', ' '),  # Multiple spaces
            (r'\.\s*\.', '.'),  # Double periods
            (r'^\s*[,.]', ''),  # Leading punctuation
            (r',\s*,', ','),  # Double commas
        ]
        
        for narration in narrations:
            if not narration:
                cleaned.append("")
                continue
            
            text = str(narration)
            
            # Deflowering filter: Remove all cringey dramatic language
            for cringe in DAILY_DOSE_OF_CRINGE:
                # Case-insensitive removal with word boundaries
                pattern = r'\b' + re.escape(cringe) + r'\b'
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            
            # Remove redundant adjectives (very, really, extremely, totally)
            text = re.sub(r'\b(very|really|extremely|totally|completely|absolutely)\s+', '', text, flags=re.IGNORECASE)
            
            # Apply removal patterns
            for pattern in meta_patterns:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            
            # Apply replacements
            for pattern, replacement in replacements:
                text = re.sub(pattern, replacement, text)
            
            # Final cleanup
            text = text.strip()
            text = re.sub(r'\s+', ' ', text)  # Normalize spaces
            text = re.sub(r'\s*,\s*,', ',', text)  # Remove double commas
            text = re.sub(r'\.\s*\.', '.', text)  # Remove double periods
            
            # If we stripped too much, keep original but clean basic stuff
            if len(text) < 20 and len(narration) > 50:
                text = narration
                # At minimum, remove chapter labels
                text = re.sub(r'^CHAPTER\s*\d+[^:]*:\s*', '', text, flags=re.IGNORECASE)
            
            cleaned.append(text)
        
        return cleaned
    
    def _split_user_script_into_chapters(self, script_text: str, chapters: List[dict]) -> List[str]:
        """
        Split a user-provided script into N chapter narrations without rewriting the text.

        Strategy:
        - Prefer explicit chapter delimiters if present (e.g. "=== Chapter").
        - Otherwise, split into sentences and allocate sequential chunks proportionally
          to chapter durations, ensuring at least 1 sentence per chapter.
        """
        script_text = (script_text or "").strip()
        if not script_text:
            return []

        n = len(chapters or [])
        if n <= 0:
            return [script_text]

        # Explicit delimiter path
        if "=== Chapter" in script_text or "=== CHAPTER" in script_text:
            parts = []
            buf = []
            for line in script_text.splitlines():
                if line.strip().lower().startswith("=== chapter"):
                    if buf:
                        parts.append("\n".join(buf).strip())
                        buf = []
                    continue
                buf.append(line)
            if buf:
                parts.append("\n".join(buf).strip())

            parts = [p for p in parts if p]
            if len(parts) >= n:
                return parts[:n]
            # If fewer parts than chapters, fall back to sentence allocation below.

        # Sentence allocation path
        sentences = self.audio_segmenter._split_into_sentences(script_text)
        sentences = [s.strip() for s in sentences if s and s.strip()]
        if not sentences:
            return [script_text] * n

        # Compute chapter weights by duration
        weights = []
        for ch in chapters:
            try:
                s = parse_time(ch.get("start", 0))
                e = parse_time(ch.get("end", s + 10))
                dur = max(1.0, float(e) - float(s))
            except Exception:
                dur = 60.0
            weights.append(dur)

        total_weight = sum(weights) if weights else float(n)
        remaining_sentences = len(sentences)
        remaining_weight = float(total_weight)

        narrations: List[str] = []
        idx = 0
        for i in range(n):
            chapters_left = n - i
            if i == n - 1:
                count = remaining_sentences
            else:
                # Proportional allocation of remaining sentences.
                w = float(weights[i]) if i < len(weights) else 1.0
                frac = (w / remaining_weight) if remaining_weight > 0 else (1.0 / chapters_left)
                count = int(round(remaining_sentences * frac))
                # Ensure at least 1 sentence and leave enough for the remaining chapters.
                count = max(1, count)
                max_allowed = max(1, remaining_sentences - (chapters_left - 1))
                count = min(count, max_allowed)

            chunk = " ".join(sentences[idx:idx + count]).strip()
            narrations.append(chunk)

            idx += count
            remaining_sentences -= count
            remaining_weight -= float(weights[i]) if i < len(weights) else 1.0

        return narrations
    
    def _compress_for_memories(self, video_path: str, job_id: str) -> tuple:
        """
        Compress video for Memories.ai processing with balanced quality.
        
        Uses 720p to preserve enough detail for AI recognition of:
        - Non-human characters (aliens, armored figures)
        - Masked/helmeted characters
        - Dark or stylized sci-fi scenes
        
        Args:
            video_path: Path to source video
            job_id: Job identifier for temp files
            
        Returns:
            Tuple of (output_path, was_compressed)
        """
        import subprocess
        
        # Get video info
        info = self.video_compressor.get_video_info(video_path)
        
        # Determine target resolution.
        # USER REQUIREMENT: Never compress below 720p - preserve original resolution if >= 720p
        # Only downscale if video is > 720p and file size > 400MB
        # If video is already <= 720p, only compress if file size > 400MB (bitrate reduction only)
        
        # Never downscale below 720p - preserve original resolution
        if info.height <= 720:
            target_height = info.height
            scale_filter = None  # no scaling - preserve original resolution
            print(f"📐 Preserving original resolution: {info.height}p (not downscaling below 720p)", flush=True)
        else:
            # Only downscale if video is > 720p
            target_height = 720
            scale_filter = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1"
            print(f"📐 Downscaling from {info.height}p to 720p", flush=True)
        
        # Memories.ai frequently gets stuck at UNPARSE if the MP4 isn't "faststart" (moov atom at the front),
        # or if the container/streams are weird. Even when size is OK, we should at least REMUX to faststart.
        # We'll only TRANSCODE when needed (file size > 400MB, bitrate too high, or wrong codec).
        needs_transcode = (
            info.file_size_mb > 400 or
            (info.height > 720) or  # Only transcode if downscaling is needed
            info.bitrate_kbps > 2500 or
            (info.codec or "").lower() != "h264"
        )
        
        # Always remux to faststart if we aren't transcoding, to avoid UNPARSE.
        if not needs_transcode:
            print(f"📦 Remuxing for Memories.ai faststart ({info.file_size_mb:.0f}MB, {info.height}p, {info.codec})...", flush=True)
            compressed_dir = os.path.join(self.settings.temp_dir, job_id, "compressed")
            os.makedirs(compressed_dir, exist_ok=True)
            output_path = os.path.join(compressed_dir, "optimized.mp4")
            
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path
            ]
            
            try:
                result = run_ffmpeg_capture(cmd, check=False, timeout=600)
                if result.returncode != 0:
                    print(f"⚠️ Faststart remux failed:\n{sanitize_ffmpeg_stderr(result.stderr or '')}", flush=True)
                    return (video_path, False)
                
                remuxed_size = os.path.getsize(output_path) / (1024 ** 2)
                print(f"✅ Remuxed faststart: {info.file_size_mb:.0f}MB -> {remuxed_size:.0f}MB", flush=True)
                return (output_path, True)
            except Exception as e:
                print(f"⚠️ Faststart remux error: {e}", flush=True)
            return (video_path, False)
        
        action = "downscaling" if info.height > 720 else "compressing"
        print(f"📦 {action.capitalize()} for Memories.ai ({info.file_size_mb:.0f}MB, {info.height}p -> {target_height}p)...", flush=True)
        
        # Create output path
        compressed_dir = os.path.join(self.settings.temp_dir, job_id, "compressed")
        os.makedirs(compressed_dir, exist_ok=True)
        output_path = os.path.join(compressed_dir, "optimized.mp4")
        
        # Calculate target bitrate to achieve ~400MB max file size (but keep within a reasonable range).
        # Adjust minimum bitrate based on resolution to maintain quality
        duration_minutes = info.duration_seconds / 60
        if info.duration_seconds > 0:
            calculated_bitrate = int((400 * 8 * 1024) / info.duration_seconds)  # kbps for ~400MB
            # Higher resolution needs higher bitrate to maintain quality
            if target_height >= 1080:
                min_kbps = 2000  # Minimum for 1080p
                max_kbps = 4000
            elif target_height >= 720:
                min_kbps = 1200  # Minimum for 720p
                max_kbps = 2500
            else:
                min_kbps = 800  # Minimum for lower resolutions
                max_kbps = 1800
            target_bitrate_kbps = max(min_kbps, min(calculated_bitrate, max_kbps))
        else:
            # Default based on target resolution
            target_bitrate_kbps = 2000 if target_height >= 1080 else (1500 if target_height >= 720 else 1000)
        
        target_bitrate = f"{target_bitrate_kbps}k"
        
        vf = scale_filter if scale_filter else "null"
        
        # Use FFmpeg progress reporting to a temporary file for monitoring
        progress_file = os.path.join(self.settings.temp_dir, job_id, "compressed", "ffmpeg_progress.txt")
        os.makedirs(os.path.dirname(progress_file), exist_ok=True)
        
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vf", f"{vf},fps=30" if vf != "null" else "fps=30",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-b:v", target_bitrate,
            "-maxrate", f"{int(target_bitrate_kbps * 1.2)}k",
            "-bufsize", "3000k",
            "-c:a", "aac",
            "-b:a", "64k",
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            "-progress", progress_file,
            "-nostats",  # Suppress stats to stderr, use progress file instead
            output_path
        ]
        
        estimated_size_mb = (target_bitrate_kbps * info.duration_seconds) / (8 * 1024) if info.duration_seconds > 0 else 0
        scale_info = f"{info.height}p -> {target_height}p" if info.height != target_height else f"{target_height}p (preserved)"
        print(f"📦 Transcoding @ {target_bitrate} with {scale_info} ({duration_minutes:.1f} min → ~{estimated_size_mb:.0f}MB)", flush=True)
        
        # Calculate timeout based on video duration (allow 2x video duration + 10 minutes overhead)
        # For very long videos, cap at 2 hours to prevent indefinite hangs
        compression_timeout = min(
            max(int(info.duration_seconds * 2) + 600, 900),  # At least 15 min, or 2x duration + 10 min
            7200  # Max 2 hours
        )
        print(f"⏱️ Compression timeout: {compression_timeout // 60} minutes (video is {duration_minutes:.1f} min)", flush=True)

        # Use Popen to monitor progress in real-time
        import subprocess
        import threading
        
        start_time = time.time()
        compression_complete = False
        compression_error = None
        
        def monitor_progress():
            """Monitor FFmpeg progress and log periodically"""
            nonlocal compression_complete
            last_log_time = start_time
            
            while not compression_complete:
                try:
                    if os.path.exists(progress_file):
                        with open(progress_file, 'r') as f:
                            lines = f.readlines()
                            for line in lines:
                                if line.startswith("out_time_ms="):
                                    try:
                                        out_time_ms = int(line.split("=")[1].strip())
                                        out_time_sec = out_time_ms / 1000000.0
                                        progress_pct = (out_time_sec / info.duration_seconds * 100) if info.duration_seconds > 0 else 0
                                        
                                        # Log progress every 30 seconds
                                        current_time = time.time()
                                        if current_time - last_log_time >= 30:
                                            elapsed_min = (current_time - start_time) / 60
                                            print(f"📊 Compression progress: {progress_pct:.1f}% ({out_time_sec:.0f}s / {info.duration_seconds:.0f}s, elapsed: {elapsed_min:.1f} min)", flush=True)
                                            last_log_time = current_time
                                    except:
                                        pass
                except:
                    pass
                
                time.sleep(5)  # Check every 5 seconds
        
        try:
            # Start progress monitor
            progress_monitor = threading.Thread(target=monitor_progress, daemon=True)
            progress_monitor.start()
            
            # Run FFmpeg
            result = run_ffmpeg_capture(cmd, check=False, timeout=compression_timeout)
            compression_complete = True


            if result.returncode != 0:
                print(f"⚠️ Compression failed:\n{sanitize_ffmpeg_stderr(result.stderr or '')}", flush=True)
                return (video_path, False)
            
            # Get compressed file size
            compressed_size = os.path.getsize(output_path) / (1024 ** 2)
            print(f"✅ Compressed: {info.file_size_mb:.0f}MB -> {compressed_size:.0f}MB ({(1 - compressed_size/info.file_size_mb)*100:.0f}% smaller)", flush=True)
            
            return (output_path, True)
            
        except FFmpegError as e:
            compression_complete = True
            # Should not be hit since we use check=False, but keep for safety.
            print(f"⚠️ Compression ffmpeg error:\n{e.stderr}", flush=True)
            return (video_path, False)
        except subprocess.TimeoutExpired:
            compression_complete = True
            elapsed = time.time() - start_time
            print(f"❌ Compression timed out after {elapsed/60:.1f} minutes (timeout: {compression_timeout/60:.1f} min)", flush=True)
            print(f"⚠️ Video is very long ({duration_minutes:.1f} min). Consider using a shorter video or increasing timeout.", flush=True)
            return (video_path, False)
        except Exception as e:
            compression_complete = True
            print(f"⚠️ Compression error: {e}, using original video", flush=True)
            return (video_path, False)
        finally:
            # Clean up progress file
            try:
                if os.path.exists(progress_file):
                    os.remove(progress_file)
            except:
                pass
    
    def _merge_small_chapters(self, chapters: List[dict], min_duration_seconds: float = 60.0) -> List[dict]:
        """
        Merge consecutive small chapters into larger scene-level chapters.
        
        Memories.ai often returns micro-chapters (10-30 seconds each), but Gemini
        needs substantial content to write meaningful narration. This method
        combines small chapters until each is at least min_duration_seconds long.
        
        Args:
            chapters: List of chapter dicts from Memories.ai
            min_duration_seconds: Minimum duration for a chapter (default 60s)
            
        Returns:
            List of merged chapters, each at least min_duration_seconds long
        """
        if not chapters:
            return chapters
        
        merged = []
        current_group = None
        
        for ch in chapters:
            # Parse start/end times
            start = ch.get("start", 0)
            end = ch.get("end", 0)
            
            # Handle string timestamps
            if isinstance(start, str):
                try:
                    if ":" in start:
                        parts = start.split(":")
                        start = float(parts[0]) * 60 + float(parts[1]) if len(parts) == 2 else float(start)
                    else:
                        start = float(start)
                except:
                    start = 0
            
            if isinstance(end, str):
                try:
                    if ":" in end:
                        parts = end.split(":")
                        end = float(parts[0]) * 60 + float(parts[1]) if len(parts) == 2 else float(end)
                    else:
                        end = float(end)
                except:
                    end = start + 30
            
            start = float(start)
            end = float(end) if end > start else start + 30
            
            if current_group is None:
                # Start new group
                current_group = {
                    "start": start,
                    "end": end,
                    "title": ch.get("title", ""),
                    "description": ch.get("description", "") or ch.get("summary", ""),
                    "merged_count": 1
                }
            else:
                group_duration = current_group["end"] - current_group["start"]
                
                if group_duration < min_duration_seconds:
                    # Merge into current group
                    current_group["end"] = end
                    new_desc = ch.get("description", "") or ch.get("summary", "")
                    if new_desc:
                        current_group["description"] += " " + new_desc
                    current_group["merged_count"] += 1
                else:
                    # Current group is big enough, save it and start new
                    merged.append(current_group)
                    current_group = {
                        "start": start,
                        "end": end,
                        "title": ch.get("title", ""),
                        "description": ch.get("description", "") or ch.get("summary", ""),
                        "merged_count": 1
                    }
        
        # Don't forget the last group
        if current_group:
            merged.append(current_group)
        
        return merged
    
    def run(self):
        """Main worker loop."""
        print("🚀 Pipeline worker started (Chapter-Based mode)", flush=True)
        
        while True:
            try:
                job_id = self.job_manager.get_next_job()
                
                if job_id:
                    print(f"📦 Processing job: {job_id}", flush=True)
                    asyncio.run(self.process_job(job_id))
                else:
                    # No jobs, wait before polling again
                    time.sleep(2)
                    
            except KeyboardInterrupt:
                print("👋 Worker shutting down...", flush=True)
                break
            except Exception as e:
                print(f"❌ Worker error: {e}", flush=True)
                tb.print_exc()
                time.sleep(5)
    
    async def process_job(self, job_id: str):
        """
        Process a single job through the Chapter-Based pipeline.
        
        Args:
            job_id: The job ID to process
        """
        job_data = self.job_manager.get_job(job_id)
        if not job_data:
            print(f"Job {job_id} not found")
            return
        
        # IMMEDIATELY update status to PROCESSING so frontend shows correct status
        print(f"🔄 Updating job {job_id} status to PROCESSING...", flush=True)
        self.job_manager.update_job(
            job_id,
            status=JobStatus.PROCESSING,
            progress=1,
            current_step="Initializing job..."
        )
        print(f"✅ Job {job_id} status updated to PROCESSING", flush=True)
        
        video_id = job_data["video_id"]
        target_duration_minutes = job_data.get("target_duration_minutes")
        character_guide = job_data.get("character_guide", "")
        enable_scene_matcher = job_data.get("enable_scene_matcher", False)
        
        # Create working directory
        work_dir = os.path.join(self.settings.temp_dir, job_id)
        audio_dir = os.path.join(work_dir, "audio")
        
        for d in [work_dir, audio_dir]:
            os.makedirs(d, exist_ok=True)
        
        video_no = None  # Track for cleanup
        
        try:

            # ==== Step 1: Download video ====
            self.job_manager.update_job(
                job_id,
                status=JobStatus.PROCESSING,
                progress=5,
                current_step="Downloading video..."
            )

            local_video = os.path.join(work_dir, "source.mp4")
            self.storage.download_video(video_id, local_video)

            # ==== Step 1.25: Convert video format if needed for Memories.ai ====
            self.job_manager.update_job(
                job_id,
                progress=6,
                current_step="Checking video format compatibility..."
            )

            # Check if video needs format conversion for Memories.ai
            converted_video = self.video_converter.ensure_compatible(local_video)

            if converted_video != local_video:
                print(f"✅ Video converted to compatible format: {converted_video}", flush=True)
                # Use converted video for processing
                local_video = converted_video
            
            # ==== Step 1.5: Compress video for faster Memories.ai processing ====
            self.job_manager.update_job(
                job_id,
                progress=7,
                current_step="Optimizing video for processing..."
            )

            # Compress to 720p for faster Memories.ai processing
            # This significantly reduces processing time without losing important content
            compressed_video, was_compressed = self._compress_for_memories(local_video, job_id)

            if was_compressed:
                print(f"✅ Video compressed for faster processing", flush=True)
                upload_video = compressed_video
            else:
                upload_video = local_video
            
            # ==== Step 2: Upload to Memories.ai ====
            self.job_manager.update_job(
                job_id,
                progress=10,
                current_step="Uploading to Memories.ai..."
            )
            
            # Check if webhook mode is enabled
            webhook_base_url = self.settings.webhook.base_url
            callback_url = None
            use_webhook_mode = False
            
            # Validate webhook URL - must be a real URL, not a placeholder
            webhook_is_valid = (
                webhook_base_url and 
                webhook_base_url.startswith("https://") and
                "abc123" not in webhook_base_url and  # Reject placeholder URLs
                "example" not in webhook_base_url and
                len(webhook_base_url) > 15  # Must be a real URL
            )
            
            if webhook_is_valid:
                # Build callback URL with job_id parameter
                # Generate a per-job token to prevent spoofed callbacks.
                # Stored in Redis with TTL so Memories.ai retries still work.
                token = secrets.token_urlsafe(32)
                try:
                    self.job_manager.redis.setex(f"memories:webhook_token:{job_id}", 6 * 60 * 60, token)
                except Exception as e:
                    print(f"⚠️ Failed to store webhook token in Redis; falling back to polling mode: {e}", flush=True)
                    token = None
                
                if token:
                    callback_url = f"{webhook_base_url}/api/webhooks/memories?job_id={job_id}&token={token}"
                use_webhook_mode = True
                print(f"\n{'='*60}", flush=True)
                print(f"🔔 WEBHOOK MODE ENABLED", flush=True)
                print(f"   Callback URL: {callback_url}", flush=True)
                print(f"   No polling required - Memories.ai will notify us!", flush=True)
                print(f"{'='*60}\n", flush=True)
            else:
                if webhook_base_url:
                    print(f"⚠️ Webhook URL appears to be a placeholder: {webhook_base_url}", flush=True)
                else:
                    print(f"⚠️ Webhook not configured (WEBHOOK_BASE_URL not set)", flush=True)
                print(f"   Using polling mode instead", flush=True)

            # Upload with callback URL if webhook mode is enabled
            upload_response = await self.memories_client.upload_video(
                upload_video, 
                unique_id=job_id,
                callback_url=callback_url
            )
            video_no = upload_response.video_no

            print(f"📤 Uploaded to Memories.ai: {video_no}", flush=True)
            
            # Wait for processing
            step_msg = "Processing video..." + (" (webhook mode)" if use_webhook_mode else " (polling mode)")
            self.job_manager.update_job(
                job_id,
                progress=15,
                current_step=step_msg
            )

            # Track wait time for periodic status updates
            wait_start_time = time.time()
            
            if use_webhook_mode:
                # 🚀 OPTIMIZED: Use webhook-based waiting (0 API calls!)
                processing_complete = await self.memories_client.wait_for_processing_webhook(
                    video_no=video_no,
                    job_id=job_id,
                    unique_id=job_id,
                    max_wait_seconds=1800  # 30 minutes (reduced from 60 for faster failure detection)
                )
            else:
                # Fallback: Use polling (many API calls)
                # Check status periodically and log UNPARSE details
                # Also update job status periodically to keep frontend informed
                async def update_status_periodically():
                    """Update job status every 30 seconds while waiting"""
                    while True:
                        await asyncio.sleep(30)
                        elapsed_min = int((time.time() - wait_start_time) // 60)
                        elapsed_sec = int((time.time() - wait_start_time) % 60)
                        self.job_manager.update_job(
                            job_id,
                            progress=15 + min(5, elapsed_min // 5),  # Gradually increase progress
                            current_step=f"{step_msg} (waiting {elapsed_min}m {elapsed_sec}s...)"
                        )
                
                # Start status updater as background task
                status_updater = asyncio.create_task(update_status_periodically())
                try:
                    processing_complete = await self.memories_client.wait_for_processing(
                        video_no, 
                        unique_id=job_id,
                        max_wait_seconds=1800  # 30 minutes (reduced from 60 for faster failure detection)
                    )
                finally:
                    status_updater.cancel()
                    try:
                        await status_updater
                    except asyncio.CancelledError:
                        pass

            if not processing_complete:
                # Get final status to provide better error message
                final_status, cause = await self.memories_client.get_video_status(video_no, job_id)
                status_str = final_status.value if hasattr(final_status, 'value') else str(final_status)
                
                error_msg = f"Video processing timed out on Memories.ai (30 min limit). Status: {status_str}"
                if cause and cause != "null":
                    error_msg += f". Cause: {cause}"
                error_msg += ". Try a shorter/smaller video or check Memories.ai service status."
                raise Exception(error_msg)
            
            print(f"✅ Video processed by Memories.ai", flush=True)
            
            # ==== Step 2.5: Index video for vector matching (if enabled) ====
            if self.settings.features.vector_matching.enable_vector_matching:
                try:
                    self.job_manager.update_job(
                        job_id,
                        progress=20,
                        current_step="Indexing video for semantic matching..."
                    )
                    
                    try:
                        from app.services.video_indexer import VideoIndexer
                        video_indexer = VideoIndexer()
                        await video_indexer.index_video(video_no)
                        print("✅ Video indexed for vector matching", flush=True)
                    except Exception as e:
                        print(f"⚠️ Vector matching unavailable; skipping indexing: {e}", flush=True)
                except Exception as e:
                    print(f"⚠️ Video indexing failed (will use fallback matching): {e}", flush=True)
                    # Don't fail the job - fallback to existing SceneMatcher
            
            # ==== Step 3: Get Chapters AND Audio Transcription IN PARALLEL ====
            # 🚀 OPTIMIZATION: Run both API calls simultaneously (saves ~50% time)
            self.job_manager.update_job(
                job_id,
                progress=25,
                current_step="Fetching chapters and audio transcription (parallel)..."
            )
            
            print(f"\n{'='*60}", flush=True)
            print(f"🚀 PARALLEL API CALLS: Chapters + Audio Transcription", flush=True)
            print(f"{'='*60}", flush=True)
            
            # Run both calls in parallel
            chapters_task = self.memories_client.generate_summary(
                video_no=video_no,
                unique_id=job_id,
                summary_type="CHAPTER"
            )
            
            audio_task = self.memories_client.get_audio_transcription(
                video_no=video_no,
                unique_id=job_id
            )
            
            # Wait for both to complete
            chapters, audio_transcript = await asyncio.gather(
                chapters_task,
                audio_task,
                return_exceptions=True
            )
            
            # Handle chapters result
            if isinstance(chapters, Exception):
                print(f"❌ Chapters fetch failed: {chapters}", flush=True)
                chapters = None
            
            if not chapters:
                raise Exception("Failed to get chapters from Memories.ai. This could be a temporary API issue - please try again in a few minutes.")
            
            print(f"📖 Got {len(chapters)} chapters from Memories.ai", flush=True)
            
            # Sort chapters by start time to ensure chronological order
            # Memories.ai may return chapters in detection order, not timeline order
            chapters = sorted(chapters, key=lambda ch: parse_time(ch.get("start", 0)))
            print(f"📋 Chapters sorted by start time (chronological order)", flush=True)
            
            # Remove duplicate/overlapping chapters (keep first occurrence)
            deduplicated = []
            last_end = -1
            for ch in chapters:
                ch_start = parse_time(ch.get("start", 0))
                if ch_start >= last_end - 1:  # Allow 1s overlap tolerance
                    deduplicated.append(ch)
                    last_end = parse_time(ch.get("end", ch_start + 10))
                else:
                    print(f"⏭️ Skipping overlapping chapter at {ch_start:.1f}s (ends before {last_end:.1f}s)", flush=True)
            
            if len(deduplicated) < len(chapters):
                print(f"📋 Removed {len(chapters) - len(deduplicated)} overlapping chapters", flush=True)
                chapters = deduplicated
            
            # Merge small chapters into larger scene-level chapters
            # This helps Gemini write longer, more meaningful narrations
            original_count = len(chapters)
            chapters = self._merge_small_chapters(chapters, min_duration_seconds=60.0)
            if len(chapters) < original_count:
                print(f"📦 Merged {original_count} micro-chapters → {len(chapters)} scene chapters (min 60s each)", flush=True)
            
            # Handle audio transcript result
            if isinstance(audio_transcript, Exception):
                print(f"⚠️ Audio transcription failed (non-critical): {audio_transcript}", flush=True)
                audio_transcript = []
            
            if audio_transcript:
                print(f"🎤 Got {len(audio_transcript)} audio transcription segments", flush=True)
                
                # Save transcript for debugging
                transcript_path = os.path.join(work_dir, "audio_transcript.txt")
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write("=== AUDIO TRANSCRIPTION (Direct from Audio Track) ===\n\n")
                    for seg in audio_transcript:
                        speaker = seg.get("speaker", "Unknown")
                        start = seg.get("start", 0)
                        end = seg.get("end", 0)
                        text = seg.get("text", "")
                        f.write(f"[{start:.1f}s - {end:.1f}s] {speaker}: \"{text}\"\n")
            else:
                print(f"⚠️ No audio transcription available", flush=True)
                audio_transcript = []
            
            print(f"{'='*60}\n", flush=True)
            
            # Get video duration for calculating last chapter's end time
            video_duration = self.video_editor.get_media_duration(local_video)
            print(f"📹 Video duration: {video_duration:.1f}s ({video_duration/60:.1f} min)", flush=True)
            
            # ==== VALIDATION: Check if target duration is feasible ====
            if target_duration_minutes:
                target_seconds = target_duration_minutes * 60
                
                # Cannot expand video beyond 2x its original length
                # (would require extreme slow-motion, making it unwatchable)
                max_feasible_duration = video_duration * 2
                
                if target_seconds > max_feasible_duration:
                    # Target is too long - cap it at 2x source duration
                    capped_minutes = (max_feasible_duration / 60)
                    print(f"⚠️ TARGET DURATION VALIDATION:", flush=True)
                    print(f"   Requested: {target_duration_minutes} min ({target_seconds:.0f}s)", flush=True)
                    print(f"   Source video: {video_duration/60:.1f} min ({video_duration:.0f}s)", flush=True)
                    print(f"   Maximum feasible: {capped_minutes:.1f} min (2x source)", flush=True)
                    print(f"   ❌ Cannot expand a {video_duration/60:.1f}-min video to {target_duration_minutes} min!", flush=True)
                    print(f"   📏 Capping target to {capped_minutes:.1f} min to avoid unwatchable slow-motion", flush=True)
                    
                    # Update target to feasible maximum
                    target_duration_minutes = capped_minutes
                    
                    # Update job with warning
                    self.job_manager.update_job(
                        job_id,
                        current_step=f"Note: Target capped to {capped_minutes:.0f}min (source is only {video_duration/60:.0f}min)"
                    )
                elif target_seconds > video_duration:
                    # Target is longer than source but within 2x - still warn
                    print(f"⚠️ Note: Target ({target_duration_minutes}min) > source ({video_duration/60:.1f}min). Video will be slowed down.", flush=True)
            
            # Calculate end times for chapters that don't have them
            # Merged chapters already have correct end times from _merge_small_chapters()
            # Only fill in missing end times for unmerged chapters
            for i, ch in enumerate(chapters):
                existing_end = ch.get("end")
                # Check if end time is missing, zero, or less than start
                ch_start = parse_time(ch.get("start", 0))
                ch_end = parse_time(existing_end) if existing_end else 0
                
                if ch_end <= ch_start:
                    # End time is missing or invalid - calculate from next chapter or video end
                    if i < len(chapters) - 1:
                        ch["end"] = chapters[i + 1].get("start", "0")
                    else:
                        ch["end"] = str(video_duration)
                # Otherwise keep the existing end time (from merge or API)
            
            # ==== Filter out credits and fix extreme chapter durations ====
            filtered_chapters = []
            MAX_CHAPTER_DURATION = 180  # Max 3 minutes per chapter segment
            
            for i, ch in enumerate(chapters):
                title = (ch.get("title", "") or "").lower()
                summary = (ch.get("description", "") or ch.get("summary", "") or "").lower()
                
                # Skip credits sections
                if any(word in title for word in ["credit", "credits", "end credits", "closing"]):
                    print(f"⏭️ Skipping credits chapter: {ch.get('title', '')}", flush=True)
                    continue
                if any(phrase in summary for phrase in ["credits roll", "end credits", "closing credits"]):
                    print(f"⏭️ Skipping credits chapter: {ch.get('title', '')}", flush=True)
                    continue
                
                # Calculate chapter duration
                ch_start = parse_time(ch.get("start", 0))
                ch_end = parse_time(ch.get("end", 0))
                ch_duration = ch_end - ch_start
                
                # Cap extremely long chapters (likely includes credits or is malformed)
                if ch_duration > MAX_CHAPTER_DURATION:
                    print(f"⚠️ Chapter {i+1} too long ({ch_duration:.0f}s), capping to {MAX_CHAPTER_DURATION}s", flush=True)
                    ch["end"] = str(ch_start + MAX_CHAPTER_DURATION)
                
                # Skip chapters that are too short (< 3 seconds)
                if ch_duration < 3:
                    print(f"⏭️ Skipping very short chapter ({ch_duration:.1f}s): {ch.get('title', '')}", flush=True)
                    continue
                
                filtered_chapters.append(ch)
            
            # Replace chapters with filtered list
            if len(filtered_chapters) < len(chapters):
                print(f"📋 Filtered chapters: {len(chapters)} → {len(filtered_chapters)} (removed credits/invalid)", flush=True)
                chapters = filtered_chapters
            
            # Calculate and log average chapter duration
            chapter_durations = []
            for ch in chapters:
                ch_start = parse_time(ch.get("start", 0))
                ch_end = parse_time(ch.get("end", 0))
                duration = ch_end - ch_start
                chapter_durations.append(duration)
            
            if chapter_durations:
                avg_duration = sum(chapter_durations) / len(chapter_durations)
                min_duration = min(chapter_durations)
                max_duration = max(chapter_durations)
                print(f"📊 Chapter Duration Statistics:", flush=True)
                print(f"   Total chapters: {len(chapters)}", flush=True)
                print(f"   Average duration: {avg_duration:.1f}s ({avg_duration/60:.2f} min)", flush=True)
                print(f"   Min duration: {min_duration:.1f}s", flush=True)
                print(f"   Max duration: {max_duration:.1f}s ({max_duration/60:.2f} min)", flush=True)
            
            # Log chapters for debugging
            for i, ch in enumerate(chapters[:5]):
                print(f"    [{i+1}] {ch.get('start', '?')}s - {ch.get('end', '?')}s: {ch.get('title', 'Untitled')[:40]}...", flush=True)
            
            self.job_manager.update_job(
                job_id,
                total_scenes=len(chapters)
            )
            
            # ==== Step 3.5: UNIFIED Movie Data Extraction (1 API call instead of 5!) ====
            # 🚀 OPTIMIZATION: Combines identify_characters, get_plot_summary, 
            #    identify_key_moments, extract_structured_movie_data, and map_speakers_to_characters
            #    into a SINGLE Video Chat call (saves 80% API calls!)
            self.job_manager.update_job(
                job_id,
                progress=30,
                current_step="Extracting movie data (unified call)..."
            )
            
            print(f"\n{'='*60}", flush=True)
            print(f"🚀 UNIFIED EXTRACTION: 1 API call instead of 5", flush=True)
            print(f"   Combines: characters + plot + key_moments + scenes + speaker_mapping", flush=True)
            print(f"{'='*60}", flush=True)
            
            # Use unified extraction method
            unified_data = await self.memories_client.extract_all_movie_data_unified(
                video_no=video_no,
                chapters=chapters,
                audio_transcript=audio_transcript,
                unique_id=job_id
            )
            
            # Extract individual components from unified data
            structured_data = None
            character_guide = character_guide  # Keep user-provided if exists
            plot_summary = ""
            key_moments = []
            speaker_mapping = {}
            
            if unified_data:
                # Build structured_data from unified response
                structured_data = {
                    "title": unified_data.get("title", "Unknown"),
                    "characters": unified_data.get("characters", []),
                    "locations": unified_data.get("locations", []),
                    "factions": unified_data.get("factions", []),
                    "relationships": unified_data.get("relationships", []),
                    "scenes": unified_data.get("scenes", []),
                    "plot_summary": unified_data.get("plot_summary", "")
                }
                
                # Extract character_guide if not provided by user
                if not character_guide and unified_data.get("character_guide"):
                    character_guide = unified_data["character_guide"]
                    print(f"🎭 Character guide from unified extraction", flush=True)
                
                # Extract plot summary
                plot_summary = unified_data.get("plot_summary", "")
                if plot_summary:
                    print(f"📖 Plot summary: {len(plot_summary)} chars", flush=True)
                
                # Extract key moments
                key_moments = unified_data.get("key_moments", [])
                if key_moments:
                    print(f"🎬 Key moments: {len(key_moments)} identified", flush=True)
                
                # Extract speaker mapping and apply to audio transcript
                speaker_mapping = unified_data.get("speaker_mapping", {})
                if speaker_mapping and audio_transcript:
                    print(f"🔊 Applying speaker mapping ({len(speaker_mapping)} mappings)...", flush=True)
                    for seg in audio_transcript:
                        if seg.get("speaker") and seg["speaker"] in speaker_mapping:
                            seg["speaker"] = speaker_mapping[seg["speaker"]]
                    
                    # Update saved transcript with mapped names
                    transcript_path = os.path.join(work_dir, "audio_transcript.txt")
                    with open(transcript_path, "w", encoding="utf-8") as f:
                        f.write("=== AUDIO TRANSCRIPTION (with character names mapped) ===\n\n")
                        f.write(f"Speaker Mapping: {speaker_mapping}\n\n")
                        for seg in audio_transcript:
                            speaker = seg.get("speaker", "Unknown")
                            start = seg.get("start", 0)
                            end = seg.get("end", 0)
                            text = seg.get("text", "")
                            f.write(f"[{start:.1f}s - {end:.1f}s] {speaker}: \"{text}\"\n")
                
                print(f"✅ Unified extraction complete!", flush=True)
            else:
                print(f"⚠️ Unified extraction returned no data", flush=True)
            
            print(f"{'='*60}\n", flush=True)
            
            # ==== Step 3.6: Character Extraction (AI + Visual in Parallel) ====
            # Uses both Gemini (transcript analysis) and Memories.ai (visual analysis)
            # to accurately identify characters for narration
            if self.settings.features.enable_character_extraction:
                try:
                    self.job_manager.update_job(
                        job_id,
                        progress=32,
                        current_step="Extracting characters (AI + Visual)..."
                    )
                    
                    print(f"\n{'='*60}", flush=True)
                    print(f"🎭 CHARACTER EXTRACTION: AI + Visual (Parallel)", flush=True)
                    print(f"{'='*60}", flush=True)
                    
                    # === Phase 3: Load existing characters from database ===
                    series_id = job_data.get("series_id")
                    # Normalize to lowercase for case-insensitive matching
                    if series_id:
                        series_id = series_id.strip().lower()
                    existing_characters = []
                    char_db = None
                    
                    if series_id:
                        try:
                            char_db = CharacterDatabase()
                            existing_characters = char_db.get_series_characters(series_id)
                            if existing_characters:
                                print(f"📚 Loaded {len(existing_characters)} existing characters from series '{series_id}'", flush=True)
                                for char in existing_characters[:3]:
                                    print(f"   ↳ {char.name} ({char.role})", flush=True)
                                if len(existing_characters) > 3:
                                    print(f"   ↳ ... and {len(existing_characters) - 3} more", flush=True)
                            else:
                                print(f"📚 Series '{series_id}' exists but has no saved characters yet", flush=True)
                        except Exception as db_err:
                            print(f"⚠️ Could not load existing characters: {db_err}", flush=True)
                    else:
                        print(f"📚 No series_id provided - character extraction is stateless", flush=True)
                    
                    # Build transcript text from audio transcript
                    transcript_text = ""
                    if audio_transcript:
                        transcript_text = "\n".join([
                            f"{seg.get('speaker', 'Unknown')}: {seg.get('text', '')}"
                            for seg in audio_transcript
                            if seg.get('text')
                        ])
                    
                    # Run AI and Visual extraction in PARALLEL
                    async def empty_list():
                        return []
                    
                    ai_task = self.character_extractor.extract_characters_ai(
                        transcript=transcript_text,
                        plot_summary=plot_summary,
                        existing_characters=existing_characters  # Pass existing chars for context
                    ) if transcript_text else empty_list()
                    
                    visual_task = self.character_extractor.extract_characters_visual(
                        video_no=video_no,
                        unique_id=job_id
                    ) if video_no else empty_list()
                    
                    # Wait for both to complete
                    ai_characters, visual_characters = await asyncio.gather(
                        ai_task,
                        visual_task,
                        return_exceptions=True
                    )
                    
                    # Handle exceptions gracefully
                    if isinstance(ai_characters, Exception):
                        print(f"⚠️ AI extraction failed: {ai_characters}", flush=True)
                        ai_characters = []
                    if isinstance(visual_characters, Exception):
                        print(f"⚠️ Visual extraction failed: {visual_characters}", flush=True)
                        visual_characters = []
                    
                    print(f"📊 Extraction results: {len(ai_characters)} from AI, {len(visual_characters)} from Visual", flush=True)
                    
                    # Merge all three sources with priority ordering
                    merged_characters = self.character_extractor.merge_all_sources(
                        ai_characters=ai_characters,
                        visual_characters=visual_characters,
                        existing_characters=existing_characters  # Existing gets highest priority
                    )
                    
                    # === Phase 3: Save merged characters back to database ===
                    if series_id and merged_characters and char_db:
                        try:
                            char_db.save_series_characters(series_id, merged_characters)
                            print(f"💾 Saved {len(merged_characters)} characters to series '{series_id}'", flush=True)
                        except Exception as save_err:
                            print(f"⚠️ Could not save characters to database: {save_err}", flush=True)
                    
                    if merged_characters:
                        # Build character guide from merged characters
                        merged_character_guide = self.character_extractor.build_character_guide(merged_characters)
                        
                        # Merge with existing character guide (user-provided or from unified extraction)
                        if character_guide and merged_character_guide:
                            character_guide = f"{character_guide}\n{merged_character_guide}"
                            print(f"🎭 Merged character guide with existing ({len(merged_character_guide.splitlines())} new mappings)", flush=True)
                        elif merged_character_guide:
                            character_guide = merged_character_guide
                            print(f"🎭 Using merged character guide ({len(merged_character_guide.splitlines())} mappings)", flush=True)
                        
                        # Log extracted characters
                        for char in merged_characters[:5]:
                            desc_preview = char.description[:40] + "..." if len(char.description) > 40 else char.description
                            source = "👁️" if char.id.startswith("char_vis_") else "🤖"
                            print(f"   {source} {char.name} ({char.role}, conf: {char.confidence:.2f}): {desc_preview}", flush=True)
                        if len(merged_characters) > 5:
                            print(f"   ... and {len(merged_characters) - 5} more characters", flush=True)
                    
                    print(f"{'='*60}\n", flush=True)
                    
                except Exception as char_err:
                    print(f"⚠️ Character extraction failed (non-critical): {char_err}", flush=True)
                    tb.print_exc()
                    # Continue without character extraction - narration will still work
            
            # ==== Step 4: Rewrite Chapters with Video Chat (More Accurate) ====
            self.job_manager.update_job(
                job_id,
                progress=35,
                current_step="Writing narration with Video Chat..."
            )
            
            # Calculate target duration for fallback mode only
            # For structured data mode, we use ACTUAL CLIP DURATION to avoid speedup
            target_seconds = None
            
            if target_duration_minutes:
                target_seconds = target_duration_minutes * 60
                print(f"📏 User requested {target_duration_minutes} min target duration", flush=True)
            
            # Strategy: Use Gemini with structured data (CHEAP) as primary
            # Video Chat already used for structured extraction - no need to use it again for narration
            narrations = []

            # If a script was uploaded via /upload, it lives in storage as "{job_id}/script.txt".
            # Use it *as-is* (split into chapter-sized chunks) instead of rewriting with Gemini.
            used_user_script = False
            try:
                import hashlib as _hashlib
                script_object_name = f"{job_id}/script.txt"
                script_text = None
                try:
                    # Prefer the job flag if present, but also auto-detect by storage existence
                    if bool(job_data.get("has_script", False)) or self.storage.script_exists(script_object_name):
                        script_text = self.storage.download_script(script_object_name)
                except Exception:
                    # Best-effort: don't fail the job if storage check fails
                    script_text = None

                if script_text and str(script_text).strip():
                    used_user_script = True
                    narrations = self._split_user_script_into_chapters(str(script_text), chapters)
            except Exception:
                used_user_script = False
            
            # PRIMARY: Gemini with structured data (if we have structured data)
            if (not used_user_script) and structured_data and (structured_data.get("characters") or structured_data.get("scenes")):
                print(f"🎬 Using Gemini with structured data (cost-efficient)...", flush=True)
                print(f"   📋 Structured data: {len(structured_data.get('characters', []))} chars, {len(structured_data.get('scenes', []))} scenes", flush=True)
                
                try:
                    # If user requested a target duration, we should actively try to hit it by
                    # increasing narration length (otherwise target is only a cap, not a goal).
                    # We distribute the requested total across chapters (reserve ~30s for intro/outro).
                    target_words_per_chapter = None
                    if target_seconds and target_seconds > 0 and len(chapters) > 0:
                        available = max(float(target_seconds) - 30.0, 60.0)
                        seconds_per_chapter = available / float(len(chapters))
                        # Rough speech rate: ~2.2 words/sec (adjustable). This is only used as a *target* for Gemini.
                        target_words_per_chapter = max(120, int(seconds_per_chapter * 2.2))

                    # If target_words_per_chapter is None, ScriptGenerator will calculate from clip duration
                    # which is good for \"no speedup\" mode but will not expand to a longer requested recap.
                    # Use small batch_size=3 so Gemini focuses on fewer sections with more words each
                    narrations = await self.script_generator.rewrite_chapters_with_structured_data(
                        chapters=chapters,
                        structured_data=structured_data,
                        audio_transcript=audio_transcript,
                        target_words_per_chapter=target_words_per_chapter,
                        batch_size=3  # Smaller batches = more words per section
                    )
                    
                    # Check quality - look for meta-language as a sign of poor quality
                    good_narrations = 0
                    for n in narrations:
                        if n and len(n.split()) > 10:
                            # Check if it's NOT raw summary (has meta-language)
                            lower_n = n.lower()
                            has_meta = any(phrase in lower_n for phrase in [
                                'the video', 'the film', 'the scene', 'the camera',
                                'we see', 'on screen', 'is shown', 'is displayed'
                            ])
                            if not has_meta:
                                good_narrations += 1
                    
                    print(f"   📊 Quality check: {good_narrations}/{len(narrations)} narrations without meta-language", flush=True)
                    
                    if good_narrations < len(chapters) * 0.3:  # Lowered threshold
                        print(f"⚠️ Gemini produced too many raw summaries ({good_narrations}/{len(chapters)} clean), trying fallback...", flush=True)
                        # Don't clear - let post-processing clean it up
                        # narrations = []
                    else:
                        print(f"✅ Gemini narration complete: {good_narrations}/{len(chapters)} clean chapters", flush=True)
                        
                except Exception as gemini_error:
                    print(f"⚠️ Gemini with structured data failed: {gemini_error}", flush=True)
                    tb.print_exc()
                    narrations = []
            else:
                print(f"⚠️ No structured data available - skipping Gemini structured mode", flush=True)
                if structured_data:
                    print(f"   Data has: characters={len(structured_data.get('characters', []))}, scenes={len(structured_data.get('scenes', []))}", flush=True)
            
            # FALLBACK 1: Gemini without structured data (parallel mode)
            if (not used_user_script) and (not narrations or len(narrations) < len(chapters) * 0.5):
                print(f"🔄 Falling back to Gemini parallel mode...", flush=True)
                
                self.job_manager.update_job(
                    job_id,
                    current_step="Writing narration with Gemini..."
                )
                
                try:
                    # If user requested a target duration, distribute it across chapters.
                    # Otherwise use actual chapter timestamps.
                    narrations = await self.script_generator.rewrite_chapters_parallel(
                        chapters=chapters,
                        character_guide=character_guide,
                        plot_summary=plot_summary,
                        audio_transcript=audio_transcript,
                        target_duration_seconds=target_seconds,
                        batch_size=5,
                        key_moments=key_moments
                    )
                except Exception as fallback_error:
                    print(f"⚠️ Gemini fallback also failed: {fallback_error}", flush=True)
                    # Last resort: use raw summaries
                    narrations = [ch.get("description", "") or ch.get("summary", "") for ch in chapters]
            
            # ==== POST-PROCESS: Clean up ALL narrations (remove meta-language) ====
            if not used_user_script:
                print(f"🧹 Post-processing {len(narrations)} narrations to remove meta-language...", flush=True)
                narrations = self._clean_narrations(narrations)
            else:
                print(f"🧾 Using user script as-is (skipping narration cleanup)", flush=True)
            
            print(f"✍️ Rewrote {len(narrations)} chapters to dramatic narration", flush=True)

            # If user requested a long recap, we must actively generate enough narration to reach it.
            # The system previously treated target as a cap only, which can yield short recaps.
            if (not used_user_script) and target_seconds and target_seconds > 0 and narrations:
                # Predict narration duration from word counts (rough), so we can retry BEFORE TTS.
                # Observed speech rate in this system is ~2.5 words/sec on average.
                wps_est = 2.5
                words_total = sum(len((n or "").split()) for n in narrations)
                predicted_chapters_s = words_total / wps_est if wps_est > 0 else 0.0
                predicted_total_s = predicted_chapters_s + 25.0  # rough intro+outro reserve
                min_acceptable_pred = float(target_seconds) * 0.8

                # If prediction is far below target, retry once with a higher word target.
                if predicted_total_s < min_acceptable_pred and structured_data and (structured_data.get("characters") or structured_data.get("scenes")):
                    scale = (min_acceptable_pred / max(predicted_total_s, 1.0)) * 1.15  # +15% buffer
                    # Recompute per-chapter target words with a higher wps to compensate fast TTS.
                    secs_per_ch = max((float(target_seconds) - 30.0) / float(len(chapters)), 10.0)
                    base_words = int(secs_per_ch * 2.8)  # faster speech -> need more words
                    boosted_words = int(min(420, max(160, base_words * scale)))

                    print(f"⚠️ Narration too short ({predicted_total_s:.0f}s < {min_acceptable_pred:.0f}s), retrying with {boosted_words} words/chapter...", flush=True)

                    narrations = await self.script_generator.rewrite_chapters_with_structured_data(
                        chapters=chapters,
                        structured_data=structured_data,
                        audio_transcript=audio_transcript,
                        target_words_per_chapter=boosted_words,
                        batch_size=3,
                    )
                    narrations = self._clean_narrations(narrations)
            
            # ==== Step 4.5: Generate Intro & Outro ====
            self.job_manager.update_job(
                job_id,
                progress=48,
                current_step="Generating intro and outro..."
            )
            
            # Generate AI intro based on plot summary
            intro_text = await self.script_generator.generate_intro(
                plot_summary=plot_summary,
                character_guide=character_guide,
                video_title=job_data.get("filename", "").replace(".mp4", "").replace("_", " ")
            )
            
            # Generate template outro
            outro_text = self.script_generator.generate_outro(
                video_title=job_data.get("filename", "").replace(".mp4", "").replace("_", " "),
                include_cta=True
            )
            
            print(f"🎬 Intro: {intro_text[:60]}...", flush=True)
            print(f"🎬 Outro: {outro_text[:60]}...", flush=True)
            
            # Save combined script for debugging
            script_path = os.path.join(work_dir, "script.txt")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(f"=== INTRO ===\n{intro_text}\n\n")
                for i, (ch, narr) in enumerate(zip(chapters, narrations)):
                    f.write(f"=== Chapter {i+1}: {ch.get('title', 'Untitled')} ===\n")
                    f.write(f"Time: {ch.get('start', '?')} - {ch.get('end', '?')}\n")
                    f.write(f"Original: {ch.get('description', '') or ch.get('summary', '')}\n")
                    f.write(f"Narration: {narr}\n\n")
                f.write(f"=== OUTRO ===\n{outro_text}\n\n")
            
            # ==== Step 5: Generate TTS Audio (The Voice) - PARALLEL with TURBO ====
            self.job_manager.update_job(
                job_id,
                status=JobStatus.GENERATING_AUDIO,
                progress=50,
                current_step="Generating voiceover audio (parallel turbo mode)..."
            )
            
            # Parse narrations for ORIGINAL_AUDIO markers
            # Chapters with markers need special handling
            parsed_narrations = []
            chapters_with_markers = []
            
            for i, narration in enumerate(narrations):
                narration_text, marker_info = parse_original_audio_marker(narration)
                parsed_narrations.append(narration_text)
                if marker_info:
                    chapters_with_markers.append((i, marker_info))
                    print(f"🎬 Chapter {i+1} has original audio marker: {marker_info['start']:.1f}s-{marker_info['end']:.1f}s [{marker_info['speaker']}]", flush=True)
            
            if chapters_with_markers:
                print(f"🎬 {len(chapters_with_markers)} chapters will include original audio clips", flush=True)
            
            # Prepare items for parallel TTS generation
            # Include intro, all chapters (narration only, without markers), and outro
            tts_items = []
            
            # Intro
            intro_audio_path = os.path.join(audio_dir, "000_intro.mp3")
            tts_items.append((intro_text, intro_audio_path))
            
            # Chapters (use parsed narration without markers)
            for i, narration_text in enumerate(parsed_narrations):
                audio_path = os.path.join(audio_dir, f"chapter_{i+1:03d}_tts.mp3")
                tts_items.append((narration_text, audio_path))
            
            # Outro
            outro_audio_path = os.path.join(audio_dir, "999_outro.mp3")
            tts_items.append((outro_text, outro_audio_path))
            
            # Use parallel processing with turbo model for speed!
            print(f"⚡ Starting PARALLEL TTS generation for {len(tts_items)} items (intro + {len(narrations)} chapters + outro)...", flush=True)
            
            tts_results = await self.elevenlabs.generate_speeches_parallel(
                items=tts_items,
                batch_size=5,  # 5 concurrent TTS calls
                use_turbo=True,  # Use fastest model
                use_timestamps=True  # Prefer alignment-derived durations to avoid drift
            )
            
            # Extract intro and outro results
            intro_result = tts_results[0]  # (path, duration)
            chapter_tts_results = tts_results[1:-1]  # All chapters (TTS only)
            outro_result = tts_results[-1]  # (path, duration)
            
            print(f"🎬 Intro audio: {intro_result[1]:.1f}s", flush=True)
            print(f"🎬 Outro audio: {outro_result[1]:.1f}s", flush=True)
            
            # ==== Step 5.5: Process Original Audio Clips ====
            # For chapters with ORIGINAL_AUDIO markers, extract and concatenate
            chapter_results = []  # Final (audio_path, duration) for each chapter
            
            for i, (tts_path, tts_duration) in enumerate(chapter_tts_results):
                # Check if this chapter has a marker
                marker_info = None
                for chapter_idx, m_info in chapters_with_markers:
                    if chapter_idx == i:
                        marker_info = m_info
                        break
                
                if marker_info:
                    # This chapter needs original audio concatenated
                    print(f"🎙️ Processing original audio for chapter {i+1}...", flush=True)
                    
                    try:
                        # Extract original audio clip
                        original_audio_path = os.path.join(audio_dir, f"chapter_{i+1:03d}_original.mp3")
                        self.video_editor.extract_audio_clip(
                            video_path=local_video,
                            start_time=marker_info["start"],
                            end_time=marker_info["end"],
                            output_path=original_audio_path
                        )
                        
                        # Concatenate TTS + Original audio
                        combined_audio_path = os.path.join(audio_dir, f"chapter_{i+1:03d}.mp3")
                        self.audio_segmenter.concatenate_audio_files(
                            audio_files=[tts_path, original_audio_path],
                            output_path=combined_audio_path
                        )
                        
                        # Get combined duration
                        combined_duration = self.video_editor.get_media_duration(combined_audio_path)
                        chapter_results.append((combined_audio_path, combined_duration))

                        print(f"✅ Chapter {i+1}: TTS ({tts_duration:.1f}s) + Original ({marker_info['end']-marker_info['start']:.1f}s) = {combined_duration:.1f}s", flush=True)
                        
                    except Exception as e:
                        print(f"⚠️ Failed to process original audio for chapter {i+1}: {e}", flush=True)
                        # Fall back to TTS only
                        chapter_results.append((tts_path, tts_duration))
                else:
                    # No marker, just rename TTS file
                    final_path = os.path.join(audio_dir, f"chapter_{i+1:03d}.mp3")
                    if tts_path != final_path:
                        import shutil
                        shutil.copy2(tts_path, final_path)
                    chapter_results.append((final_path, tts_duration))

            # ==== Step 5.6: OPTIONAL Scene Matching (AI-powered clip selection) ====
            # This is an optional enhancement that can improve clip-to-narration matching
            # Can be enabled per-job via the upload form, or globally via ENABLE_SCENE_MATCHER=true in .env
            matched_timestamps = None  # Will store matched clip timestamps if enabled
            
            # SceneMatcher is only useful when user provides their own script
            # When AI generates narration from chapters, the narration already matches chapter timestamps
            scene_matcher_requested = enable_scene_matcher or self.settings.features.enable_scene_matcher
            use_scene_matcher = scene_matcher_requested and used_user_script

            if scene_matcher_requested and not used_user_script:
                print(f"ℹ️ SceneMatcher skipped: AI-generated narration already matches chapter timestamps", flush=True)
            
            if use_scene_matcher and video_no:
                try:
                    print(f"\n{'='*60}", flush=True)
                    print(f"🎯 SceneMatcher: Matching narrations to best clips...", flush=True)
                    print(f"{'='*60}", flush=True)
                    
                    self.job_manager.update_job(
                        job_id,
                        progress=55,
                        current_step="Matching narration to optimal clips (SceneMatcher)..."
                    )
                    
                    # Import here to avoid errors if SceneMatcher doesn't exist
                    from app.services.scene_matcher import SceneMatcher
                    
                    scene_matcher = SceneMatcher()
                    matched_scenes_result = await scene_matcher.match_narration_to_clips(
                        narrations=narrations,
                        video_no=video_no,
                        chapters=chapters,
                        unique_id=job_id,
                        story_context=plot_summary or ""
                    )
                    
                    # Extract matched timestamps as a dict for easy lookup
                    matched_timestamps = {
                        i: {
                            "start": m.clip_start, 
                            "end": m.clip_end, 
                            "confidence": m.confidence,
                            "source": m.source
                        }
                        for i, m in enumerate(matched_scenes_result)
                    }
                    
                    # Log match quality
                    high_conf = sum(
                        1 for m in matched_scenes_result 
                        if m.confidence >= self.settings.features.scene_matcher_confidence_threshold
                    )
                    print(f"✅ SceneMatcher: {high_conf}/{len(matched_scenes_result)} high-confidence matches", flush=True)
                    print(f"{'='*60}\n", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ SceneMatcher failed (using original timestamps): {e}", flush=True)
                    tb.print_exc()
                    matched_timestamps = None  # Will fall back to original
            
            # Build final scenes from results
            final_scenes: List[ChapterScene] = []
            
            # Add intro as first scene (use first few seconds of video as background)
            intro_audio_path, intro_duration = intro_result
            if intro_duration > 0:
                final_scenes.append(ChapterScene(
                    id=0,
                    title="Intro",
                    narration=intro_text,
                    audio_path=intro_audio_path,
                    audio_duration=intro_duration,
                    video_start=0.0,  # Start of video
                    video_end=min(intro_duration * 1.5, 15.0)  # Use first ~15 seconds max
                ))
            
            # Add chapter scenes
            for i, ((audio_path, audio_duration), chapter, narration) in enumerate(zip(chapter_results, chapters, narrations)):
                # Use matched timestamps if available and confidence is good
                # Otherwise fall back to original chapter timestamps (CURRENT BEHAVIOR)
                if matched_timestamps and i in matched_timestamps:
                    match = matched_timestamps[i]
                    # Only use matched timestamp if confidence is above threshold
                    confidence_threshold = self.settings.features.scene_matcher_confidence_threshold
                    # Extra guardrail: full-video search is more error-prone; require a higher bar.
                    # (Observed: full_video matches can barely clear threshold and be wrong.)
                    source_type = match.get("source")
                    effective_threshold = confidence_threshold + 0.10 if source_type == "full_video" else confidence_threshold
                    
                    # Calculate how far the matched clip is from original timestamps
                    original_start = parse_time(chapter.get("start", 0))
                    original_end = parse_time(chapter.get("end", original_start + 10))
                    original_duration = original_end - original_start
                    delta_start = abs(match["start"] - original_start)
                    
                    # CRITICAL: Reject matches that are too far from original timestamp
                    # Even high-confidence matches can be wrong if they're from a completely different part of the video
                    # Allow up to 2x the chapter duration as maximum drift
                    max_allowed_delta = max(original_duration * 2, 120.0)  # At least 2 minutes drift allowed

                    if match["confidence"] >= effective_threshold and delta_start <= max_allowed_delta:
                        video_start = match["start"]
                        video_end = match["end"]
                        match_indicator = f" 🎯 [{match['source']}:{match['confidence']:.2f}]"
                    elif delta_start > max_allowed_delta:
                        # Match is too far from expected position - use original timestamps
                        video_start = original_start
                        video_end = original_end
                        match_indicator = f" ⚠️ too-far (delta={delta_start:.0f}s)"
                    else:
                        # Low confidence - use original timestamps
                        video_start = original_start
                        video_end = original_end
                        match_indicator = " ⚠️ low-conf"
                else:
                    # No matching available - use original chapter timestamps
                    video_start = parse_time(chapter.get("start", 0))
                    video_end = parse_time(chapter.get("end", video_start + 10))
                    match_indicator = ""
                
                # Check if this chapter had original audio
                has_original = any(idx == i for idx, _ in chapters_with_markers)
                marker_str = " 🎙️" if has_original else ""
                
                print(f"  [{i+1}] '{chapter.get('title', '')[:30]}...'{marker_str}{match_indicator} -> Video: {video_start:.1f}s-{video_end:.1f}s, Audio: {audio_duration:.1f}s", flush=True)

                final_scenes.append(ChapterScene(
                    id=i + 1,
                    title=chapter.get("title", f"Chapter {i+1}"),
                    narration=narration,
                    audio_path=audio_path,
                    audio_duration=audio_duration,
                    video_start=video_start,
                    video_end=video_end
                ))
            
            # Add outro as last scene (use last few seconds of video as background)
            outro_audio_path, outro_duration = outro_result
            if outro_duration > 0:
                final_scenes.append(ChapterScene(
                    id=999,
                    title="Outro",
                    narration=outro_text,
                    audio_path=outro_audio_path,
                    audio_duration=outro_duration,
                    video_start=max(0, video_duration - outro_duration * 1.5),  # End of video
                    video_end=video_duration
                ))
            
            total_audio = sum(s.audio_duration for s in final_scenes)
            print(f"🎙️ Generated {len(final_scenes)} audio segments (intro + {len(chapters)} chapters + outro = {total_audio:.1f}s total)", flush=True)
            print(f"🎙️ Generated {len(final_scenes)} audio segments ({total_audio:.1f}s total)", flush=True)
            
            # ==== Step 5.5: Select Chapters to Fit Target Duration (if specified) ====
            if target_duration_minutes:
                target_seconds = target_duration_minutes * 60
                min_acceptable = target_seconds * 0.8  # Allow 20% under target
                max_acceptable = target_seconds * 1.1  # Allow 10% over target
                
                if total_audio > max_acceptable:
                    print(f"📏 Total audio ({total_audio:.1f}s) exceeds target ({target_seconds:.1f}s + 10% = {max_acceptable:.1f}s)", flush=True)
                    print(f"📏 Selecting chapters to fit target duration...", flush=True)
                    
                    # Select chapters until we're within acceptable range
                    selected_scenes = []
                    running_total = 0
                    
                    for scene in final_scenes:
                        if running_total + scene.audio_duration <= max_acceptable:
                            selected_scenes.append(scene)
                            running_total += scene.audio_duration
                        else:
                            break
                    
                    if selected_scenes:
                        final_scenes = selected_scenes
                        new_total = sum(s.audio_duration for s in final_scenes)
                        print(f"✅ Selected {len(final_scenes)}/{len(chapters)} chapters ({new_total:.1f}s, target: {target_seconds:.1f}s)", flush=True)
                    else:
                        print(f"⚠️ Could not fit any chapters within target. Using first chapter only.", flush=True)
                        final_scenes = final_scenes[:1]
                elif total_audio < min_acceptable:
                    shortfall_pct = ((target_seconds - total_audio) / target_seconds) * 100
                    print(f"⚠️ WARNING: Total audio ({total_audio:.1f}s) is {shortfall_pct:.0f}% SHORT of target ({target_seconds:.1f}s)!", flush=True)
                    print(f"⚠️ This may be due to Gemini API quota limits or short chapter summaries.", flush=True)
                    print(f"⚠️ The final video will be shorter than requested.", flush=True)
                else:
                    print(f"✅ Total audio ({total_audio:.1f}s) is within target range ({min_acceptable:.1f}s - {max_acceptable:.1f}s)", flush=True)
            
            # ==== Step 6: Elastic Stitch (with optional copyright protection) ====
            self.job_manager.update_job(
                job_id,
                status=JobStatus.STITCHING,
                progress=70,
                current_step="Stitching video with elastic sync..."
            )
            
            # Check if copyright protection is enabled
            enable_copyright_protection = job_data.get("enable_copyright_protection", self.settings.features.enable_copyright_protection)
            
            if enable_copyright_protection:
                print(f"\n{'='*60}", flush=True)
                print(f"🔒 COPYRIGHT PROTECTION ENABLED", flush=True)
                print(f"{'='*60}", flush=True)
                
                try:
                    # Initialize copyright protector
                    transform_intensity = getattr(self.settings, 'transform_intensity', 'subtle')
                    copyright_protector = CopyrightProtector(intensity=transform_intensity)
                    
                    # Process each scene for copyright protection
                    protected_scenes: List[ProtectedScene] = []
                    
                    for scene in final_scenes:
                        try:
                            # Use async version with alternates if video_no available
                            if video_no:
                                protected_scene = await copyright_protector.process_scene_with_alternates(
                                    video_start=scene.video_start,
                                    video_end=scene.video_end,
                                    audio_path=scene.audio_path,
                                    audio_duration=scene.audio_duration,
                                    video_no=video_no,
                                    unique_id=job_id,
                                    narration=scene.narration,
                                    scene_id=scene.id
                                )
                            else:
                                # Fallback to sync version without alternates
                                protected_scene = copyright_protector.process_scene(
                                    video_start=scene.video_start,
                                    video_end=scene.video_end,
                                    audio_path=scene.audio_path,
                                    audio_duration=scene.audio_duration,
                                    scene_id=scene.id
                                )
                            
                            protected_scenes.append(protected_scene)
                            
                        except Exception as scene_err:
                            print(f"⚠️ Failed to protect scene {scene.id}: {scene_err}", flush=True)
                            # Fall back to unprotected scene
                            fallback_scene = copyright_protector.process_scene(
                                video_start=scene.video_start,
                                video_end=scene.video_end,
                                audio_path=scene.audio_path,
                                audio_duration=scene.audio_duration,
                                scene_id=scene.id
                            )
                            protected_scenes.append(fallback_scene)
                    
                    # Stitch protected scenes
                    raw_output_path = os.path.join(work_dir, "raw_recap.mp4")
                    await asyncio.to_thread(
                        self.video_editor.elastic_stitch_protected_scenes,
                        local_video,
                        protected_scenes,
                        raw_output_path
                    )
                    
                    # Apply final post-processing transforms
                    import random
                    output_path = os.path.join(work_dir, "final_recap.mp4")
                    await asyncio.to_thread(
                        self.video_editor.apply_post_transforms,
                        raw_output_path,
                        output_path,
                        brightness=random.uniform(0.97, 1.03),
                        saturation=random.uniform(0.97, 1.03),
                        contrast=random.uniform(0.98, 1.02),
                        hue_shift=random.uniform(-2, 2)
                    )
                    
                    # Cleanup raw output
                    try:
                        os.remove(raw_output_path)
                    except:
                        pass
                    
                    print(f"✅ Copyright protection complete", flush=True)
                    print(f"{'='*60}\n", flush=True)
                    
                except Exception as cp_err:
                    print(f"⚠️ Copyright protection failed, falling back to standard stitch: {cp_err}", flush=True)
                    tb.print_exc()
                    
                    # Fall back to standard stitching
                    scenes_for_editor = [
                        {
                            "id": s.id,
                            "audio_path": s.audio_path,
                            "video_start": s.video_start,
                            "video_end": s.video_end,
                            "target_duration": s.audio_duration,
                            "text": s.narration
                        }
                        for s in final_scenes
                    ]
                    
                    output_path = os.path.join(work_dir, "final_recap.mp4")
                    await self.video_editor.stitch_elastic(
                        source_video=local_video,
                        scenes=scenes_for_editor,
                        output_path=output_path
                    )
            else:
                # Standard stitching (no copyright protection)
                # Convert ChapterScene to dict format expected by video_editor
                scenes_for_editor = [
                    {
                        "id": s.id,
                        "audio_path": s.audio_path,
                        "video_start": s.video_start,
                        "video_end": s.video_end,
                        "target_duration": s.audio_duration,
                        "text": s.narration
                    }
                    for s in final_scenes
                ]
                
                output_path = os.path.join(work_dir, "final_recap.mp4")
                await self.video_editor.stitch_elastic(
                    source_video=local_video,
                    scenes=scenes_for_editor,
                    output_path=output_path
                )
            
            # ==== Step 7: Upload Output ====
            self.job_manager.update_job(
                job_id,
                progress=90,
                current_step="Uploading final video..."
            )
            
            output_object_name = f"{job_id}/final_recap.mp4"

            self.storage.upload_output(output_object_name, output_path)
            output_url = self.storage.get_output_url(output_object_name)

            # Upload script for reference
            script_object_name = f"{job_id}/script.txt"
            self.storage.upload_output(script_object_name, script_path)
            
            # Cleanup Memories.ai video
            if video_no:
                try:
                    await self.memories_client.delete_video(video_no, unique_id=job_id)
                except Exception as cleanup_err:
                    print(f"⚠️ Failed to cleanup Memories.ai video: {cleanup_err}", flush=True)
            
            # Build scene data for response
            scene_dicts = [
                {
                    "index": s.id,
                    "title": s.title,
                    "start_time": s.video_start,
                    "end_time": s.video_end,
                    "duration": s.audio_duration,
                    "narration_text": s.narration[:200] + "..." if len(s.narration) > 200 else s.narration,
                    "processed": True
                }
                for s in final_scenes
            ]
            
            # Mark complete
            self.job_manager.complete_job_if_not_failed(
                job_id=job_id,
                progress=100,
                current_step="Complete!",
                processed_scenes=len(final_scenes),
                output_url=output_url,
                scenes=scene_dicts,
            )
            
            print(f"✅ Job {job_id} completed successfully (Chapter-Based)", flush=True)
            
        except FFmpegError as e:
            # Surface sanitized error to job; keep full stderr in logs.
            error_msg = str(e)
            print(f"❌ Job {job_id} failed (FFmpeg): {error_msg}", flush=True)
            if getattr(e, "stderr", None):
                print(f"--- FFmpeg stderr (full) ---\n{e.stderr}\n--- end ffmpeg stderr ---", flush=True)
            tb.print_exc()
            
            self.job_manager.fail_job_if_not_completed(
                job_id=job_id,
                error_message=error_msg,
                current_step="Failed",
            )
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Job {job_id} failed: {error_msg}", flush=True)
            tb.print_exc()
            
            self.job_manager.fail_job_if_not_completed(
                job_id=job_id,
                error_message=error_msg,
                current_step="Failed",
            )
            
            # Try to cleanup Memories.ai video on error
            if video_no:
                try:
                    await self.memories_client.delete_video(video_no, unique_id=job_id)
                except:
                    pass
        
        finally:
            # Cleanup working directory
            import shutil
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)


def main():
    """Entry point for the worker."""
    worker = PipelineWorker()
    worker.run()


if __name__ == "__main__":
    main()
