"""
Script Generator Service - The "Author" Module

Converts raw audio transcripts from Memories.ai into dramatic 3rd-person
story scripts ("Bible") using Gemini.

Part of the Audio-First Pipeline:
1. Transcript -> Script Generator -> bible.txt
2. Bible -> Audio Segmenter -> TTS audio
3. Audio + Visual Search -> Elastic Stitch
"""

import asyncio
import re
import json as _json
import time as _time
from typing import List, Optional
from dataclasses import dataclass

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from app.config import get_settings
from app.services.gemini_client import ContinuousNarrator


def parse_time(time_str) -> float:
    """
    Convert timestamp string to seconds.
    
    Handles formats:
    - "00:01:30" (HH:MM:SS)
    - "01:30" (MM:SS) 
    - "90" or "90.5" (seconds as string)
    - 90 or 90.5 (already a number)
    
    Args:
        time_str: Timestamp string or number
        
    Returns:
        Time in seconds as float
    """
    if time_str is None:
        return 0.0
    
    # Already a number
    if isinstance(time_str, (int, float)):
        return float(time_str)
    
    time_str = str(time_str).strip()
    
    if not time_str:
        return 0.0
    
    # Try direct float conversion first (handles "90" or "90.5")
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


@dataclass
class TranscriptSegment:
    """A segment of the transcript with timing info."""
    text: str
    start_time: float
    end_time: float
    speaker: Optional[str] = None


# Story structure labels for narrative context
STORY_STRUCTURE_LABELS = {
    "intro": "Character introduction and premise",
    "conflict": "Initial conflict/goal established", 
    "rising": "Escalation and complications",
    "climax": "Major confrontation/decision",
    "resolution": "Consequences and wrap-up"
}


def get_script_label(scene_number: int, total_scenes: int) -> str:
    """
    Auto-detect which story phase we're in based on scene position.
    
    Args:
        scene_number: Current scene number (1-based)
        total_scenes: Total number of scenes
        
    Returns:
        Story phase label: "intro", "conflict", "rising", "climax", or "resolution"
    """
    if total_scenes <= 0:
        return "intro"
    
    percent = scene_number / total_scenes
    
    if percent < 0.15:
        return "intro"
    elif percent < 0.4:
        return "conflict" 
    elif percent < 0.8:
        return "rising"
    elif percent < 0.95:
        return "climax"
    else:
        return "resolution"


