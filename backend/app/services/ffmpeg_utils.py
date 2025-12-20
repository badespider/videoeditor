import re
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence
import os


@dataclass
class FFmpegError(Exception):
    """
    Typed ffmpeg failure.
    - message: sanitized/shortened text safe for job.error_message
    - stderr: full stderr for server logs/debugging
    - cmd: the command executed
    """
    message: str
    stderr: str = ""
    cmd: Optional[list[str]] = None

    def __str__(self) -> str:
        return self.message


def sanitize_ffmpeg_stderr(stderr: str, max_lines: int = 25, max_chars: int = 4000) -> str:
    """
    Keep the error understandable but short:
    - take the last N lines (ffmpeg usually prints the real reason near the end)
    - trim overly long lines and total size
    - remove common noisy prefixes
    """
    if not stderr:
        return "FFmpeg failed (no stderr)"

    # Normalize newlines
    s = stderr.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in s.split("\n") if ln.strip()]

    # ffmpeg often repeats banner/info; last lines are typically most useful
    tail = lines[-max_lines:] if len(lines) > max_lines else lines

    cleaned: list[str] = []
    for ln in tail:
        # Strip common noise (ffmpeg banners often appear right before the real error)
        ln = ln.strip()
        if not ln:
            continue
        if re.match(r"^ffmpeg version\b", ln, re.IGNORECASE):
            continue
        if re.match(r"^built with\b", ln, re.IGNORECASE):
            continue
        if re.match(r"^configuration:", ln, re.IGNORECASE):
            continue
        if re.match(r"^(libav(util|codec|format|device|filter)|libswscale|libswresample|libpostproc)\b", ln, re.IGNORECASE):
            continue
        if re.match(r"^Input #\\d+", ln, re.IGNORECASE):
            continue
        if re.match(r"^Output #\\d+", ln, re.IGNORECASE):
            continue
        if re.match(r"^Stream mapping:", ln, re.IGNORECASE):
            continue
        if re.match(r"^Press \\[q\\] to stop", ln, re.IGNORECASE):
            continue
        # Avoid huge dumps
        if len(ln) > 500:
            ln = ln[:500] + "…"
        cleaned.append(ln)

    out = "\n".join(cleaned).strip()
    if not out:
        out = "FFmpeg failed (no useful stderr)"

    if len(out) > max_chars:
        out = out[-max_chars:]
    return out


def _inject_nostdin(cmd: Sequence[str]) -> list[str]:
    cmd_list = list(cmd)
    if not cmd_list:
        raise ValueError("Empty ffmpeg command")

    # Accept any of:
    # - ["ffmpeg", ...]
    # - ["ffmpeg.exe", ...]
    # - ["C:\\path\\to\\ffmpeg.exe", ...]
    # - ["-y", "-i", ...]  (args only; we will prepend ffmpeg)
    first = str(cmd_list[0])
    base = os.path.basename(first).lower()
    is_ffmpeg_bin = base in {"ffmpeg", "ffmpeg.exe"}
    if not is_ffmpeg_bin:
        # Treat as args-only; prepend the ffmpeg executable name.
        cmd_list.insert(0, "ffmpeg")

    # Insert -nostdin right after ffmpeg unless already present anywhere.
    if "-nostdin" not in cmd_list:
        cmd_list.insert(1, "-nostdin")
    return cmd_list


def run_ffmpeg_capture(
    cmd: Sequence[str],
    *,
    check: bool = True,
    timeout: Optional[float] = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run ffmpeg with robust defaults:
    - inject -nostdin to prevent background hangs
    - capture output for diagnostics
    - optionally raise FFmpegError with sanitized stderr
    """
    cmd_list = _inject_nostdin(cmd)

    try:
        proc = subprocess.run(
            cmd_list,
            capture_output=True,
            text=text,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        stderr = getattr(e, "stderr", "") or ""
        raise FFmpegError(
            message=f"FFmpeg timed out after {timeout}s",
            stderr=stderr,
            cmd=cmd_list,
        )

    if check and proc.returncode != 0:
        raise FFmpegError(
            message=f"FFmpeg failed:\n{sanitize_ffmpeg_stderr(proc.stderr)}",
            stderr=proc.stderr or "",
            cmd=cmd_list,
        )

    return proc


def run_ffmpeg(cmd: Sequence[str], *, timeout: Optional[float] = None) -> None:
    """Run ffmpeg and raise FFmpegError on failure."""
    run_ffmpeg_capture(cmd, check=True, timeout=timeout)


def run_ffprobe_capture(
    cmd: Sequence[str],
    *,
    check: bool = True,
    timeout: Optional[float] = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run ffprobe with robust defaults:
    - capture output for diagnostics
    - optionally raise FFmpegError with sanitized stderr
    """
    cmd_list = list(cmd)
    if not cmd_list:
        raise ValueError("Empty ffprobe command")

    try:
        proc = subprocess.run(
            cmd_list,
            capture_output=True,
            text=text,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        stderr = getattr(e, "stderr", "") or ""
        raise FFmpegError(
            message=f"FFprobe timed out after {timeout}s",
            stderr=stderr,
            cmd=cmd_list,
        )

    if check and proc.returncode != 0:
        raise FFmpegError(
            message=f"FFprobe failed:\n{sanitize_ffmpeg_stderr(proc.stderr)}",
            stderr=proc.stderr or "",
            cmd=cmd_list,
        )

    return proc


def run_ffprobe(cmd: Sequence[str], *, timeout: Optional[float] = None) -> None:
    """Run ffprobe and raise FFmpegError on failure."""
    run_ffprobe_capture(cmd, check=True, timeout=timeout)


