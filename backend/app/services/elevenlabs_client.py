import os
import json
import asyncio
import requests
import httpx
from typing import Optional, Iterator, List, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.services.ffmpeg_utils import run_ffmpeg_capture


@dataclass
class WordAlignment:
    """Word-level timing from TTS."""
    word: str
    start_time: float  # seconds
    end_time: float    # seconds


@dataclass
class TTSResult:
    """Result from TTS generation with optional timestamps."""
    audio_path: str
    # Preferred duration for synchronization (seconds). Prefer alignment-derived duration when present.
    duration: float
    # Duration from ffprobe on the produced audio (seconds). Useful for diagnostics.
    audio_duration_seconds: float
    # Duration from ElevenLabs alignment (last character end - first character start).
    # This is usually the best value for tight cuts / sync.
    alignment_duration_seconds: Optional[float] = None
    alignments: Optional[List[WordAlignment]] = None


class ElevenLabsClient:
    """
    Client for ElevenLabs Text-to-Speech API.
    
    Generates narration audio from scene descriptions.
    Uses direct HTTP requests for compatibility.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.elevenlabs.api_key
        self.base_url = "https://api.elevenlabs.io/v1"

    def _ensure_silent_mp3(self, output_path: str, duration_s: float = 0.25) -> float:
        """
        Ensure a valid (very short) silent mp3 exists at output_path.
        Used when narration text is empty or a TTS call fails, so downstream steps don't crash.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(duration_s),
                "-q:a", "9",
                "-acodec", "libmp3lame",
                output_path,
            ]
            # Best-effort: create a valid mp3 but don't fail if ffmpeg errors.
            run_ffmpeg_capture(cmd, check=False, timeout=30, text=True)
        except Exception:
            # As a last resort, at least create the file to prevent FileNotFoundError.
            try:
                with open(output_path, "wb") as f:
                    f.write(b"")
            except Exception:
                pass

        try:
            if os.path.exists(output_path):
                return self.get_audio_duration(output_path)
        except Exception:
            pass
        return 0.0

    async def generate_speech_with_timestamps_async(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        use_turbo: bool = True
    ) -> TTSResult:
        """
        Async version of generate_speech_with_timestamps().
        Uses ElevenLabs' /text-to-speech/{voice_id}/with-timestamps endpoint to get alignment.
        """
        import base64

        voice = voice_id or self.settings.elevenlabs.voice_id

        # Model selection: try turbo if requested; fall back upstream on failure.
        if use_turbo:
            model = "eleven_turbo_v2_5"
        else:
            model = model_id or self.settings.elevenlabs.model_id

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        url = f"{self.base_url}/text-to-speech/{voice}/with-timestamps"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }

        data = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()

        audio_base64 = result.get("audio_base64", "")
        audio_data = base64.b64decode(audio_base64)
        with open(output_path, "wb") as f:
            f.write(audio_data)

        alignment_data = result.get("alignment", {}) or {}
        characters = alignment_data.get("characters", [])
        char_start_times = alignment_data.get("character_start_times_seconds", [])
        char_end_times = alignment_data.get("character_end_times_seconds", [])

        # Alignment-derived duration
        alignment_duration_seconds: Optional[float] = None
        try:
            if char_start_times and char_end_times:
                alignment_duration_seconds = float(char_end_times[-1]) - float(char_start_times[0])
                if alignment_duration_seconds < 0:
                    alignment_duration_seconds = None
        except Exception:
            alignment_duration_seconds = None

        # Reconstruct word-level alignments from character alignment
        alignments: List[WordAlignment] = []
        if characters and char_start_times and char_end_times:
            current_word = ""
            word_start = None
            for i, char in enumerate(characters):
                if char == " " or i == len(characters) - 1:
                    if i == len(characters) - 1 and char != " ":
                        current_word += char
                    if current_word and word_start is not None:
                        word_end = char_end_times[i - 1] if char == " " else char_end_times[i]
                        alignments.append(WordAlignment(
                            word=current_word,
                            start_time=word_start,
                            end_time=word_end
                        ))
                    current_word = ""
                    word_start = None
                else:
                    if word_start is None:
                        word_start = char_start_times[i]
                    current_word += char

        audio_duration_seconds = self.get_audio_duration(output_path)
        preferred_duration_seconds = alignment_duration_seconds if alignment_duration_seconds is not None else audio_duration_seconds

        return TTSResult(
            audio_path=output_path,
            duration=preferred_duration_seconds,
            audio_duration_seconds=audio_duration_seconds,
            alignment_duration_seconds=alignment_duration_seconds,
            alignments=alignments
        )
    
    def generate_speech(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None
    ) -> str:
        """
        Generate speech audio from text.
        
        Args:
            text: The text to convert to speech
            output_path: Path to save the audio file
            voice_id: Optional voice ID (uses default from settings if not provided)
            model_id: Optional model ID (uses default from settings if not provided)
            
        Returns:
            Path to the generated audio file
        """
        voice = voice_id or self.settings.elevenlabs.voice_id
        model = model_id or self.settings.elevenlabs.model_id
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        url = f"{self.base_url}/text-to-speech/{voice}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        response = requests.post(url, json=data, headers=headers, stream=True)
        response.raise_for_status()
        
        # Write audio to file
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        
        return output_path
    
    def generate_speech_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None
    ) -> Iterator[bytes]:
        """
        Generate speech audio as a stream.
        
        Args:
            text: The text to convert to speech
            voice_id: Optional voice ID
            model_id: Optional model ID
            
        Yields:
            Audio data chunks
        """
        voice = voice_id or self.settings.elevenlabs.voice_id
        model = model_id or self.settings.elevenlabs.model_id
        
        url = f"{self.base_url}/text-to-speech/{voice}/stream"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        response = requests.post(url, json=data, headers=headers, stream=True)
        response.raise_for_status()
        
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                yield chunk
    
    def get_audio_duration(self, audio_path: str) -> float:
        """
        Get the duration of an audio file in seconds.
        
        Args:
            audio_path: Path to the audio file
            
        Returns:
            Duration in seconds
        """
        import subprocess
        import json
        
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            audio_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
        return 0.0
    
    def list_voices(self) -> list:
        """
        List available voices.
        
        Returns:
            List of voice objects with id and name
        """
        url = f"{self.base_url}/voices"
        headers = {"xi-api-key": self.api_key}
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        return [
            {"id": v["voice_id"], "name": v["name"]}
            for v in data.get("voices", [])
        ]
    
    def generate_narrations_batch(
        self,
        texts: list[str],
        output_dir: str,
        voice_id: Optional[str] = None
    ) -> list[dict]:
        """
        Generate narration audio for multiple texts.
        
        Args:
            texts: List of texts to convert
            output_dir: Directory to save audio files
            voice_id: Optional voice ID
            
        Returns:
            List of dicts with path and duration for each audio
        """
        os.makedirs(output_dir, exist_ok=True)
        results = []
        
        for i, text in enumerate(texts):
            if not text.strip():
                results.append({"path": None, "duration": 0})
                continue
            
            output_path = os.path.join(output_dir, f"narration_{i:04d}.mp3")
            
            try:
                self.generate_speech(text, output_path, voice_id)
                duration = self.get_audio_duration(output_path)
                results.append({
                    "path": output_path,
                    "duration": duration
                })
            except Exception as e:
                print(f"Failed to generate audio for text {i}: {e}")
                results.append({"path": None, "duration": 0, "error": str(e)})
        
        return results
    
    async def generate_speech_async(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        use_turbo: bool = True
    ) -> Tuple[str, float]:
        """
        Generate speech audio from text asynchronously.
        
        Args:
            text: The text to convert to speech
            output_path: Path to save the audio file
            voice_id: Optional voice ID
            model_id: Optional model ID
            use_turbo: Use turbo model for faster generation (default: True)
            
        Returns:
            Tuple of (output_path, duration)
        """
        voice = voice_id or self.settings.elevenlabs.voice_id
        
        # Use turbo model for speed if requested
        if use_turbo:
            model = "eleven_turbo_v2_5"  # Fastest model
        else:
            model = model_id or self.settings.elevenlabs.model_id
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        url = f"{self.base_url}/text-to-speech/{voice}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "speed": 1.0  # Normal speech speed
            }
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            
            with open(output_path, "wb") as f:
                f.write(response.content)
        
        duration = self.get_audio_duration(output_path)
        return (output_path, duration)
    
    async def generate_speeches_parallel(
        self,
        items: List[Tuple[str, str]],  # List of (text, output_path)
        voice_id: Optional[str] = None,
        batch_size: int = 5,
        use_turbo: bool = True,
        use_timestamps: bool = False
    ) -> List[Tuple[str, float]]:
        """
        Generate multiple speech audio files in PARALLEL batches.
        
        Processes TTS requests in batches concurrently for much faster
        total generation time.
        
        Args:
            items: List of (text, output_path) tuples
            voice_id: Optional voice ID
            batch_size: Number of concurrent TTS requests (default: 5)
            use_turbo: Use turbo model for faster generation (default: True)
            
        Returns:
            List of (output_path, duration) tuples in same order as input
        """
        all_results = []
        total_items = len(items)
        
        for batch_start in range(0, total_items, batch_size):
            batch_end = min(batch_start + batch_size, total_items)
            batch = items[batch_start:batch_end]
            
            print(f"⚡ Generating TTS {batch_start+1}-{batch_end} in parallel...", flush=True)
            
            # Create tasks for parallel execution
            tasks = []
            for text, output_path in batch:
                if not text.strip():
                    # Empty text - create a placeholder result
                    # IMPORTANT: downstream expects the MP3 path to exist; generate a tiny silent placeholder.
                    silent_dur = self._ensure_silent_mp3(output_path)
                    tasks.append(asyncio.sleep(0, result=(output_path, silent_dur)))
                else:
                    if use_timestamps:
                        tasks.append(self.generate_speech_with_timestamps_async(
                            text=text,
                            output_path=output_path,
                            voice_id=voice_id,
                            use_turbo=use_turbo
                        ))
                    else:
                        tasks.append(self.generate_speech_async(
                            text=text,
                            output_path=output_path,
                            voice_id=voice_id,
                            use_turbo=use_turbo,
                        ))
            
            # Execute batch in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle results
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    print(f"⚠️ TTS {batch_start + i + 1} failed: {result}", flush=True)
                    text, output_path = batch[i]
                    # Ensure placeholder file exists so later pipeline steps don't crash.
                    silent_dur = self._ensure_silent_mp3(output_path)
                    all_results.append((output_path, silent_dur))
                else:
                    # result may be either (path, duration) or TTSResult depending on mode
                    if isinstance(result, TTSResult):
                        all_results.append((result.audio_path, result.duration))
                    else:
                        all_results.append(result)
            
            # Small delay between batches to avoid rate limits
            if batch_end < total_items:
                await asyncio.sleep(1)
        
        print(f"⚡ Generated {len(all_results)} audio files in parallel mode", flush=True)
        return all_results
    
    def optimize_text_for_speech(self, text: str) -> str:
        """
        Optimize text for better TTS output.
        
        Args:
            text: Raw text from scene description
            
        Returns:
            Optimized text for speech synthesis
        """
        # Remove common filler phrases
        fillers = [
            "In this scene,",
            "We see",
            "The scene shows",
            "Here we have",
        ]
        
        result = text
        for filler in fillers:
            result = result.replace(filler, "")
        
        # Clean up whitespace
        result = " ".join(result.split())
        
        # Add slight pauses with commas for dramatic effect
        # (ElevenLabs respects punctuation for pacing)
        
        return result.strip()
    
    def generate_speech_with_timestamps(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None
    ) -> TTSResult:
        """
        Generate speech audio with word-level timestamps.
        
        Uses ElevenLabs' /text-to-speech/{voice_id}/with-timestamps endpoint
        to get word-level alignment data for precise audio segmentation.
        
        Args:
            text: The text to convert to speech
            output_path: Path to save the audio file
            voice_id: Optional voice ID (uses default from settings if not provided)
            model_id: Optional model ID (uses default from settings if not provided)
            
        Returns:
            TTSResult with audio path, duration, and word alignments
        """
        voice = voice_id or self.settings.elevenlabs.voice_id
        model = model_id or self.settings.elevenlabs.model_id
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        url = f"{self.base_url}/text-to-speech/{voice}/with-timestamps"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        
        result = response.json()
        
        # Extract audio (base64 encoded)
        import base64
        audio_base64 = result.get("audio_base64", "")
        audio_data = base64.b64decode(audio_base64)
        
        with open(output_path, "wb") as f:
            f.write(audio_data)
        
        # Parse alignments
        alignments = []
        alignment_data = result.get("alignment", {})
        
        # ElevenLabs returns character-level alignment
        # We need to reconstruct word-level from characters
        characters = alignment_data.get("characters", [])
        char_start_times = alignment_data.get("character_start_times_seconds", [])
        char_end_times = alignment_data.get("character_end_times_seconds", [])

        # Compute alignment-derived duration (preferred for tight sync)
        alignment_duration_seconds: Optional[float] = None
        try:
            if char_start_times and char_end_times:
                alignment_duration_seconds = float(char_end_times[-1]) - float(char_start_times[0])
                if alignment_duration_seconds < 0:
                    alignment_duration_seconds = None
        except Exception:
            alignment_duration_seconds = None
        
        if characters and char_start_times and char_end_times:
            current_word = ""
            word_start = None
            
            for i, char in enumerate(characters):
                if char == " " or i == len(characters) - 1:
                    # End of word
                    if i == len(characters) - 1 and char != " ":
                        current_word += char
                    
                    if current_word and word_start is not None:
                        word_end = char_end_times[i - 1] if char == " " else char_end_times[i]
                        alignments.append(WordAlignment(
                            word=current_word,
                            start_time=word_start,
                            end_time=word_end
                        ))
                    current_word = ""
                    word_start = None
                else:
                    if word_start is None:
                        word_start = char_start_times[i]
                    current_word += char
        
        # Get total duration from ffprobe (diagnostics)
        audio_duration_seconds = self.get_audio_duration(output_path)
        # Preferred duration: alignment if present, else audio duration.
        preferred_duration_seconds = alignment_duration_seconds if alignment_duration_seconds is not None else audio_duration_seconds
        
        return TTSResult(
            audio_path=output_path,
            duration=preferred_duration_seconds,
            audio_duration_seconds=audio_duration_seconds,
            alignment_duration_seconds=alignment_duration_seconds,
            alignments=alignments
        )
    
    def find_sentence_boundaries(
        self, 
        text: str, 
        alignments: List[WordAlignment]
    ) -> List[Dict[str, Any]]:
        """
        Find sentence boundaries from word alignments.
        
        Uses punctuation (. ! ?) to detect sentence endings.
        
        Args:
            text: Original text
            alignments: Word-level alignments from TTS
            
        Returns:
            List of sentence info: [{"text": "...", "start": 0.0, "end": 2.5, "words": [...]}, ...]
        """
        import re
        
        # Split text into sentences
        sentence_pattern = r'(?<=[.!?])\s+'
        sentences = re.split(sentence_pattern, text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not alignments:
            # No alignment data - estimate equal distribution
            total_duration = alignments[-1].end_time if alignments else 0
            duration_per_sentence = total_duration / len(sentences) if sentences else 0
            
            result = []
            current_time = 0
            for sent in sentences:
                result.append({
                    "text": sent,
                    "start": current_time,
                    "end": current_time + duration_per_sentence,
                    "words": []
                })
                current_time += duration_per_sentence
            return result
        
        # Match sentences to word alignments
        result = []
        word_idx = 0
        
        for sentence in sentences:
            sentence_words = sentence.split()
            if not sentence_words:
                continue
            
            # Find words that belong to this sentence
            matched_words = []
            sentence_start = None
            sentence_end = None
            
            for word in sentence_words:
                # Clean punctuation for matching
                clean_word = word.strip('.,!?;:"\'-')
                
                # Find matching alignment
                while word_idx < len(alignments):
                    align = alignments[word_idx]
                    align_clean = align.word.strip('.,!?;:"\'-')
                    
                    if align_clean.lower() == clean_word.lower() or clean_word.lower() in align_clean.lower():
                        if sentence_start is None:
                            sentence_start = align.start_time
                        sentence_end = align.end_time
                        matched_words.append(align)
                        word_idx += 1
                        break
                    word_idx += 1
            
            if sentence_start is not None:
                result.append({
                    "text": sentence,
                    "start": sentence_start,
                    "end": sentence_end,
                    "words": matched_words
                })
        
        return result