class ScriptGenerator:
    """
    Converts dialogue transcripts into dramatic 3rd-person story scripts.
    
    The "Author" module that transforms raw dialogue into narration-ready
    story text while preserving plot accuracy and character names.
    """
    
    def __init__(self):
        self.settings = get_settings()
        
        # Configure Gemini API
        genai.configure(api_key=self.settings.gemini.api_key)
        
        # Initialize continuous narrator for story flow
        self.narrator = ContinuousNarrator(max_context_length=3)
        
        # Safety settings for all models
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # Use Gemini 2.0 Flash for longer context and better rate limits
        self.model = genai.GenerativeModel(
            'gemini-2.0-flash',  # Use flash for speed; upgrade to pro for quality
            safety_settings=self.safety_settings
        )
    
    def _get_fresh_model(self):
        """Get a fresh model instance to avoid event loop issues."""
        return genai.GenerativeModel(
            'gemini-2.0-flash',
            safety_settings=self.safety_settings
        )
    
    def _clean_narration_output(self, narration: str) -> str:
        """
        Comprehensive cleanup of narration output.
        
        Removes:
        - JSON artifacts
        - Chapter markers
        - Banned transition words
        - Meta-commentary
        - Transcription garbage
        - Vague language
        
        Args:
            narration: Raw narration text from AI
            
        Returns:
            Cleaned narration text
        """
        if not narration:
            return ""
        
        narration = narration.strip().strip('"\'')
        
        # Remove JSON artifacts
        narration = re.sub(r'^```json\s*', '', narration)
        narration = re.sub(r'^```\s*', '', narration)
        narration = re.sub(r'\s*```$', '', narration)
        narration = re.sub(r'^\[\s*"', '', narration)
        narration = re.sub(r'"\s*\]$', '', narration)
        
        # Remove chapter/section labels
        narration = re.sub(r'^CHAPTER\s*\d+\s*(\[[^\]]*\])?\s*:?\s*', '', narration, flags=re.IGNORECASE)
        narration = re.sub(r'^SECTION\s*\d+\s*:?\s*', '', narration, flags=re.IGNORECASE)
        narration = re.sub(r'^Ch\.\s*\d+\s*:?\s*', '', narration, flags=re.IGNORECASE)
        narration = re.sub(r'^#\d+\s*', '', narration)
        
        # Remove timestamp markers
        narration = re.sub(r'^\d+:\d+\s*-\s*\d+:\d+\s*', '', narration)
        narration = re.sub(r'^\[\d+:\d+\s*-\s*\d+:\d+\]\s*', '', narration)
        
        # Remove banned transition words at the start
        banned_starts = [
            r'^Elsewhere,?\s*',
            r'^Somewhere,?\s*',
            r'^Meanwhile,?\s*',
            r'^Back at[^,]*,?\s*',
            r'^In another part of[^,]*,?\s*',
            r'^The scene shows\s*',
            r'^The scene shifts to\s*',
            r'^The scene transitions to\s*',
            r'^The scene returns to\s*',
            r'^Things cut to\s*',
            r'^Now we\'re at\s*',
            r'^Speaking of\s*',
            r'^On that note,?\s*',
            r'^We see\s*',
            r'^We get\s*',
            r'^We\'re\s+',
            r'^The camera shows\s*',
            r'^The camera then\s*',
            r'^The camera zeroes\s*',
            r'^The video shows\s*',
            r'^The film shows\s*',
            r'^This story kicks off\s*',
            r'^Alright,?\s*',
            r'^So,?\s+basically\s*',
        ]
        for pattern in banned_starts:
            narration = re.sub(pattern, '', narration, flags=re.IGNORECASE)
        
        # Remove YouTuber language patterns (anywhere in text)
        youtuber_patterns = [
            r',?\s*let me tell you[,.]?\s*',
            r',?\s*trust me[,.]?\s*',
            r',?\s*right\?\s*',
            r',?\s*if you know what I mean[,.]?\s*',
            r'\s*–\s*always a good sign!?\s*',
            r',?\s*always a good sign!?\s*',
            r',?\s*unsettling,? right\?\s*',
            r',?\s*creepy,? right\?\s*',
            r'\s*Think [^.]*Club Med[^.]*\.\s*',
            r'\s*It\'s not exactly [^.]*\.\s*',
        ]
        for pattern in youtuber_patterns:
            narration = re.sub(pattern, ' ', narration, flags=re.IGNORECASE)
        
        # Remove meta-commentary sentences
        meta_patterns = [
            r"The text says[^.]*\.\s*",
            r"The screen shows[^.]*\.\s*",
            r"The screen flashes[^.]*\.\s*",
            r"A title card[^.]*\.\s*",
            r"A caption flashes[^.]*\.\s*",
            r"A subtitle flashes[^.]*\.\s*",
            r"The next line says[^.]*\.\s*",
            r"It then switches to[^.]*\.\s*",
            r"The scene depicts[^.]*\.\s*",
            r"The scene returns[^.]*\.\s*",
            r"We're shown[^.]*\.\s*",
            r"We get this[^.]*\.\s*",
            r"We get glimpses[^.]*\.\s*",
            r"The movie shows[^.]*\.\s*",
            r"The film depicts[^.]*\.\s*",
            r"Credits and art flash[^.]*\.\s*",
            r"Credits roll[^.]*\.\s*",
        ]
        for pattern in meta_patterns:
            narration = re.sub(pattern, '', narration, flags=re.IGNORECASE)

        # Remove "scene description" language anywhere (not just at the start).
        # This is the main culprit for the "documentary / screenplay" feel.
        # Expanded to catch more verb variations and longer sentences (up to 200 chars).
        scene_language_patterns = [
            # "The scene <verb>..." - catch any verb, remove entire sentence
            r"\bthe scene\b[^.!?]{0,200}[.!?]\s*",
            # "The screen <verb>..." - flickers, shows, etc.
            r"\bthe screen\b[^.!?]{0,200}[.!?]\s*",
            # "The show <verb>..." - begins, opens with
            r"\bthe show\b[^.!?]{0,200}[.!?]\s*",
            # "The video <verb>..."
            r"\bthe video (shows|opens|begins|cuts|shifts|transitions)[^.!?]*[.!?]\s*",
            # "The camera <verb>..."
            r"\bthe camera\b[^.!?]{0,200}[.!?]\s*",
            # "In this scene..." / "In the scene..."
            r"\bin (this|the) scene\b[^.!?]{0,200}[.!?]\s*",
            # "The setting <verb>..." - abruptly changes, transitions, shifts
            r"\bthe setting\b[^.!?]{0,200}[.!?]\s*",
            # "The narrative <verb>..." - takes a turn, shifts, etc.
            r"\bthe narrative\b[^.!?]{0,200}[.!?]\s*",
            # "The focus <verb>..." - shifts, moves, etc.
            r"\bthe focus\b[^.!?]{0,200}[.!?]\s*",
            # "The title card..." - visual descriptions
            r"\bthe title card\b[^.!?]{0,200}[.!?]\s*",
            # "A title card appears..." / "Title card shows..."
            r"\b(a )?title card\b[^.!?]{0,200}[.!?]\s*",
            # Generic visual framing phrases
            r"\bwe see\b\s*",
            r"\bwe watch\b\s*",
            r"\bwe observe\b\s*",
            r"\bwe're shown\b\s*",
            r"\bwe're immediately\b[^.!?]{0,200}[.!?]\s*",
            r"\bon screen\b[^.!?]*[.!?]\s*",
            # "It is revealed that..." / "It's revealed..."
            r"\bit('s| is) revealed (that )?\b",
            # "Abruptly, ..." / "Suddenly, the image..." (screenplay feel)
            r"\babruptly,\s*",
            r"\bsuddenly,\s+the (image|scene|screen)\b[^.!?]*[.!?]\s*",
            # Documentary transitions
            r"\bin another shift,?\s*",
            r"\bfollowing the[^,]{0,50},\s*",
            # Visual passive descriptions
            r"\bis prominently displayed\b",
            r"\bare prominently displayed\b",
            r", (his|her|their) expressions? (suggesting|betraying|showing)[^,.]*[,.]",
            r", leaving (him|her|them) visibly [^,.]*[,.]",
            # Opening scene descriptions
            r"^the bustling streets\b[^.!?]{0,200}[.!?]\s*",
            r"^amidst the\b[^.!?]{0,200}[.!?]\s*",
        ]
        for pattern in scene_language_patterns:
            narration = re.sub(pattern, ' ', narration, flags=re.IGNORECASE)
        
        # Aggressive visual description removal (the patterns Gemini keeps using)
        visual_patterns = [
            # Face/expression descriptions
            r",?\s*(his|her|their) faces? etched with[^,.]*[,.]?",
            r",?\s*(his|her|their) expressions? (suggesting|betraying|showing|a mixture of)[^,.]*[,.]?",
            r",?\s*(his|her|their) eyes (reflecting|gleaming|burning|fixed)[^,.]*[,.]?",
            r",?\s*(his|her|their) (knuckles|hands|fingers) (white|gripping|pressing)[^,.]*[,.]?",
            r",?\s*a (cold |chilling |)glint in (his|her|their) eyes?[^,.]*[,.]?",
            # Body language descriptions
            r",?\s*(his|her|their) gaze (unwavering|fixed|intense)[^,.]*[,.]?",
            r",?\s*determination (blazing|burning|shining) in (his|her|their) eyes[^,.]*[,.]?",
            # Scene-setting adjectives
            r"\ba sprawling metropolis\b",
            r"\ba harbor where dreams dock\b",
            r"\bshadows lurk\b",
            r"\bsickly green light\b",
            r"\bdimly lit\b",
            r"\bbustling\b",
            # Visual framing
            r",?\s*a (stark |)contrast to[^,.]*[,.]?",
            r",?\s*a (silent |)observer[^,.]*[,.]?",
            r",?\s*its presence dominating[^,.]*[,.]?",
            # Weak openings that describe visuals
            r"^A (crimson|green|blue|red|dark|bright) hue[^.]*\.\s*",
            r"^The (room|scene|frame|shot) is (washed|bathed|filled)[^.]*\.\s*",
            # Camera/viewer language that still slips through
            r"\bwe're plunged into\b",
            r"\bwe see it\b",
            r"\bwe see\b",
            r"\bthe image zooms\b",
            r"\bthe camera zooms\b",
            r"\band then we see\b",
            r"\bthen we see\b",
            # Section labels
            r"^SECTION \d+:\s*",
        ]
        for pattern in visual_patterns:
            narration = re.sub(pattern, '', narration, flags=re.IGNORECASE)
        
        # Remove transcription garbage
        garbage_patterns = [
            r'\bThe End\b\.?\s*',
            r'\broz\b\.?\s*',
            r'\bShish\b\.?\s*',
            r'\bOi\b\s*!?\s*',
            r'\b[А-Яа-яЁё]+\b',  # Cyrillic/Russian text
            r'\[Music\]',
            r'\[Applause\]',
            r'\[Laughter\]',
            r'♪[^♪]*♪',
            r'🎵[^🎵]*🎵',
        ]
        for pattern in garbage_patterns:
            narration = re.sub(pattern, '', narration, flags=re.IGNORECASE)
        
        # Remove repeated phrases (like "The End, The End, The End")
        narration = re.sub(r'(\b\w+\b)(\s*,?\s*\1){2,}', r'\1', narration, flags=re.IGNORECASE)
        
        # Remove on-screen text references
        narration = re.sub(r"'[^']*Studios'[^.]*\.", '', narration)
        narration = re.sub(r'"[^"]*Studios"[^.]*\.', '', narration)
        
        # Note: We no longer auto-replace vague language since the AI should use
        # proper character names from the structured data. Auto-replacement could
        # introduce incorrect names (e.g., replacing "A figure" with "A warrior" 
        # when it should be a specific character name).
        
        # Clean up whitespace
        narration = re.sub(r'\s+', ' ', narration).strip()
        
        # Ensure it doesn't start with lowercase after cleaning
        if narration and narration[0].islower():
            narration = narration[0].upper() + narration[1:]
        
        return narration
    
    def _extract_names_from_dialogue(self, audio_transcript: List[dict]) -> List[str]:
        """
        Extract character names mentioned in dialogue.
        
        Scans the audio transcript for potential character names that appear in:
        - Direct address: "Kaliska!", "Dek, listen!", "Thea?"
        - References: "Where is Thea?", "Kaliska is coming", "Tell Dek"
        - Introductions: "I am Dek", "My name is Thea"
        
        Args:
            audio_transcript: List of transcript segments with 'text' field
            
        Returns:
            List of unique character names found in dialogue
        """
        if not audio_transcript:
            return []
        
        # Combine all dialogue text
        all_text = " ".join(seg.get("text", "") for seg in audio_transcript)
        
        # Common words to exclude (not character names)
        common_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
            'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
            'from', 'up', 'about', 'into', 'over', 'after', 'beneath', 'under',
            'above', 'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves',
            'you', 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his',
            'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself',
            'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which',
            'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'been',
            'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
            'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
            'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'now',
            'yes', 'no', 'okay', 'ok', 'please', 'thank', 'thanks', 'sorry',
            'hello', 'hi', 'hey', 'goodbye', 'bye', 'well', 'oh', 'ah', 'um',
            'uh', 'like', 'know', 'think', 'want', 'go', 'come', 'see', 'look',
            'get', 'make', 'take', 'give', 'find', 'tell', 'say', 'said',
            'father', 'mother', 'brother', 'sister', 'son', 'daughter',
            'man', 'woman', 'boy', 'girl', 'child', 'children', 'people',
            'human', 'humans', 'creature', 'creatures', 'monster', 'monsters',
            'warrior', 'warriors', 'hunter', 'hunters', 'predator', 'predators',
            'alien', 'aliens', 'one', 'two', 'three', 'first', 'second', 'last',
            'end', 'music', 'scene', 'video', 'film', 'movie'
        }
        
        found_names = set()
        
        # Pattern 1: Direct address - "Name!" or "Name," or "Name?"
        # Matches capitalized words followed by punctuation
        direct_address = re.findall(r'\b([A-Z][a-z]{2,15})[!?,]', all_text)
        for name in direct_address:
            if name.lower() not in common_words:
                found_names.add(name)
        
        # Pattern 2: "I am Name" or "My name is Name" or "Call me Name"
        intro_patterns = [
            r"I am ([A-Z][a-z]{2,15})",
            r"[Mm]y name is ([A-Z][a-z]{2,15})",
            r"[Cc]all me ([A-Z][a-z]{2,15})",
            r"[Tt]hey call me ([A-Z][a-z]{2,15})",
            r"I'm ([A-Z][a-z]{2,15})"
        ]
        for pattern in intro_patterns:
            matches = re.findall(pattern, all_text)
            for name in matches:
                if name.lower() not in common_words:
                    found_names.add(name)
        
        # Pattern 3: "Where is Name?" or "Find Name" or "Tell Name"
        reference_patterns = [
            r"[Ww]here is ([A-Z][a-z]{2,15})",
            r"[Ff]ind ([A-Z][a-z]{2,15})",
            r"[Tt]ell ([A-Z][a-z]{2,15})",
            r"[Aa]sk ([A-Z][a-z]{2,15})",
            r"[Kk]ill ([A-Z][a-z]{2,15})",
            r"[Ss]ave ([A-Z][a-z]{2,15})",
            r"[Pp]rotect ([A-Z][a-z]{2,15})",
            r"([A-Z][a-z]{2,15}) is coming",
            r"([A-Z][a-z]{2,15}) is here",
            r"([A-Z][a-z]{2,15}) is dead",
            r"([A-Z][a-z]{2,15}) is alive"
        ]
        for pattern in reference_patterns:
            matches = re.findall(pattern, all_text)
            for name in matches:
                if name.lower() not in common_words:
                    found_names.add(name)
        
        # Pattern 4: Repeated capitalized words (likely names if mentioned multiple times)
        # Find all capitalized words
        capitalized_words = re.findall(r'\b([A-Z][a-z]{2,15})\b', all_text)
        word_counts = {}
        for word in capitalized_words:
            if word.lower() not in common_words:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        # Add words that appear 3+ times (likely character names)
        for word, count in word_counts.items():
            if count >= 3:
                found_names.add(word)
        
        # Convert to sorted list
        names_list = sorted(list(found_names))
        
        if names_list:
            print(f"🔍 Extracted {len(names_list)} names from dialogue: {', '.join(names_list)}", flush=True)
        
        return names_list
    
    def _parse_transcript(self, raw_transcript: List[dict]) -> List[TranscriptSegment]:
        """
        Parse raw transcript from Memories.ai into structured segments.
        
        Expected format from Memories.ai:
        [{"text": "...", "start": 0.0, "end": 2.5, "speaker": "Speaker 1"}, ...]
        """
        segments = []
        for item in raw_transcript:
            segments.append(TranscriptSegment(
                text=item.get("text", ""),
                start_time=float(item.get("start", item.get("start_time", 0))),
                end_time=float(item.get("end", item.get("end_time", 0))),
                speaker=item.get("speaker")
            ))
        return segments
    
    def _chunk_transcript(
        self, 
        segments: List[TranscriptSegment], 
        chunk_minutes: int = 15
    ) -> List[List[TranscriptSegment]]:
        """
        Split transcript into chunks that fit context window.
        
        ~15 minutes of dialogue ≈ 3000-5000 words ≈ 4000-7000 tokens
        Gemini can handle much more, but chunking improves quality.
        """
        chunks = []
        current_chunk = []
        chunk_start_time = 0.0
        
        for segment in segments:
            # Check if this segment would exceed chunk duration
            if segment.end_time - chunk_start_time > chunk_minutes * 60:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [segment]
                chunk_start_time = segment.start_time
            else:
                current_chunk.append(segment)
        
        # Don't forget the last chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def _format_chunk_for_prompt(self, segments: List[TranscriptSegment]) -> str:
        """Format transcript segments into readable dialogue text."""
        lines = []
        for seg in segments:
            speaker = seg.speaker or "Speaker"
            lines.append(f"[{seg.start_time:.1f}s] {speaker}: {seg.text}")
        return "\n".join(lines)
    
    async def _convert_chunk_to_story(
        self, 
        chunk_text: str, 
        chunk_index: int, 
        total_chunks: int,
        previous_summary: str = ""
    ) -> str:
        """
        Convert a chunk of dialogue transcript into story narration.
        
        Args:
            chunk_text: Formatted dialogue text
            chunk_index: Which chunk this is (0-based)
            total_chunks: Total number of chunks
            previous_summary: Summary of previous chunks for continuity
            
        Returns:
            Story narration text for this chunk
        """
        context_info = ""
        if previous_summary:
            context_info = f"PREVIOUS STORY SO FAR:\n{previous_summary}\n\n"
        
        position = f"Part {chunk_index + 1} of {total_chunks}"
        
        prompt = (
            f"TASK: Convert this dialogue transcript into chronological 3rd-person narration.\n\n"
            f"POSITION: {position}\n\n"
            f"{context_info}"
            f"DIALOGUE TRANSCRIPT:\n{chunk_text}\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'He says' not 'He said' or 'He is saying'\n"
            f"2. SIMPLE SENTENCES: 'X does Y' not 'X, feeling Y, decides to Z'. Max 2 clauses per sentence.\n"
            f"3. CHRONOLOGICAL ORDER: Events must happen in sequence they appear in dialogue\n"
            f"4. USE CHARACTER NAMES: Always use names from the transcript. NEVER say 'someone', 'they', 'a character', 'a person'\n"
            f"5. CONNECT TO PREVIOUS: If there's PREVIOUS STORY SO FAR, reference it naturally. Use simple transitions: 'Next', 'Then', 'Meanwhile'\n"
            f"6. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone' or 'he sees looking upset'\n"
            f"7. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context. Say what it is.\n"
            f"8. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined', 'feels the weight'\n"
            f"9. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"10. KEEP ALL PLOT POINTS: Don't skip events, but describe them plainly.\n"
            f"11. SHORT PARAGRAPHS: 1-2 sentences max per paragraph for pacing.\n\n"
            f"EXAMPLE TRANSFORMATIONS:\n"
            f"❌ BAD: 'Realizing the gravity of the situation, Yuji suddenly decides...'\n"
            f"✅ GOOD: 'Yuji decides to fight the curse.'\n"
            f"\n❌ BAD: 'The young man is caught off guard by a shocking discovery...'\n"
            f"✅ GOOD: 'Yuji finds out his grandfather died.'\n\n"
            f"OUTPUT: Write the story as it happens, not how it feels. No formatting markers."
        )
        
        print(f"📝 Converting chunk {chunk_index + 1}/{total_chunks} to story...", flush=True)
        
        try:
            response = await self.model.generate_content_async(
                prompt,
                request_options={"timeout": 120}
            )
            
            story_text = response.text.strip()
            print(f"✅ Chunk {chunk_index + 1} converted ({len(story_text)} chars)", flush=True)
            return story_text
            
        except Exception as e:
            print(f"⚠️ Error converting chunk {chunk_index + 1}: {e}", flush=True)
            raise
    
    async def _generate_summary(self, story_text: str) -> str:
        """Generate a brief summary of the story so far for continuity."""
        prompt = (
            f"Summarize this story excerpt in 2-3 sentences. "
            f"Focus on: main characters, current situation, key events.\n\n"
            f"STORY:\n{story_text[-3000:]}\n\n"  # Last 3000 chars
            f"SUMMARY:"
        )
        
        try:
            response = await self.model.generate_content_async(
                prompt,
                request_options={"timeout": 30}
            )
            return response.text.strip()
        except Exception:
            return ""  # Non-critical, continue without summary
    
    async def create_bible(
        self,
        raw_transcript: List[dict],
        chunk_minutes: int = 15
    ) -> str:
        """
        Convert raw dialogue transcript into a complete story script ("Bible").
        
        Args:
            raw_transcript: List of transcript segments from Memories.ai
                           Format: [{"text": "...", "start": 0.0, "end": 2.5}, ...]
            chunk_minutes: Size of chunks to process (default 15 minutes)
            
        Returns:
            Complete story script text ready for TTS
        """
        if not raw_transcript:
            raise ValueError("Empty transcript provided")
        
        print(f"📖 Creating Bible from {len(raw_transcript)} transcript segments", flush=True)
        
        # Parse and chunk the transcript
        segments = self._parse_transcript(raw_transcript)
        chunks = self._chunk_transcript(segments, chunk_minutes)
        
        print(f"📦 Split into {len(chunks)} chunks (~{chunk_minutes} min each)", flush=True)
        
        # Convert each chunk to story
        story_parts = []
        previous_summary = ""
        
        for i, chunk in enumerate(chunks):
            chunk_text = self._format_chunk_for_prompt(chunk)
            
            # Convert to story
            story_part = await self._convert_chunk_to_story(
                chunk_text=chunk_text,
                chunk_index=i,
                total_chunks=len(chunks),
                previous_summary=previous_summary
            )
            
            story_parts.append(story_part)
            
            # Generate summary for next chunk's context
            if i < len(chunks) - 1:
                previous_summary = await self._generate_summary(story_part)
            
            # Rate limit between chunks
            if i < len(chunks) - 1:
                await asyncio.sleep(2)
        
        # Combine all parts
        bible_text = "\n\n".join(story_parts)
        
        print(f"📚 Bible complete: {len(bible_text)} chars, {len(bible_text.split())} words", flush=True)
        
        return bible_text
    
    async def create_bible_simple(
        self,
        raw_transcript: List[dict]
    ) -> str:
        """
        Simplified version for short videos (< 15 minutes).
        
        Processes entire transcript in one API call.
        """
        if not raw_transcript:
            raise ValueError("Empty transcript provided")
        
        # Calculate total duration
        if raw_transcript:
            total_duration = max(
                float(seg.get("end", seg.get("end_time", 0))) 
                for seg in raw_transcript
            )
        else:
            total_duration = 0
        
        # If longer than 20 minutes, use chunked version
        if total_duration > 20 * 60:
            return await self.create_bible(raw_transcript)
        
        print(f"📖 Creating Bible (simple mode) from {len(raw_transcript)} segments", flush=True)
        
        segments = self._parse_transcript(raw_transcript)
        full_text = self._format_chunk_for_prompt(segments)
        
        story = await self._convert_chunk_to_story(
            chunk_text=full_text,
            chunk_index=0,
            total_chunks=1
        )
        
        return story

    async def rewrite_chapter(
        self, 
        chapter_data: dict,
        previous_context: str = "",
        duration_seconds: float = 30.0,
        character_guide: str = "",
        plot_summary: str = "",
        dialogue_segments: Optional[List[dict]] = None,
        key_moment: Optional[dict] = None,
        speaker_mapping: Optional[dict] = None
    ) -> str:
        """
        Rewrites a single dry chapter summary into dramatic narration.
        
        Takes a chapter from Memories.ai's generate_summary endpoint and
        transforms the dry description into engaging, dramatic narration
        using the "Novelist" style with duration-aware word count.
        
        Args:
            chapter_data: Dict with 'title', 'description', 'start', 'end' fields
            previous_context: Last ~300 chars of previous narration for continuity
            duration_seconds: Target duration for this chapter (for word count calc)
            character_guide: Optional character name mapping (e.g., "Woman with powers = The Ancient One")
            plot_summary: Full plot summary for story context (who dies, major events, etc.)
            dialogue_segments: Optional list of dialogue segments with speaker labels from
                              audio transcription. Format: [{"text": "...", "speaker": "Speaker 1", "start": 0.0, "end": 2.5}]
            key_moment: Optional key moment dict for original audio insertion. Format:
                       {"start": 95.2, "end": 98.5, "speaker": "Name", "dialogue": "...", "lead_in": "..."}
                       If provided, narration will end with the lead_in and an ORIGINAL_AUDIO marker.
            speaker_mapping: Optional dict mapping generic speakers to character names.
                            Format: {"Speaker 1": "Dek", "Speaker 2": "Thea"}
                
        Returns:
            Dramatic narration text with appropriate word count for duration.
            If key_moment is provided, includes [ORIGINAL_AUDIO:start:end:speaker] marker.
        """
        title = chapter_data.get("title", "")
        # API returns "description" but we also support "summary" for compatibility
        summary = chapter_data.get("description", "") or chapter_data.get("summary", "")
        
        # If there's a key moment, reduce narration duration to make room for original audio
        original_audio_duration = 0.0
        if key_moment:
            original_audio_duration = key_moment.get("end", 0) - key_moment.get("start", 0)
            # Reduce target duration by original audio length + lead-in (~3 seconds)
            effective_duration = max(duration_seconds - original_audio_duration - 3, 10)
            print(f"🎬 Key moment detected: {original_audio_duration:.1f}s original audio, reducing narration to {effective_duration:.1f}s", flush=True)
        else:
            effective_duration = duration_seconds
        
        # Calculate target word count (avg speaking rate = 2.5 words/sec)
        target_word_count = int(effective_duration * 2.5)
        max_word_count = target_word_count + 15  # Small buffer
        
        # Build context string
        context_str = previous_context[-300:] if previous_context else "This is the opening scene."
        
        # Build character guide section if provided
        character_section = ""
        if character_guide and character_guide.strip():
            character_section = f"""
CHARACTER GUIDE (Replace generic descriptions with these names):
{character_guide.strip()}

"""
        
        # Build plot summary section if provided
        plot_section = ""
        if plot_summary and plot_summary.strip():
            # Truncate plot summary to ~2000 chars to fit in prompt
            truncated_plot = plot_summary[:2000] + "..." if len(plot_summary) > 2000 else plot_summary
            plot_section = f"""
STORY CONTEXT (Full plot summary - use this to maintain story consistency):
{truncated_plot}

IMPORTANT: Use this story context to:
- Know who is alive/dead at this point in the story
- Understand character relationships and roles
- Avoid contradictions (e.g., don't say a character is alive if they died earlier)
- Maintain plot consistency throughout the narration

"""
        
        # Build dialogue section if provided (from audio transcription with speaker recognition)
        dialogue_section = ""
        if dialogue_segments:
            # Helper to apply speaker mapping
            def map_speaker(speaker: str) -> str:
                if not speaker_mapping:
                    return speaker
                if speaker in speaker_mapping:
                    return speaker_mapping[speaker]
                # Try case-insensitive match
                for key, value in speaker_mapping.items():
                    if key.lower() == speaker.lower():
                        return value
                return speaker
            
            # Format dialogue with speaker labels (mapped to character names if available)
            dialogue_lines = []
            for seg in dialogue_segments[:20]:  # Limit to 20 segments to fit context
                speaker = seg.get("speaker", "Speaker")
                mapped_speaker = map_speaker(speaker)
                text = seg.get("text", "")
                if text.strip():
                    dialogue_lines.append(f"{mapped_speaker}: \"{text}\"")
            
            if dialogue_lines:
                dialogue_section = f"""
ACTUAL DIALOGUE (from audio transcription):
{chr(10).join(dialogue_lines)}

Use this dialogue to know exactly what characters said and incorporate it into the narration.

"""
        
        prompt = f"""You are telling a story to a friend. Transform the summary below into FLOWING STORYTELLING.

{character_section}{plot_section}{dialogue_section}

═══════════════════════════════════════════════════════════════════════════════
SUMMARY TO TRANSFORM:
{summary}
═══════════════════════════════════════════════════════════════════════════════

Write {target_word_count} words (±10%) - about {duration_seconds:.0f} seconds when spoken.

🎯 YOUR TASK: Transform the summary into STORYTELLING narration.
The summary may describe WHAT THE SCREEN SHOWS - your job is to retell it as a STORY.

═══════════════════════════════════════════════════════════════════════════════
TRANSFORMATION EXAMPLES (Study these carefully!)
═══════════════════════════════════════════════════════════════════════════════

SUMMARY: "Yuji was a regular office worker who died from overwork"
STORYTELLING: "Yuji was once a regular office worker in a company that worked him to the bone. One day, he died because of overwork."

SUMMARY: "A man in a white suit appears in the city streets"
STORYTELLING: "Shotaro Hidari walks through the city streets, his signature white suit standing out against the urban backdrop."

SUMMARY: "The monstrous creature attacks, causing destruction"
STORYTELLING: "The creature strikes without warning. Buildings crumble. People run. And in the chaos, our heroes must make a choice."

SUMMARY: "The bustling streets of Fūto City, eventually focusing on a specific address"
STORYTELLING: "In the heart of Fūto City, Tokime makes her way through the crowded streets. She's searching for something - or someone."

SUMMARY: "Shotaro and Philip are engaged in a serious conversation"
STORYTELLING: "Shotaro and Philip sit across from each other, the weight of their decision hanging in the air. Whatever they're about to do, there's no going back."

SUMMARY: "The scene plunges into a lab with red-orange light where men scatter"
STORYTELLING: "Deep inside the lab, panic erupts. Men scatter in every direction as something goes terribly wrong."

═══════════════════════════════════════════════════════════════════════════════
🚫 NEVER USE THESE (Documentary/Screenplay Language):
═══════════════════════════════════════════════════════════════════════════════
❌ "The scene shows..." / "The scene plunges into..."
❌ "We see..." / "The camera reveals..." / "The camera pans..."
❌ "The screen flickers..." / "The video opens with..."
❌ "In a dimly lit room, the man sits..." (describing what's on screen)
❌ "His face etched with concern..." (describing visuals)
❌ "The bustling streets..." (scene-setting description)
❌ "The monstrous creature appears amidst..." (documentary description)
❌ "A figure" / "Someone" / "The man" → USE CHARACTER NAMES!

═══════════════════════════════════════════════════════════════════════════════
✅ ALWAYS USE THESE (Storytelling Language):
═══════════════════════════════════════════════════════════════════════════════
✅ Start with character names: "Shotaro walks..." not "A man walks..."
✅ Active voice: "The creature attacks" not "The creature is shown attacking"
✅ Story flow: "And then..." / "But..." / "Meanwhile..." / "Little does he know..."
✅ Direct narration: "Philip realizes the truth" not "Philip is shown realizing..."
✅ Simple sentences: "He fights. He wins. He moves on."

NOW TRANSFORM THE SUMMARY INTO {target_word_count} WORDS OF STORYTELLING:
"""
        
        print(f"📝 Rewriting chapter: {title[:30]}... (target: {target_word_count} words for {duration_seconds:.0f}s)", flush=True)
        
        # Minimum acceptable word count (at least 80% of target)
        min_acceptable = int(target_word_count * 0.8)
        max_retries = 2
        last_word_count = 0  # Track word count from previous attempt
        
        for attempt in range(max_retries + 1):
            try:
                # On retry, add stronger word count emphasis
                current_prompt = prompt
                if attempt > 0 and last_word_count > 0:
                    shortfall = target_word_count - last_word_count
                    current_prompt = f"""⚠️ TOO SHORT! Add {shortfall} more words.

You wrote: {last_word_count} words. Need: {target_word_count} words.

EXPAND BY TELLING MORE OF THE STORY:
- Explain WHY characters do what they do
- Add context: "This is the moment everything changes..."
- Describe the stakes: "If he fails, everyone dies"
- Add personality: "And here's the thing..." / "But it gets worse..."

REMEMBER: Tell the story like you're explaining it to a friend - NOT describing scenes!

{prompt}"""
                
                # Use fresh model instance to avoid event loop issues in parallel execution
                model = self._get_fresh_model()
                response = await model.generate_content_async(
                    current_prompt,
                    request_options={"timeout": 90}
                )
                
                narration = response.text.strip()
                
                # Apply comprehensive cleaning
                narration = self._clean_narration_output(narration)
                
                # Additional cleanup for labels
                if narration.lower().startswith("narration:"):
                    narration = narration[10:].strip()
                if narration.lower().startswith("output:"):
                    narration = narration[7:].strip()
                
                word_count = len(narration.split())
                last_word_count = word_count  # Save for potential retry
                
                # Check if word count is acceptable
                if word_count >= min_acceptable:
                    print(f"✅ Chapter rewritten ({word_count}/{target_word_count} words, {len(narration)} chars)", flush=True)
                    # Append original audio marker if key_moment exists
                    narration = self._append_original_audio_marker(narration, key_moment)
                    return narration
                else:
                    print(f"⚠️ Narration too short ({word_count}/{target_word_count} words), attempt {attempt + 1}/{max_retries + 1}", flush=True)
                    if attempt == max_retries:
                        # Last attempt, return what we have
                        print(f"⚠️ Using short narration after {max_retries + 1} attempts", flush=True)
                        narration = self._append_original_audio_marker(narration, key_moment)
                        return narration
                    
            except Exception as e:
                error_str = str(e)
                print(f"⚠️ Error rewriting chapter (attempt {attempt + 1}): {e}", flush=True)
                
                # Check for rate limit errors (429)
                if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                    # Wait before retrying on rate limit
                    wait_time = 10 * (attempt + 1)  # 10s, 20s, 30s
                    print(f"⏳ Rate limit hit, waiting {wait_time}s before retry...", flush=True)
                    await asyncio.sleep(wait_time)
                    continue  # Retry after waiting
                
                # Check for event loop errors - try sync fallback
                if "event loop" in error_str.lower() or "closed" in error_str.lower():
                    print(f"🔄 Event loop issue, trying sync fallback...", flush=True)
                    try:
                        model = self._get_fresh_model()
                        response = model.generate_content(
                            current_prompt,
                            request_options={"timeout": 90}
                        )
                        narration = response.text.strip()
                        narration = narration.strip('"\'')
                        if narration.lower().startswith("narration:"):
                            narration = narration[10:].strip()
                        print(f"✅ Sync fallback succeeded ({len(narration.split())} words)", flush=True)
                        return self._append_original_audio_marker(narration, key_moment)
                    except Exception as sync_err:
                        print(f"⚠️ Sync fallback also failed: {sync_err}", flush=True)
                
                if attempt == max_retries:
                    # Fallback: return the original summary
                    print(f"⚠️ All attempts failed, using original summary", flush=True)
                    return self._append_original_audio_marker(summary, key_moment)
        
        # Should not reach here, but fallback just in case
        return self._append_original_audio_marker(summary, key_moment)
    
    def _append_original_audio_marker(self, narration: str, key_moment: Optional[dict]) -> str:
        """
        Append original audio marker to narration if key_moment is provided.
        
        Args:
            narration: The narration text
            key_moment: Optional key moment dict with start, end, speaker, lead_in
            
        Returns:
            Narration with lead-in and [ORIGINAL_AUDIO:start:end:speaker] marker appended,
            or unchanged narration if no key_moment.
        """
        if not key_moment:
            return narration
        
        start = key_moment.get("start", 0)
        end = key_moment.get("end", 0)
        speaker = key_moment.get("speaker", "Unknown")
        lead_in = key_moment.get("lead_in", f"And then {speaker} says...")
        
        # Clean up lead_in (remove trailing punctuation if present, we'll add our own)
        lead_in = lead_in.rstrip('.,!?:;')
        
        # Append lead-in and marker
        # Format: [ORIGINAL_AUDIO:start:end:speaker]
        marker = f"[ORIGINAL_AUDIO:{start:.2f}:{end:.2f}:{speaker}]"
        
        # Ensure narration ends with proper punctuation before lead-in
        narration = narration.rstrip()
        if narration and narration[-1] not in '.!?':
            narration += '.'
        
        # Add lead-in and marker
        result = f"{narration} {lead_in}... {marker}"
        
        print(f"🎬 Added original audio marker: {marker}", flush=True)
        return result

    async def rewrite_chapters_batch(self, chapters: List[dict]) -> List[str]:
        """
        Rewrite multiple chapters in sequence with context continuity.
        
        Args:
            chapters: List of chapter dicts from Memories.ai
            
        Returns:
            List of dramatic narration strings, one per chapter
        """
        narrations = []
        
        for i, chapter in enumerate(chapters):
            print(f"📖 Processing chapter {i+1}/{len(chapters)}", flush=True)
            narration = await self.rewrite_chapter(chapter)
            narrations.append(narration)
            
            # Small delay between API calls to avoid rate limits
            if i < len(chapters) - 1:
                await asyncio.sleep(1)
        
        return narrations

    async def rewrite_chapters_parallel(
        self,
        chapters: List[dict],
        character_guide: str = "",
        plot_summary: str = "",
        audio_transcript: Optional[List[dict]] = None,
        target_duration_seconds: Optional[float] = None,
        batch_size: int = 5,
        key_moments: Optional[List[dict]] = None,
        speaker_mapping: Optional[dict] = None
    ) -> List[str]:
        """
        Rewrite multiple chapters in PARALLEL batches for speed.
        
        Processes chapters in batches of `batch_size` concurrently,
        significantly reducing total processing time.
        
        Args:
            chapters: List of chapter dicts from Memories.ai
            character_guide: Character name mappings
            plot_summary: Full plot summary for context
            audio_transcript: Optional list of dialogue segments with speaker labels
                             Format: [{"text": "...", "speaker": "Speaker 1", "start": 0.0, "end": 2.5}]
            target_duration_seconds: If set, distribute this total duration across all chapters
                                    (overrides chapter-based duration calculation)
            batch_size: Number of chapters to process concurrently (default: 5)
            key_moments: Optional list of key moments for original audio insertion.
                        Each moment has chapter_index to map to the correct chapter.
            speaker_mapping: Optional dict mapping generic speakers to character names.
                            Format: {"Speaker 1": "Dek", "Speaker 2": "Thea"}
            
        Returns:
            List of dramatic narration strings, one per chapter (in order).
            Chapters with key_moments will include [ORIGINAL_AUDIO:...] markers.
        """
        all_narrations = []
        total_chapters = len(chapters)
        
        # Build a map of chapter_index -> key_moment for quick lookup
        key_moment_map = {}
        if key_moments:
            for moment in key_moments:
                chapter_idx = moment.get("chapter_index")
                if chapter_idx is not None and 0 <= chapter_idx < total_chapters:
                    key_moment_map[chapter_idx] = moment
            if key_moment_map:
                print(f"🎬 {len(key_moment_map)} chapters have key moments for original audio", flush=True)
        
        # Calculate duration per chapter based on target or chapter timestamps
        if target_duration_seconds and target_duration_seconds > 0:
            # Distribute target duration evenly across chapters
            # Reserve ~30 seconds for intro/outro
            available_duration = max(target_duration_seconds - 30, 60)
            duration_per_chapter = available_duration / total_chapters
            print(f"📏 Target duration mode: {target_duration_seconds:.0f}s total → {duration_per_chapter:.1f}s per chapter ({total_chapters} chapters)", flush=True)
        else:
            duration_per_chapter = None
            print(f"📏 Chapter duration mode: using video segment timestamps", flush=True)
        
        # Process in batches
        for batch_start in range(0, total_chapters, batch_size):
            batch_end = min(batch_start + batch_size, total_chapters)
            batch = chapters[batch_start:batch_end]
            
            print(f"⚡ Processing chapters {batch_start+1}-{batch_end} in parallel...", flush=True)
            
            # Create tasks for parallel execution
            tasks = []
            for i, chapter in enumerate(batch):
                chapter_idx = batch_start + i
                
                # Use parse_time to handle various timestamp formats (MM:SS, seconds, etc.)
                chapter_start = parse_time(chapter.get("start", 0))
                chapter_end = parse_time(chapter.get("end", 0))
                
                # If end time is invalid or before start, estimate based on next chapter or default
                if chapter_end <= chapter_start:
                    chapter_end = chapter_start + 60  # Default 60 seconds if parsing fails
                
                # Use target-based duration if specified, otherwise use chapter timestamps
                if duration_per_chapter:
                    duration = duration_per_chapter
                else:
                    duration = chapter_end - chapter_start
                    # Ensure minimum duration of 10 seconds
                    duration = max(duration, 10.0)
                
                # Log the duration calculation for debugging
                print(f"    Chapter {chapter_idx + 1}: video {chapter_start:.1f}s-{chapter_end:.1f}s → narration {duration:.1f}s", flush=True)
                
                # Get dialogue segments for this chapter's time range (check for overlap, not containment)
                chapter_dialogue = None
                if audio_transcript:
                    chapter_dialogue = [
                        seg for seg in audio_transcript
                        if parse_time(seg.get("start", 0)) < chapter_end and parse_time(seg.get("end", seg.get("start", 0) + 1)) > chapter_start
                    ]
                    if chapter_dialogue:
                        print(f"    💬 Chapter {chapter_idx + 1}: {len(chapter_dialogue)} dialogue segments", flush=True)
                
                # Get key moment for this chapter (if any)
                chapter_key_moment = key_moment_map.get(chapter_idx)
                if chapter_key_moment:
                    print(f"    🎬 Chapter {chapter_idx + 1} has key moment: [{chapter_key_moment.get('speaker')}] \"{chapter_key_moment.get('dialogue', '')[:30]}...\"", flush=True)
                
                # For parallel processing, we can't use previous_context
                # but we have plot_summary which provides story continuity
                task = self.rewrite_chapter(
                    chapter,
                    previous_context="",  # Can't use in parallel
                    duration_seconds=duration,
                    character_guide=character_guide,
                    plot_summary=plot_summary,
                    dialogue_segments=chapter_dialogue,
                    key_moment=chapter_key_moment,
                    speaker_mapping=speaker_mapping
                )
                tasks.append(task)
            
            # Execute batch in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle results
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    print(f"⚠️ Chapter {batch_start + i + 1} failed: {result}", flush=True)
                    # Fallback to original description
                    chapter = batch[i]
                    all_narrations.append(chapter.get("description", "") or chapter.get("summary", ""))
                else:
                    all_narrations.append(result)
            
            # Delay between batches to avoid rate limits
            if batch_end < total_chapters:
                print(f"⏳ Waiting 5s before next batch to avoid rate limits...", flush=True)
                await asyncio.sleep(5)
        
        print(f"⚡ Completed {len(all_narrations)} chapters in parallel mode", flush=True)
        return all_narrations

    async def rewrite_chapters_with_structured_data(
        self,
        chapters: List[dict],
        structured_data: dict,
        audio_transcript: Optional[List[dict]] = None,
        target_words_per_chapter: Optional[int] = None,
        batch_size: int = 10
    ) -> List[str]:
        """
        Rewrite chapters using pre-extracted structured movie data and audio transcription.
        
        This method produces FLOWING STORY NARRATION like professional movie recap channels,
        not fragmented scene descriptions.
        
        Args:
            chapters: List of chapter dicts from Memories.ai
            structured_data: Pre-extracted movie data with characters, locations, scenes
            audio_transcript: Optional list of audio transcription segments with dialogue
            target_words_per_chapter: Target word count per chapter. If None, calculated from
                                      chapter duration to match video clip length (no speedup needed)
            batch_size: Chapters per batch (default 10)
            
        Returns:
            List of narration strings, one per chapter
        """
        import json
        
        total_chapters = len(chapters)
        all_narrations = [""] * total_chapters
        
        # Helper function to parse time strings to seconds
        def parse_time_to_seconds(time_str):
            """Convert time string (MM:SS or seconds) to float seconds."""
            if isinstance(time_str, (int, float)):
                return float(time_str)
            if isinstance(time_str, str):
                if ":" in time_str:
                    parts = time_str.split(":")
                    if len(parts) == 2:
                        return float(parts[0]) * 60 + float(parts[1])
                    elif len(parts) == 3:
                        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                try:
                    return float(time_str)
                except ValueError:
                    return 0.0
            return 0.0
        
        # Clean audio transcript - filter out garbage
        def clean_dialogue_text(text: str) -> str:
            """Filter out transcription garbage from dialogue."""
            if not text:
                return ""
            
            # Remove repeated phrases like "The End, The End, The End"
            import re
            text = re.sub(r'(\b\w+\b)(\s*,?\s*\1){2,}', r'\1', text, flags=re.IGNORECASE)
            
            # Remove common transcription artifacts
            garbage_patterns = [
                r'\bThe End\b\.?',
                r'\broz\b',
                r'\bShish\b',
                r'\bOi\b\s*!?\s*',
                r'\b[А-Яа-яЁё]+\b',  # Cyrillic characters (Russian text)
                r'\[Music\]',
                r'\[Applause\]',
                r'\[Laughter\]',
                r'♪.*?♪',
                r'🎵.*?🎵',
            ]
            for pattern in garbage_patterns:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            
            # Clean up extra whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # If text is too short after cleaning, it's probably garbage
            if len(text) < 3:
                return ""
            
            return text
        
        # Get speaker mapping to convert "Speaker 1" -> actual character names
        speaker_mapping = structured_data.get("speaker_mapping", {})
        
        def apply_speaker_mapping(speaker: str) -> str:
            """Convert generic speaker labels to actual character names."""
            if not speaker_mapping:
                return speaker
            # Try exact match first
            if speaker in speaker_mapping:
                return speaker_mapping[speaker]
            # Try case-insensitive match
            speaker_lower = speaker.lower()
            for key, value in speaker_mapping.items():
                if key.lower() == speaker_lower:
                    return value
            return speaker
        
        # Build dialogue lookup by chapter (with cleaning and speaker mapping)
        chapter_dialogue = {}
        if audio_transcript:
            for ch_idx, ch in enumerate(chapters):
                ch_start = parse_time_to_seconds(ch.get("start", "0:00"))
                ch_end = parse_time_to_seconds(ch.get("end", "0:00"))
                
                dialogue_in_chapter = []
                for seg in audio_transcript:
                    seg_start = seg.get("start", 0)
                    seg_end = seg.get("end", seg_start + 1)
                    
                    if seg_start < ch_end and seg_end > ch_start:
                        cleaned_text = clean_dialogue_text(seg.get("text", ""))
                        if cleaned_text:
                            # Apply speaker mapping to get actual character name
                            original_speaker = seg.get("speaker", "Unknown")
                            mapped_speaker = apply_speaker_mapping(original_speaker)
                            
                            dialogue_in_chapter.append({
                                **seg,
                                "text": cleaned_text,
                                "speaker": mapped_speaker,
                                "original_speaker": original_speaker
                            })
                
                if dialogue_in_chapter:
                    chapter_dialogue[ch_idx + 1] = dialogue_in_chapter
        
        # Format character info with more detail
        char_info = ""
        if structured_data.get("characters"):
            char_lines = []
            for char in structured_data["characters"]:
                name = char.get("name", "Unknown")
                char_type = char.get("type", "")
                role = char.get("role", "")
                appearance = char.get("appearance", "")
                line = f"• {name}"
                if char_type:
                    line += f" ({char_type})"
                if role:
                    line += f" - {role}"
                if appearance:
                    line += f" [{appearance}]"
                char_lines.append(line)
            char_info = "\n".join(char_lines)
        
        # Format location info
        loc_info = ""
        if structured_data.get("locations"):
            loc_lines = []
            for loc in structured_data["locations"]:
                if isinstance(loc, dict):
                    name = loc.get("name", "Unknown")
                    desc = loc.get("description", "")
                    loc_lines.append(f"• {name}: {desc}" if desc else f"• {name}")
                else:
                    loc_lines.append(f"• {loc}")
            loc_info = "\n".join(loc_lines[:10])  # Limit to 10 locations
        
        # Format relationships
        rel_info = ""
        if structured_data.get("relationships"):
            rel_lines = []
            for rel in structured_data["relationships"][:10]:  # Limit to 10
                if isinstance(rel, dict):
                    char1 = rel.get("character1", rel.get("from", ""))
                    char2 = rel.get("character2", rel.get("to", ""))
                    rel_type = rel.get("type", rel.get("relationship", ""))
                    if char1 and char2:
                        rel_lines.append(f"• {char1} ↔ {char2}: {rel_type}")
                elif isinstance(rel, str):
                    rel_lines.append(f"• {rel}")
            rel_info = "\n".join(rel_lines)
        
        # Format factions/groups
        faction_info = ""
        if structured_data.get("factions"):
            faction_lines = []
            for faction in structured_data["factions"][:5]:  # Limit to 5
                if isinstance(faction, dict):
                    name = faction.get("name", "")
                    desc = faction.get("description", "")
                    members = faction.get("members", [])
                    line = f"• {name}"
                    if desc:
                        line += f": {desc}"
                    if members:
                        line += f" (Members: {', '.join(members[:5])})"
                    faction_lines.append(line)
                elif isinstance(faction, str):
                    faction_lines.append(f"• {faction}")
            faction_info = "\n".join(faction_lines)
        
        # Build scene lookup
        scene_map = {}
        if structured_data.get("scenes"):
            for scene in structured_data["scenes"]:
                ch_num = scene.get("chapter", 0)
                scene_map[ch_num] = scene
        
        # Get plot summary for context
        plot_summary = structured_data.get("plot_summary", "")
        
        # Extract character names from dialogue (catches names visual recognition might miss)
        dialogue_names = self._extract_names_from_dialogue(audio_transcript) if audio_transcript else []
        
        # Format dialogue names for prompt
        dialogue_names_info = ""
        if dialogue_names:
            dialogue_names_info = "\n".join([f"• {name}" for name in dialogue_names])
        
        print(f"🎬 Rewriting {total_chapters} chapters with STORYTELLING mode...", flush=True)
        print(f"   📋 Characters: {len(structured_data.get('characters', []))}", flush=True)
        print(f"   📍 Locations: {len(structured_data.get('locations', []))}", flush=True)
        print(f"   🤝 Relationships: {len(structured_data.get('relationships', []))}", flush=True)
        print(f"   🏛️ Factions: {len(structured_data.get('factions', []))}", flush=True)
        print(f"   🗣️ Speaker mappings: {len(speaker_mapping)}", flush=True)
        print(f"   💬 Chapters with dialogue: {len(chapter_dialogue)}", flush=True)
        print(f"   📛 Names from dialogue: {len(dialogue_names)}", flush=True)
        print(f"   🎯 Word count mode: {'fixed' if target_words_per_chapter else 'per-chapter (based on clip duration)'}", flush=True)
        
        # Process in batches
        for batch_start in range(0, total_chapters, batch_size):
            batch_end = min(batch_start + batch_size, total_chapters)
            batch_chapters = chapters[batch_start:batch_end]
            
            print(f"⚡ Processing chapters {batch_start + 1}-{batch_end}...", flush=True)
            
            # Build chapter summaries for this batch with per-chapter word targets
            chapter_entries = []
            chapter_word_targets = []  # Track word targets for each chapter
            
            for i, ch in enumerate(batch_chapters):
                ch_num = batch_start + i + 1
                summary = ch.get("description", "") or ch.get("summary", "")
                
                # Clean summary of garbage
                summary = clean_dialogue_text(summary)
                
                # Calculate word target based on ACTUAL clip duration
                # This ensures narration audio matches video length = no speedup needed
                if target_words_per_chapter:
                    words_target = target_words_per_chapter
                else:
                    # Use chapter's actual video duration
                    ch_start = parse_time_to_seconds(ch.get("start", 0))
                    ch_end = parse_time_to_seconds(ch.get("end", 0))
                    ch_duration = max(ch_end - ch_start, 30)  # Minimum 30 seconds
                    # TTS speaks at ~2.5 words/sec at normal (1.0x) speed
                    # Request 2.5 words/sec to match video duration
                    words_target = int(ch_duration * 2.5)  # 2.5 words/sec (standard speaking rate)
                
                
                chapter_word_targets.append(words_target)
                
                # Get scene context
                scene = scene_map.get(ch_num, {})
                chars_present = scene.get("characters_present", [])
                location = scene.get("location", "")
                
                # Build natural continuation from previous scenes using ContinuousNarrator
                continuation = ""
                if ch_num > 1 and self.narrator.story_context:
                    # Get previous narrations for context
                    prev_narrations = list(self.narrator.story_context)
                    if prev_narrations:
                        continuation = self.narrator.build_continuation(chars_present)
                
                # Get clean dialogue with speaker names
                dialogue_lines = []
                if ch_num in chapter_dialogue:
                    for seg in chapter_dialogue[ch_num][:5]:
                        text = seg.get("text", "")
                        speaker = seg.get("speaker", "Unknown")
                        if text and len(text) > 5:
                            # Include speaker name with dialogue
                            dialogue_lines.append(f'{speaker}: "{text}"')
                
                # Include word target in the entry so AI knows how long to write
                entry = f"SECTION {ch_num} [TARGET: {words_target} words]: {summary}"
                if continuation:
                    entry = f"{continuation}{entry}"  # Add continuation at the start
                if location:
                    entry += f"\nLocation: {location}"
                if chars_present:
                    entry += f"\nCharacters present: {', '.join(chars_present)}"
                if dialogue_lines:
                    entry += f"\nDialogue:\n  " + "\n  ".join(dialogue_lines)
                
                chapter_entries.append(entry)
            
            chapters_text = "\n\n".join(chapter_entries)
            
            # Calculate video duration for temporal context
            video_duration = 0.0
            if chapters:
                last_chapter = chapters[-1]
                video_duration = parse_time_to_seconds(last_chapter.get("end", 0))
            
            # Add temporal context to each chapter entry
            temporal_contexts = []
            for i, ch in enumerate(batch_chapters):
                ch_num = batch_start + i + 1
                ch_start = parse_time_to_seconds(ch.get("start", 0))
                if video_duration > 0:
                    # Import add_temporal_context from gemini_client
                    from app.services.gemini_client import GeminiClient
                    gemini_client = GeminiClient()
                    temp_context = gemini_client.add_temporal_context(ch_start, video_duration)
                    temporal_contexts.append(temp_context)
                else:
                    temporal_contexts.append("")
            
            # Determine story position using story structure labels
            story_phases = []
            for i in range(batch_start, batch_end):
                ch_num = i + 1
                phase = get_script_label(ch_num, total_chapters)
                phase_desc = STORY_STRUCTURE_LABELS.get(phase, phase)
                if phase_desc not in story_phases:
                    story_phases.append(phase_desc)
            
            if len(story_phases) == 1:
                story_position = f"{story_phases[0].upper()}"
            else:
                story_position = f"{' / '.join(story_phases).upper()}"
            
            # Add detailed context based on story phase
            phase_context = ""
            for i in range(batch_start, batch_end):
                ch_num = i + 1
                phase = get_script_label(ch_num, total_chapters)
                if phase == "intro" and not phase_context:
                    phase_context = "Focus on character introduction and premise establishment."
                elif phase == "conflict" and not phase_context:
                    phase_context = "Establish the initial conflict or goal that drives the story."
                elif phase == "rising" and not phase_context:
                    phase_context = "Build tension and escalate complications."
                elif phase == "climax" and not phase_context:
                    phase_context = "Reach the major confrontation or decision point."
                elif phase == "resolution" and not phase_context:
                    phase_context = "Show consequences and wrap up the story."
            
            if phase_context:
                story_position += f" - {phase_context}"
            
            # Build context sections
            context_parts = []
            
            if char_info:
                context_parts.append(f"CHARACTERS (USE THESE NAMES, not 'the youth' or 'a man'):\n{char_info}")
            
            # Add names extracted from dialogue (critical for sci-fi where visual recognition fails)
            if dialogue_names_info:
                context_parts.append(f"NAMES MENTIONED IN DIALOGUE (use these instead of 'a figure' or 'someone'):\n{dialogue_names_info}")
            
            if loc_info:
                context_parts.append(f"LOCATIONS:\n{loc_info}")
            
            if rel_info:
                context_parts.append(f"RELATIONSHIPS:\n{rel_info}")
            
            if faction_info:
                context_parts.append(f"FACTIONS/GROUPS:\n{faction_info}")
            
            context_section = "\n\n".join(context_parts) if context_parts else "Use names from the plot sections below"
            
            prompt = f"""REWRITE these plot summaries as STORYTELLING NARRATION for a YouTube recap.

⚠️ CRITICAL: The input summaries describe what's ON SCREEN. You must REWRITE them as STORY.

WRONG (copying the input): "A man in a white suit stands in the city, his face etched with concern."
RIGHT (storytelling): "Shotaro knows something is wrong. He can feel it in his bones."

WRONG (visual description): "The woman falls, her hand pressing against the ground."
RIGHT (storytelling): "She hits the ground hard. But she's not giving up. Not yet."

WRONG (scene description): "The scene shifts to a dark laboratory where men scatter in panic."
RIGHT (storytelling): "Meanwhile, in the lab, all hell breaks loose. Everyone runs."

{context_section}

STORY POSITION: {story_position}
SECTIONS {batch_start + 1}-{batch_end} of {total_chapters}:
{f"TEMPORAL CONTEXT: {', '.join([tc for tc in temporal_contexts if tc])}" if any(temporal_contexts) else ""}

{chapters_text}

═══════════════════════════════════════════════════════════════════════════════
🎯 REWRITE RULES - Follow these EXACTLY:
═══════════════════════════════════════════════════════════════════════════════

1. NEVER COPY VISUAL DESCRIPTIONS FROM THE INPUT
   - Input says "his face etched with concern" → Write "He's worried"
   - Input says "her knuckles white" → Write "She grips tighter"
   - Input says "their expressions suggesting" → Write what they FEEL, not what they LOOK like

2. USE CHARACTER NAMES, NOT DESCRIPTIONS
   - "A man in white" → "Shotaro"
   - "The woman" → Use her name from context
   - "A figure" → Use the character's name
   - "Someone" → Use a specific name

3. WRITE LIKE YOU'RE TELLING A FRIEND THE PLOT
   - "So basically, Shotaro gets this phone call, right? And it's bad news."
   - "Meanwhile, Philip figures out something huge."
   - "And then the monster shows up. Things get crazy."

4. USE SHORT, PUNCHY SENTENCES
   - "He fights. He wins. But at what cost?"
   - "The creature attacks. Shotaro barely dodges."
   - "It's over. Or so they think."

═══════════════════════════════════════════════════════════════════════════════
🚫 BANNED PHRASES (If you use these, the output is WRONG):
═══════════════════════════════════════════════════════════════════════════════
- "face etched with" / "expression suggesting" / "eyes reflecting"
- "knuckles white" / "hand pressing" / "fingers gripping"  
- "the scene" / "the camera" / "the screen" / "the frame"
- "we see" / "is shown" / "is revealed" / "appears"
- "amidst" / "amongst" / "overlooking"
- "a figure" / "someone" / "a man in" / "a woman in"
- "sprawling" / "bustling" / "dimly lit" / "sickly green"
- "their faces" / "his face" / "her face" + any visual description

═══════════════════════════════════════════════════════════════════════════════
✅ GOOD STORYTELLING PATTERNS:
═══════════════════════════════════════════════════════════════════════════════
- "Shotaro knows what he has to do."
- "Philip has a plan. A dangerous one."
- "The monster attacks without warning."
- "Everything changes in an instant."
- "This is it. The final battle."
- "She makes a choice that will haunt her forever."
- "He fights back. Hard."
- "But it's not over yet."

Each section needs [TARGET: X words]. Hit that count by EXPANDING THE STORY, not by adding visual descriptions.

FORMAT: Return a JSON array with one narration string per section.
Return ONLY a JSON array of strings. No markdown, no ```json, just the raw array."""

            try:
                model = self._get_fresh_model()

                response = await model.generate_content_async(
                    prompt,
                    request_options={"timeout": 120}
                )
                
                content = response.text.strip()
                
                # Strip markdown code fences if the model wraps JSON in ```json ... ```
                # (common behavior even when instructed not to)
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*\s*", "", content).strip()
                    content = re.sub(r"\s*```$", "", content).strip()
                
                # Parse JSON array from response
                narrations = []
                if "[" in content and "]" in content:
                    start_idx = content.find("[")
                    end_idx = content.rfind("]") + 1
                    json_str = content[start_idx:end_idx]
                    try:
                        narrations = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try to extract individual strings
                        pass
                
                # If JSON parsing failed, try line-by-line
                if not narrations:
                    # Split by chapter markers or double newlines
                    lines = content.split("\n\n")
                    for line in lines:
                        line = line.strip().strip('"\'')
                        if line and len(line) > 20:
                            narrations.append(line)
                
                # Store results and update narrator memory
                for i, narration in enumerate(narrations):
                    if batch_start + i < total_chapters:
                        raw_narr = str(narration)
                        # Clean up narration with comprehensive filtering
                        narration = self._clean_narration_output(raw_narr)
                        all_narrations[batch_start + i] = narration
                        
                        # Update narrator memory for continuity
                        ch_num = batch_start + i + 1
                        ch = batch_chapters[i] if i < len(batch_chapters) else None
                        if ch:
                            # Extract characters from chapter for continuity tracking
                            scene = scene_map.get(ch_num, {})
                            chars_present = scene.get("characters_present", [])
                            self.narrator.update_memory(narration, chars_present)
                
                success_count = sum(1 for n in narrations if n and len(str(n).split()) > 10)
                print(f"   ✅ Batch complete: {success_count}/{len(batch_chapters)} good narrations", flush=True)
                
            except Exception as e:
                print(f"   ❌ Batch failed: {e}", flush=True)
                # Fallback to summaries
                for i, ch in enumerate(batch_chapters):
                    if batch_start + i < total_chapters and not all_narrations[batch_start + i]:
                        all_narrations[batch_start + i] = ch.get("description", "") or ch.get("summary", "")
            
            # Delay between batches
            if batch_end < total_chapters:
                await asyncio.sleep(2)
        
        # Fill any empty narrations with summaries
        for i, narration in enumerate(all_narrations):
            if not narration or len(narration.split()) < 5:
                all_narrations[i] = chapters[i].get("description", "") or chapters[i].get("summary", "")
        
        good_count = sum(1 for n in all_narrations if n and len(n.split()) > 10)
        print(f"✅ Gemini narration complete: {good_count}/{total_chapters} chapters", flush=True)
        
        return all_narrations

    async def generate_intro(
        self,
        plot_summary: str,
        character_guide: str = "",
        video_title: str = ""
    ) -> str:
        """
        Generate an engaging intro for the video recap.
        
        Uses AI to create a hook based on the plot summary that draws
        viewers in and sets up the story.
        
        Args:
            plot_summary: Full plot summary from Memories.ai
            character_guide: Character name mappings
            video_title: Optional title of the movie/anime
            
        Returns:
            Intro narration text (10-20 seconds worth, ~25-50 words)
        """
        # Extract key info for the intro
        title_info = f"TITLE: {video_title}\n" if video_title else ""
        char_info = f"MAIN CHARACTERS: {character_guide[:500]}\n" if character_guide else ""
        
        prompt = f"""You are a straightforward narrator. Write a brief intro (20-30 words) that states the premise.

{title_info}{char_info}
STORY PREMISE:
{plot_summary[:1500]}

REQUIREMENTS:
- EXACTLY 20-30 words (about 8-12 seconds when spoken)
- STATE THE PREMISE in 1-2 sentences
- NO questions, NO "hooks", NO drama
- Present tense
- Direct language only
- NO "Some stories are meant to be told", NO "In a world where..."

EXAMPLES:

"Jujutsu Kaisen follows Yuji Itadori, a student who eats a cursed object and joins a school of sorcerers fighting curses."

"This is the story of Tanjiro Kamado. His family is killed by demons. He becomes a demon slayer to save his sister."

"Naruto Uzumaki is a ninja with a demon sealed inside him. He wants to become the leader of his village."

Write the intro now. Output ONLY the narration, nothing else.
"""
        
        print(f"🎬 Generating intro...", flush=True)
        
        try:
            response = await self.model.generate_content_async(
                prompt,
                request_options={"timeout": 30}
            )
            
            intro = response.text.strip().strip('"\'')
            word_count = len(intro.split())
            print(f"✅ Intro generated ({word_count} words): {intro[:60]}...", flush=True)
            return intro
            
        except Exception as e:
            print(f"⚠️ Error generating intro: {e}", flush=True)
            # Fallback intro - direct and simple
            return "This is a story you need to hear. Here is what happens."

    def generate_outro(
        self,
        video_title: str = "",
        include_cta: bool = True
    ) -> str:
        """
        Generate a dramatic outro for the video.
        
        Uses pre-written templates with dramatic flair.
        Randomized to be different every time.
        
        Args:
            video_title: Optional title of the movie/anime
            include_cta: Include call-to-action (like/subscribe)
            
        Returns:
            Outro narration text (10-15 seconds worth, ~25-40 words)
        """
        import random
        
        # Dramatic endings that match the storytelling tone (expanded for variety)
        endings = [
            "And so it ends. But the echoes of this story will linger long after the credits roll.",
            "The road ends here. But the journey... the journey stays with us forever.",
            "And when the dust settles, only one question remains: was it worth it?",
            "The final step. The last breath. And a legacy that will never be forgotten.",
            "This is how it ends. Not with answers, but with silence.",
            "The curtain falls. But the story... the story never truly ends.",
            "And just like that, it's over. But nothing will ever be the same.",
            "The final chapter closes. What remains is memory.",
            "Every ending is a new beginning. This one is no different.",
            "And so the credits roll. But the questions remain.",
            "This is where the story ends. For now.",
            "The dust settles. The silence speaks louder than words ever could.",
            "And with that, the tale reaches its end. But legends never die.",
            "The final frame. The last word. And a story that will echo through time.",
            "It ends as it began. With fire. With blood. With truth.",
        ]
        
        # Reflections that feel earned (expanded for variety)
        reflections = [
            "A story of survival, sacrifice, and the darkness that lives in all of us.",
            "Not everyone makes it to the end. But those who do are never the same.",
            "In the end, it was never about winning. It was about what we're willing to lose.",
            "Some journeys change you. This one... this one breaks you.",
            "Heroes fall. Villains rise. And the line between them blurs.",
            "What we fight for defines us. What we sacrifice... that's what makes us human.",
            "The price of victory is always higher than we expect.",
            "In every ending, there's a lesson. In every loss, a truth.",
            "We came for the story. We stayed for the characters. We left... changed.",
            "Not all heroes wear capes. Some just survive.",
            "The greatest battles are fought within. This one proved it.",
            "Love, loss, and everything in between. That's what this story was about.",
            "Sometimes the monster wins. Sometimes the hero falls. That's life.",
            "We don't choose our battles. But we choose how we fight them.",
        ]
        
        # CTAs that don't break the mood (expanded for variety)
        ctas = [
            "If this story moved you, leave a like. If you want more, subscribe.",
            "Hit subscribe for more stories that stay with you.",
            "Like and subscribe if you felt something. That's all I ask.",
            "Subscribe for more tales of triumph and tragedy.",
            "Drop a like if this hit different. Subscribe for more.",
            "If you made it this far, you're one of us. Subscribe.",
            "Smash that like button. Join the journey. Subscribe.",
            "One like. One subscribe. That's how you support the story.",
            "If this story deserves to be told, help it reach more people. Like and subscribe.",
            "Your support keeps these stories alive. Like. Subscribe. Share.",
            "Want more stories like this? You know what to do.",
            "If you felt something, let me know. Like, comment, subscribe.",
        ]
        
        thanks = [
            "Until next time.",
            "See you in the next one.",
            "Thanks for being here.",
            "Until we meet again.",
            "Stay legendary.",
            "Peace.",
            "Catch you later.",
            "This has been your story. Thanks for watching.",
            "Take care of yourselves.",
            "See you on the other side.",
            "Until the next chapter.",
            "Keep watching. Keep feeling. Keep living.",
        ]
        
        # Build outro with randomized structure
        parts = []
        
        # Randomly decide structure (adds more variety)
        structure = random.choice([
            'ending_reflection_cta_thanks',
            'ending_cta_thanks',
            'reflection_ending_cta_thanks',
            'ending_reflection_thanks',
        ])
        
        if structure == 'ending_reflection_cta_thanks':
            parts.append(random.choice(endings))
            parts.append(random.choice(reflections))
            if include_cta:
                parts.append(random.choice(ctas))
            parts.append(random.choice(thanks))
        elif structure == 'ending_cta_thanks':
            parts.append(random.choice(endings))
            if include_cta:
                parts.append(random.choice(ctas))
            parts.append(random.choice(thanks))
        elif structure == 'reflection_ending_cta_thanks':
            parts.append(random.choice(reflections))
            parts.append(random.choice(endings))
            if include_cta:
                parts.append(random.choice(ctas))
            parts.append(random.choice(thanks))
        else:  # ending_reflection_thanks
            parts.append(random.choice(endings))
            parts.append(random.choice(reflections))
            parts.append(random.choice(thanks))
        
        outro = " ".join(parts)
        print(f"🎬 Generated outro ({len(outro.split())} words)", flush=True)
        
        return outro

