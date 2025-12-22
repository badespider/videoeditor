from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProtectedScene:
    """
    Minimal representation of a "copyright-protected" scene.

    The original upstream version of this file was empty (0 bytes), which breaks the worker.
    For now, we implement a safe, minimal, backwards-compatible shape so the pipeline can run.

    NOTE: This currently performs *no* per-subclip visual transformations. It preserves the
    interface and allows the worker to stitch scenes; we can iterate on real protection later.
    """

    scene_id: int
    video_start: float
    video_end: float
    audio_path: str
    audio_duration: float


class CopyrightProtector:
    """
    Compatibility layer used by the pipeline.

    In the pipeline, when copyright protection is enabled, it calls:
      - process_scene(...) -> ProtectedScene
    and later VideoEditorService.elastic_stitch_protected_scenes(...) stitches them.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def process_scene(
        self,
        *,
        video_start: float,
        video_end: float,
        audio_path: str,
        audio_duration: float,
        scene_id: int,
        alternates: Optional[object] = None,
    ) -> ProtectedScene:
        # alternates ignored in minimal implementation
        return ProtectedScene(
            scene_id=int(scene_id),
            video_start=float(video_start),
            video_end=float(video_end),
            audio_path=str(audio_path),
            audio_duration=float(audio_duration),
        )

    async def process_scene_with_alternates(
        self,
        *,
        video_start: float,
        video_end: float,
        audio_path: str,
        audio_duration: float,
        scene_id: int,
        alternates: Optional[object] = None,
    ) -> ProtectedScene:
        """
        Backwards-compatible async API expected by the pipeline.

        The current implementation does not apply any visual transformations; it simply
        returns a ProtectedScene describing the intended stitch range.
        """
        return self.process_scene(
            video_start=video_start,
            video_end=video_end,
            audio_path=audio_path,
            audio_duration=audio_duration,
            scene_id=scene_id,
            alternates=alternates,
        )


