from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from app.config import get_settings
from app.services.ffmpeg_utils import run_ffmpeg_capture, run_ffprobe_capture, FFmpegError, sanitize_ffmpeg_stderr


@dataclass
class SceneSpec:
    """Internal normalized scene spec for stitching."""

    id: int
    video_start: float
    video_end: float
    audio_path: str
    target_duration: float


class VideoEditorService:
    """
    FFmpeg-based video editor used by the pipeline worker.

    NOTE: This file was empty (0 bytes), which caused the worker to crash on import.
    The implementations here are intentionally pragmatic:
    - Stitch scenes by extracting source video ranges
    - Time-stretch each scene's video to match its narration duration (setpts)
    - Concatenate videos + audios and mux into the final mp4
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _require_file(self, path: str, *, label: str) -> None:
        """
        Guardrail: ensure an expected output file exists and is non-empty.
        If not, raise FFmpegError with a clear message (this prevents confusing concat errors).
        """
        try:
            if not os.path.exists(path):
                raise FFmpegError(message=f"FFmpeg produced no {label} file: {path}")
            if os.path.getsize(path) <= 0:
                raise FFmpegError(message=f"FFmpeg produced empty {label} file: {path}")
        except FFmpegError:
            raise
        except Exception as e:
            raise FFmpegError(message=f"Failed to validate {label} file '{path}': {e}")
    
    def get_media_duration(self, path: str) -> float:
        """
        Return media duration in seconds using ffprobe.
        """
        if not path:
            return 0.0
    
        proc = run_ffprobe_capture(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            timeout=60,
        )
        out = (proc.stdout or "").strip()
        try:
            return float(out)
        except Exception:
            return 0.0

    def extract_audio_clip(self, *, video_path: str, start_time: float, end_time: float, output_path: str) -> None:
        """
        Extract an audio segment from the source video and write to output_path.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        dur = max(0.0, float(end_time) - float(start_time))
        if dur <= 0:
            raise ValueError("Invalid audio clip duration")

        # Re-encode to mp3 for broad compatibility.
        run_ffmpeg_capture(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(start_time),
                "-t",
                str(dur),
                "-i",
                video_path,
                "-vn",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                output_path,
            ],
            check=True,
            timeout=600,
        )

    def _normalize_scenes(self, scenes: Sequence[dict]) -> List[SceneSpec]:
        out: List[SceneSpec] = []
        for s in scenes:
            out.append(
                SceneSpec(
                    id=int(s.get("id", 0)),
                    video_start=float(s.get("video_start", 0.0)),
                    video_end=float(s.get("video_end", 0.0)),
                    audio_path=str(s.get("audio_path", "")),
                    target_duration=float(s.get("target_duration", 0.0)),
                )
            )
        return out

    def _write_concat_file(self, paths: Iterable[str]) -> str:
        fd, list_path = tempfile.mkstemp(prefix="concat_", suffix=".txt")
        os.close(fd)
        with open(list_path, "w", encoding="utf-8") as f:
            for p in paths:
                # concat demuxer expects `file '...path...'`
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        return list_path

    def _stretch_video_to_duration(self, *, input_path: str, output_path: str, target_duration: float) -> None:
        src_dur = self.get_media_duration(input_path)
        if src_dur <= 0 or target_duration <= 0:
            raise ValueError("Invalid durations for time-stretch")

        # setpts factor: >1 slows down, <1 speeds up. Factor = target/src.
        factor = max(0.1, min(10.0, target_duration / src_dur))
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        run_ffmpeg_capture(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                input_path,
                "-an",
                "-vf",
                f"setpts={factor}*PTS",
                "-c:v",
                self.settings.ffmpeg.video_codec,
                "-b:v",
                self.settings.ffmpeg.video_bitrate,
                "-pix_fmt",
                "yuv420p",
                output_path,
            ],
            check=True,
            timeout=1200,
        )
        self._require_file(output_path, label="stretched segment")

    def _concat_videos(self, *, video_paths: Sequence[str], output_path: str) -> None:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        list_path = self._write_concat_file(video_paths)
        try:
            # Re-encode to avoid codec/stream mismatch issues.
            run_ffmpeg_capture(
                [
            "ffmpeg",
            "-y",
                    "-v",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_path,
                    "-an",
                    "-c:v",
                    self.settings.ffmpeg.video_codec,
                    "-b:v",
                    self.settings.ffmpeg.video_bitrate,
                    "-pix_fmt",
                    "yuv420p",
                    output_path,
                ],
                check=True,
                timeout=1800,
            )
        finally:
            try:
                os.remove(list_path)
            except Exception:
                pass

    def _concat_audios_to_m4a(self, *, audio_paths: Sequence[str], output_path: str) -> None:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        list_path = self._write_concat_file(audio_paths)
        try:
            # Re-encode into AAC for stable muxing.
            run_ffmpeg_capture(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_path,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    output_path,
                ],
                check=True,
                timeout=1200,
            )
        finally:
            try:
                os.remove(list_path)
            except Exception:
                pass

    async def stitch_elastic(self, *, source_video: str, scenes: Sequence[dict], output_path: str) -> None:
        """
        Stitch a recap by elastic time-stretching each scene's video to match narration audio.
        """
        work_dir = os.path.join(os.path.dirname(output_path) or ".", "_work_stitch")
        os.makedirs(work_dir, exist_ok=True)

        normalized = self._normalize_scenes(scenes)
        if not normalized:
            raise ValueError("No scenes to stitch")

        stretched_videos: List[str] = []
        audios: List[str] = []

        for scene in normalized:
            seg_dur = max(0.0, scene.video_end - scene.video_start)
            if seg_dur <= 0:
                raise ValueError(f"Invalid scene {scene.id} video range")
            if scene.target_duration <= 0:
                raise ValueError(f"Invalid scene {scene.id} target_duration")

            # 1) Extract raw video segment (no audio)
            raw_seg = os.path.join(work_dir, f"scene_{scene.id:04d}_raw.mp4")
            run_ffmpeg_capture(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    str(scene.video_start),
                    "-t",
                    str(seg_dur),
                    "-i",
                    source_video,
                    "-an",
                    "-c:v",
                    self.settings.ffmpeg.video_codec,
                    "-b:v",
                    self.settings.ffmpeg.video_bitrate,
                    "-pix_fmt",
                    "yuv420p",
                    raw_seg,
                ],
                check=True,
                timeout=1200,
            )
            self._require_file(raw_seg, label="raw segment")

            # 2) Stretch raw segment to target duration
            stretched = os.path.join(work_dir, f"scene_{scene.id:04d}_stretched.mp4")
            self._stretch_video_to_duration(input_path=raw_seg, output_path=stretched, target_duration=scene.target_duration)
            stretched_videos.append(stretched)

            # 3) Add corresponding narration audio path
            audios.append(scene.audio_path)

        # 4) Concat all stretched videos
        concat_video = os.path.join(work_dir, "video_concat.mp4")
        self._concat_videos(video_paths=stretched_videos, output_path=concat_video)

        # 5) Concat all audio tracks
        concat_audio = os.path.join(work_dir, "audio_concat.m4a")
        self._concat_audios_to_m4a(audio_paths=audios, output_path=concat_audio)

        # 6) Mux together into output
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        run_ffmpeg_capture(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                concat_video,
                "-i",
                concat_audio,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                output_path,
            ],
            check=True,
            timeout=1800,
        )

    # ---- Copyright protection path (compat) ----

    def elastic_stitch_protected_scenes(self, source_video: str, protected_scenes: Sequence[object], output_path: str) -> None:
        """
        Back-compat entrypoint used by the pipeline when copyright protection is enabled.

        We treat ProtectedScene as a scene-like object with:
        - video_start/video_end
        - audio_path/audio_duration
        """
        scenes = []
        for idx, ps in enumerate(protected_scenes):
            scenes.append(
                {
                    "id": getattr(ps, "scene_id", idx + 1),
                    "video_start": getattr(ps, "video_start", 0.0),
                    "video_end": getattr(ps, "video_end", 0.0),
                    "audio_path": getattr(ps, "audio_path", ""),
                    "target_duration": getattr(ps, "audio_duration", 0.0),
                }
            )

        # Run the async stitcher synchronously (worker already calls this in a thread).
        import asyncio

        asyncio.run(self.stitch_elastic(source_video=source_video, scenes=scenes, output_path=output_path))
    
    def apply_post_transforms(
        self,
        input_path: str,
        output_path: str,
        *,
        brightness: float = 1.0,
        saturation: float = 1.0,
        contrast: float = 1.0,
        hue_shift: float = 0.0,
    ) -> None:
        """
        Apply mild post-processing transforms (brightness/saturation/contrast/hue) and re-encode.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        vf = f"eq=brightness={brightness-1.0}:saturation={saturation}:contrast={contrast},hue=h={hue_shift}"
        run_ffmpeg_capture(
            [
            "ffmpeg",
            "-y",
                "-v",
                "error",
                "-i",
                input_path,
                "-vf",
                vf,
                "-c:v",
                self.settings.ffmpeg.video_codec,
                "-b:v",
                self.settings.ffmpeg.video_bitrate,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                output_path,
            ],
            check=True,
            timeout=1800,
        )


