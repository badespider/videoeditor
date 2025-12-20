"""
Audio Segmenter Service - The "Master Clock"

Generates TTS audio from the story script and splits it into sentence-level
segments with precise timing information.

Part of the Audio-First Pipeline:
1. Transcript -> Script Generator -> bible.txt
2. Bible -> Audio Segmenter -> TTS audio with timestamps
3. Audio + Visual Search -> Elastic Stitch
"""

import os
import re
import subprocess
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from app.services.elevenlabs_client import ElevenLabsClient, TTSResult
from app.services.ffmpeg_utils import run_ffmpeg, run_ffmpeg_capture, FFmpegError
from app.config import get_settings


@dataclass
class AudioSegment:
    """A segment of narration audio with metadata."""
    id: int
    text: str
    file_path: str
    duration: float
    start_time: float  # In the full audio
    end_time: float    # In the full audio


class AudioSegmenter:
    """
    Generates TTS audio and splits it by sentence.
    
    The "Master Clock" module that creates the timing blueprint for the video.
    Each sentence becomes a discrete audio segment that drives video search.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.elevenlabs = ElevenLabsClient()
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using punctuation.
        
        Handles:
        - Period, exclamation, question marks
        - Preserves quotes and dialogue
        - Merges short fragments
        """
        # Split on sentence-ending punctuation
        # But keep the punctuation with the sentence
        pattern = r'(?<=[.!?])\s+(?=[A-Z])'
        raw_sentences = re.split(pattern, text.strip())
        
        sentences = []
        for sent in raw_sentences:
            sent = sent.strip()
            if not sent:
                continue
            
            # If sentence is very short (< 3 words), merge with previous
            words = sent.split()
            if len(words) < 3 and sentences:
                sentences[-1] = sentences[-1] + " " + sent
            else:
                sentences.append(sent)
        
        return sentences
    
    def _split_audio_file(
        self,
        audio_path: str,
        start_time: float,
        end_time: float,
        output_path: str
    ) -> str:
        """
        Extract a segment from an audio file using FFmpeg.
        
        Args:
            audio_path: Source audio file
            start_time: Start time in seconds
            end_time: End time in seconds
            output_path: Where to save the segment
            
        Returns:
            Path to the extracted segment
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        duration = end_time - start_time
        
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_path
        ]

        run_ffmpeg(cmd)
        
        return output_path
    
    def _calculate_sentence_weight(self, sentence: str, is_paragraph_end: bool) -> float:
        """
        Calculate a weight for sentence duration estimation.
        
        Accounts for:
        - Word count (base)
        - Commas (add pause time)
        - Colons/semicolons (add pause)
        - Paragraph endings (longer pause after)
        
        Args:
            sentence: The sentence text
            is_paragraph_end: Whether this sentence ends a paragraph
            
        Returns:
            Weighted value for duration calculation
        """
        word_count = len(sentence.split())
        
        # Base weight is word count
        weight = float(word_count)
        
        # Commas add ~0.2 "word equivalents" each (slight pause)
        comma_count = sentence.count(',')
        weight += comma_count * 0.2
        
        # Colons and semicolons add ~0.3 (longer pause)
        colon_count = sentence.count(':') + sentence.count(';')
        weight += colon_count * 0.3
        
        # Ellipsis adds dramatic pause (~0.5)
        if '...' in sentence:
            weight += 0.5
        
        # Paragraph endings have natural pause after (~0.4 word equivalents)
        if is_paragraph_end:
            weight += 0.4
        
        # Question marks and exclamations often have emphasis
        if sentence.rstrip().endswith('?') or sentence.rstrip().endswith('!'):
            weight += 0.15
        
        return weight
    
    def _detect_paragraph_boundaries(self, sentences: List[str], original_text: str) -> List[bool]:
        """
        Detect which sentences are at the end of paragraphs.
        
        Uses double newlines in original text to detect paragraph breaks.
        
        Args:
            sentences: List of sentence texts
            original_text: The original full text
            
        Returns:
            List of bools indicating if each sentence ends a paragraph
        """
        # Split original text into paragraphs
        paragraphs = original_text.split('\n\n')
        paragraph_endings = set()
        
        for para in paragraphs:
            para = para.strip()
            if para:
                # The last sentence of each paragraph
                paragraph_endings.add(para[-50:])  # Use last 50 chars as marker
        
        results = []
        for sent in sentences:
            sent_end = sent.strip()[-50:] if len(sent.strip()) >= 50 else sent.strip()
            is_para_end = any(sent_end in ending for ending in paragraph_endings)
            results.append(is_para_end)
        
        return results
    
    def _estimate_sentence_timings(
        self,
        sentences: List[str],
        total_duration: float,
        original_text: str = ""
    ) -> List[dict]:
        """
        Estimate timing for each sentence with smart weighting.
        
        Fallback method when timestamp API is unavailable.
        Uses weighted estimation based on:
        - Word count (base)
        - Punctuation (commas, colons add pauses)
        - Paragraph boundaries (longer pauses)
        
        Args:
            sentences: List of sentence texts
            total_duration: Total audio duration in seconds
            original_text: Original full text for paragraph detection
            
        Returns:
            List of {"text": "...", "start": 0.0, "end": 2.5}
        """
        if not sentences:
            return []
        
        # Detect paragraph boundaries
        if original_text:
            para_ends = self._detect_paragraph_boundaries(sentences, original_text)
        else:
            # Assume every 3-4 sentences might be a paragraph end
            para_ends = [(i + 1) % 4 == 0 for i in range(len(sentences))]
        
        # Calculate weights for each sentence
        weights = []
        for i, sent in enumerate(sentences):
            is_para_end = para_ends[i] if i < len(para_ends) else False
            weight = self._calculate_sentence_weight(sent, is_para_end)
            weights.append(weight)
        
        total_weight = sum(weights)
        if total_weight == 0:
            return []
        
        # Distribute duration based on weights
        results = []
        current_time = 0.0
        
        for i, sent in enumerate(sentences):
            # Duration proportional to weight
            sentence_duration = (weights[i] / total_weight) * total_duration
            
            # Minimum duration floor (0.5s) to avoid micro-segments
            sentence_duration = max(0.5, sentence_duration)
            
            results.append({
                "text": sent,
                "start": current_time,
                "end": current_time + sentence_duration
            })
            
            current_time += sentence_duration
        
        # Normalize to fit total duration exactly
        if results:
            scale_factor = total_duration / current_time
            current_time = 0.0
            for r in results:
                duration = (r["end"] - r["start"]) * scale_factor
                r["start"] = current_time
                r["end"] = current_time + duration
                current_time += duration
        
        return results
    
    async def generate_voiceover(
        self,
        script_text: str,
        output_dir: str,
        use_timestamps: bool = True
    ) -> List[AudioSegment]:
        """
        Generate TTS audio split by sentence.
        
        This is the main method that:
        1. Generates full audio from script
        2. Gets word-level timestamps (if available)
        3. Splits audio at sentence boundaries
        4. Returns list of segments with timing
        
        Args:
            script_text: The story script from ScriptGenerator
            output_dir: Directory to save audio files
            use_timestamps: Whether to use ElevenLabs timestamp API
            
        Returns:
            List of AudioSegment objects with file paths and timing
        """
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"🎙️ Generating voiceover ({len(script_text)} chars)...", flush=True)
        
        # Split script into sentences
        sentences = self._split_into_sentences(script_text)
        print(f"📝 Found {len(sentences)} sentences", flush=True)
        
        if not sentences:
            return []
        
        # Generate full audio
        full_audio_path = os.path.join(output_dir, "full_narration.mp3")
        
        if use_timestamps:
            try:
                # Use timestamp API for precise timing
                tts_result = self.elevenlabs.generate_speech_with_timestamps(
                    text=script_text,
                    output_path=full_audio_path
                )
                
                # Get sentence boundaries from word alignments
                sentence_timings = self.elevenlabs.find_sentence_boundaries(
                    script_text,
                    tts_result.alignments or []
                )
                
                # Prefer alignment duration for timing, but keep ffprobe for diagnostics.
                align_dur = getattr(tts_result, "alignment_duration_seconds", None)
                audio_dur = getattr(tts_result, "audio_duration_seconds", tts_result.duration)
                print(
                    f"✅ Generated audio with timestamps (alignment={align_dur if align_dur is not None else 'n/a'}s, audio={audio_dur:.1f}s)",
                    flush=True
                )

                # If alignment matching failed (e.g., couldn't map many sentences), treat as failure and fall back.
                if not sentence_timings or len(sentence_timings) < max(1, int(len(sentences) * 0.5)):
                    raise Exception(f"Alignment insufficient: matched {len(sentence_timings)}/{len(sentences)} sentences")
                
            except Exception as e:
                print(f"⚠️ Timestamp API failed, falling back to estimation: {e}", flush=True)
                use_timestamps = False
        
        if not use_timestamps:
            # Fallback: generate without timestamps, estimate timings
            self.elevenlabs.generate_speech(
                text=script_text,
                output_path=full_audio_path
            )
            # Use actual audio duration (ffprobe) for fallback estimator.
            total_duration = self.elevenlabs.get_audio_duration(full_audio_path)
            sentence_timings = self._estimate_sentence_timings(
                sentences, 
                total_duration,
                original_text=script_text  # For paragraph boundary detection
            )
            print(f"✅ Generated audio (estimated timings, {total_duration:.1f}s)", flush=True)
        
        # Split audio into sentence files
        segments = []
        
        for i, timing in enumerate(sentence_timings):
            segment_path = os.path.join(output_dir, f"sentence_{i:04d}.mp3")
            
            try:
                self._split_audio_file(
                    audio_path=full_audio_path,
                    start_time=timing["start"],
                    end_time=timing["end"],
                    output_path=segment_path
                )
                
                # Verify segment duration
                actual_duration = self.elevenlabs.get_audio_duration(segment_path)
                
                segments.append(AudioSegment(
                    id=i,
                    text=timing["text"],
                    file_path=segment_path,
                    duration=actual_duration,
                    start_time=timing["start"],
                    end_time=timing["end"]
                ))
                
            except Exception as e:
                print(f"⚠️ Failed to extract segment {i}: {e}", flush=True)
                # Still add the segment info, just without file
                segments.append(AudioSegment(
                    id=i,
                    text=timing["text"],
                    file_path="",
                    duration=timing["end"] - timing["start"],
                    start_time=timing["start"],
                    end_time=timing["end"]
                ))
        
        print(f"✂️ Split into {len(segments)} audio segments", flush=True)
        
        return segments
    
    async def generate_voiceover_direct(
        self,
        sentences: List[str],
        output_dir: str
    ) -> List[AudioSegment]:
        """
        Generate TTS audio for each sentence individually.
        
        Alternative approach that generates each sentence separately.
        More API calls but more reliable timing.
        
        Args:
            sentences: List of sentence texts
            output_dir: Directory to save audio files
            
        Returns:
            List of AudioSegment objects
        """
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"🎙️ Generating voiceover (direct mode, {len(sentences)} sentences)...", flush=True)
        
        segments = []
        cumulative_time = 0.0
        
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            
            segment_path = os.path.join(output_dir, f"sentence_{i:04d}.mp3")
            
            try:
                # Generate audio for this sentence only
                self.elevenlabs.generate_speech(
                    text=sentence,
                    output_path=segment_path
                )
                
                duration = self.elevenlabs.get_audio_duration(segment_path)
                
                segments.append(AudioSegment(
                    id=i,
                    text=sentence,
                    file_path=segment_path,
                    duration=duration,
                    start_time=cumulative_time,
                    end_time=cumulative_time + duration
                ))
                
                cumulative_time += duration
                
                print(f"  [{i+1}/{len(sentences)}] Generated: {duration:.1f}s", flush=True)
                
            except Exception as e:
                print(f"⚠️ Failed sentence {i}: {e}", flush=True)
        
        print(f"✅ Generated {len(segments)} audio segments", flush=True)
        
        return segments
    
    def get_total_duration(self, segments: List[AudioSegment]) -> float:
        """Calculate total duration of all segments."""
        return sum(seg.duration for seg in segments)
    
    def concatenate_audio_files(
        self,
        audio_files: List[str],
        output_path: str
    ) -> str:
        """
        Concatenate multiple audio files into a single file.
        
        Used to combine TTS narration with original audio clips
        for chapters that have key moments.
        
        Args:
            audio_files: List of paths to audio files (in order)
            output_path: Path for the concatenated output file
            
        Returns:
            Path to the concatenated audio file
        """
        if not audio_files:
            raise ValueError("No audio files to concatenate")
        
        if len(audio_files) == 1:
            # Just copy the single file
            import shutil
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            shutil.copy2(audio_files[0], output_path)
            return output_path
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        print(f"🔗 Concatenating {len(audio_files)} audio files...", flush=True)
        
        # Create a temporary file list for FFmpeg concat
        list_file = output_path + ".list.txt"
        try:
            with open(list_file, "w") as f:
                for audio_file in audio_files:
                    # FFmpeg concat requires escaped paths
                    escaped_path = audio_file.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # Use FFmpeg concat demuxer
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",  # Stream copy (fast, no re-encoding)
                output_path
            ]
            
            result = run_ffmpeg_capture(cmd, check=False)

            if result.returncode != 0:
                print(f"⚠️ Stream copy failed, re-encoding...", flush=True)
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", list_file,
                    "-acodec", "libmp3lame",
                    "-ar", "44100",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
                run_ffmpeg(cmd)
            
            # Get duration of concatenated file
            duration = self._get_audio_duration(output_path)
            print(f"✅ Concatenated audio: {duration:.2f}s total", flush=True)
            
            return output_path
            
        finally:
            # Clean up temp list file
            if os.path.exists(list_file):
                os.remove(list_file)
    
    def _get_audio_duration(self, file_path: str) -> float:
        """Get duration of an audio file using ffprobe."""
        import json
        
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
        return 0.0

