"""
Google Gemini API Client for video understanding.

Replaces Memories.ai with Gemini 1.5 Pro for video analysis.
Supports chunking for videos longer than 1 hour.
"""

import asyncio
import os
import time
from collections import deque
from typing import Optional, List, Tuple, Dict
from pathlib import Path

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from app.config import get_settings


class ContinuousNarrator:
    """
    Manages story context and character continuity for natural scene transitions.
    
    Based on research-backed memory consolidation techniques for narrative flow.
    """
    
    def __init__(self, max_context_length: int = 3):
        self.story_context = deque(maxlen=max_context_length)  # Last N scenes
        self.character_states: Dict[str, str] = {}  # Track character changes
    
    def create_memory_tokens(self, previous_scenes: List[str]) -> str:
        """
        Create condensed memory tokens from previous scenes for continuity.
        
        Args:
            previous_scenes: List of previous narration strings
            
        Returns:
            Condensed summary string for prompt context
        """
        if not previous_scenes:
            return ""
        
        # Take last 3 scenes and condense to key points
        recent = previous_scenes[-3:] if len(previous_scenes) >= 3 else previous_scenes
        
        # Extract key information: characters mentioned, main actions
        summary_parts = []
        for scene in recent:
            # Simple extraction: first sentence or first 50 chars
            first_sent = scene.split('.')[0] if '.' in scene else scene[:50]
            summary_parts.append(first_sent.strip())
        
        return " | ".join(summary_parts)
    
    def update_memory(self, narration: str, characters: List[str] = None):
        """
        Update memory with new scene narration.
        
        Args:
            narration: Generated narration for current scene
            characters: Optional list of character names in this scene
        """
        self.story_context.append(narration)
        
        if characters:
            for char in characters:
                # Track that character appeared in this scene
                self.character_states[char] = narration[:100]  # Store snippet
    
    def build_continuation(self, new_scene_characters: List[str]) -> str:
        """
        Build natural continuation from previous state.
        
        Args:
            new_scene_characters: Characters in the new scene
            
        Returns:
            Transition text or empty string
        """
        if not self.story_context:
            return ""
        
        # Check for character continuity
        context = []
        for prev_narration in self.story_context:
            for character in new_scene_characters:
                if character in prev_narration:
                    # Character appeared before - natural continuation
                    context.append(f"{character} continues")
        
        # Build smooth transition
        if context:
            transition = " and ".join(context[:2])  # Max 2 characters
            return f"Meanwhile, {transition}. "
        
        return ""
    
    def get_character_change(self, character: str) -> str:
        """Get description of character's state change."""
        if character in self.character_states:
            return f"{character} moves forward"
        return ""
    
    def get_simple_transition(self, scene_type: str = "action") -> str:
        """Get simple transition word based on scene type."""
        transitions = {
            "action": "Next",
            "dialogue": "Then",
            "transition": "Meanwhile"
        }
        return transitions.get(scene_type, "Next")


class GeminiClient:
    """
    Client for interacting with Google Gemini API for video understanding.
    
    Handles video upload, processing, and scene description generation.
    Uses Gemini 1.5 Pro with 2M token context window.
    """
    
    def __init__(self):
        self.settings = get_settings()
        
        # Configure the API
        genai.configure(api_key=self.settings.gemini.api_key)
        
        # Use Gemini 2.0 Flash for video understanding
        # Flash model has much higher rate limits on free tier (15+ RPM vs 2 RPM for Pro)
        # Still capable for video analysis, just slightly less detailed than Pro
        # Upgrade to paid tier to use gemini-2.5-pro for better accuracy
        self.model = genai.GenerativeModel(
            'gemini-2.0-flash',
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        # Track uploaded files for cleanup
        self._uploaded_files = {}
        
        # Initialize continuous narrator for story flow
        self.narrator = ContinuousNarrator(max_context_length=3)
    
    async def upload_video(self, file_path: str) -> str:
        """
        Upload a video file to Gemini Files API.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            File URI for use in prompts
        """
        print(f"📤 Uploading video to Gemini: {file_path}", flush=True)
        
        # Upload the file
        video_file = genai.upload_file(path=file_path)
        
        print(f"⏳ Waiting for Gemini to process video...", flush=True)
        
        # Wait for processing to complete
        while video_file.state.name == "PROCESSING":
            await asyncio.sleep(10)
            video_file = genai.get_file(video_file.name)
            print(f"   Status: {video_file.state.name}", flush=True)
        
        if video_file.state.name == "FAILED":
            raise Exception(f"Video processing failed: {video_file.state.name}")
        
        print(f"✅ Video uploaded: {video_file.uri}", flush=True)
        
        # Track for cleanup
        self._uploaded_files[file_path] = video_file.name
        
        return video_file.uri
    
    async def get_chunk_summary(
        self, 
        video_uri: str,
        chunk_index: int = 0,
        total_chunks: int = 1
    ) -> str:
        """
        Get a comprehensive summary of a video chunk.
        
        Args:
            video_uri: Gemini file URI
            chunk_index: Index of this chunk (0-based)
            total_chunks: Total number of chunks
            
        Returns:
            Detailed story summary of the chunk
        """
        print(f"📖 Generating summary for chunk {chunk_index + 1}/{total_chunks}...", flush=True)
        
        prompt = f"""You are analyzing video chunk {chunk_index + 1} of {total_chunks}.

Watch this entire video segment and provide a detailed summary including:

1. CHARACTERS: List all characters with their names (if mentioned) and descriptions
2. PLOT: What happens in this segment? Describe the key events in order
3. SETTING: Where does this take place?
4. MOOD: What is the emotional tone?
5. KEY MOMENTS: List 5-10 important moments with approximate timestamps

This summary will be used to generate narration for individual scenes, so be thorough.

Output your summary in a clear, organized format."""

        try:
            response = await self.model.generate_content_async(
                [video_uri, prompt],
                request_options={"timeout": 300}
            )
            
            summary = response.text
            print(f"✅ Summary generated ({len(summary)} chars)", flush=True)
            return summary
            
        except Exception as e:
            print(f"❌ Summary generation failed: {e}", flush=True)
            raise
    
    async def get_full_story_summary(self, video_uri: str) -> str:
        """
        Get a comprehensive story summary for the entire video.
        Alias for get_chunk_summary with single chunk.
        
        Args:
            video_uri: Gemini file URI
            
        Returns:
            Detailed story summary
        """
        return await self.get_chunk_summary(video_uri, 0, 1)
    
    def add_temporal_context(self, start_time: float, video_duration: float) -> str:
        """
        Add chronological position encoding for better narrative flow.
        
        Args:
            start_time: Start time of current scene in seconds
            video_duration: Total video duration in seconds
            
        Returns:
            Temporal context string
        """
        if video_duration <= 0:
            return ""
        
        video_position_percent = (start_time / video_duration) * 100
        
        if video_position_percent < 20:
            time_context = "Opening scenes"
        elif video_position_percent < 50:
            time_context = "Middle section"
        elif video_position_percent < 80:
            time_context = "Building toward climax"
        else:
            time_context = "Final resolution"
        
        return f"[{time_context} at {video_position_percent:.0f}%] "
    
    async def describe_scene(
        self,
        video_uri: str,
        start_time: float,
        end_time: float,
        story_context: str = "",
        previous_narration: str = "",
        max_retries: int = 3
    ) -> str:
        """
        Get narration for a specific timestamp range.
        
        Args:
            video_uri: Gemini file URI
            start_time: Start time in seconds
            end_time: End time in seconds
            story_context: Overall story context
            previous_narration: Previous scene's narration for continuity
            max_retries: Number of retry attempts
            
        Returns:
            Narration text for the scene
        """
        duration = end_time - start_time
        word_limit = max(10, int(duration * 2.5))
        
        # Build context - 2000 chars for story bible access
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        prev_info = ""
        if previous_narration:
            prev_info = f"PREVIOUS LINE: \"{previous_narration}\"\n\n"
        
        # Chronological factual narrator prompt - natural storytelling style
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Convert scene descriptions into continuous story flow.\n\n"
            f"{context_info}"
            f"{prev_info}"
            f"SCENE: {start_time:.1f}s - {end_time:.1f}s (Max {word_limit} words)\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought' or 'Yuji is fighting'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined', 'feels the weight'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence they appear in video\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character', 'a person'\n"
            f"7. TIME MARKERS: Use exact timestamps for major scene changes (e.g., 'At minute 12')\n"
            f"8. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone' or 'he sees looking upset'\n"
            f"9. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context. Say what it is.\n\n"
            f"EXAMPLE TRANSFORMATIONS:\n"
            f"❌ BAD: 'Realizing the gravity of the situation, Yuji suddenly decides...'\n"
            f"✅ GOOD: 'Yuji decides to fight the curse at minute 12.'\n"
            f"\n❌ BAD: 'The young man is caught off guard by a shocking discovery...'\n"
            f"✅ GOOD: 'Yuji finds out his grandfather died at minute 8.'\n"
            f"\n❌ BAD: 'With determination burning in his eyes, he prepares for battle...'\n"
            f"✅ GOOD: 'Yuji prepares his magic for the upcoming fight at minute 15.'\n\n"
            f"OUTPUT: Write the story as it happens, not how it feels. No quotes, no labels."
        )
        
        print(f"📝 Requesting narration: {start_time:.1f}s-{end_time:.1f}s, max {word_limit} words", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    [video_uri, prompt],
                    request_options={"timeout": 90}
                )
                
                narration = response.text.strip()
                
                if narration:
                    return narration
                
                print(f"⚠️ Empty response, retrying...", flush=True)
                
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        # Fail fast instead of returning placeholder
        raise Exception(f"Scene narration failed after {max_retries} retries: {last_error}")
    
    async def describe_scene_batch(
        self,
        video_uri: str,
        batch_segments: List[Tuple[float, float]],
        story_context: str = "",
        max_retries: int = 3
    ) -> List[str]:
        """
        Get narrations for multiple segments in a single API call.
        
        Args:
            video_uri: Gemini file URI
            batch_segments: List of (start_time, end_time) tuples
            story_context: Overall story context
            max_retries: Number of retry attempts
            
        Returns:
            List of narration strings
        """
        # Calculate average word limit
        total_duration = sum(end - start for start, end in batch_segments)
        avg_word_limit = max(10, int((total_duration / len(batch_segments)) * 2.5))
        
        # Build segment text
        segment_text = "\n".join([
            f"Segment {i+1}: {start:.1f}s to {end:.1f}s ({end-start:.1f}s)"
            for i, (start, end) in enumerate(batch_segments)
        ])
        
        # Build context - 2000 chars for story bible access
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        # Chronological factual narrator prompt for batch
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Convert scene descriptions into continuous story flow.\n\n"
            f"{context_info}"
            f"SCENES to narrate:\n{segment_text}\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence they appear in video\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character'\n"
            f"7. TIME MARKERS: Use exact timestamps for major scene changes\n"
            f"8. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone'\n"
            f"9. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context\n"
            f"10. ~{avg_word_limit} words per segment.\n\n"
            f"❌ BAD: 'Realizing the gravity of the situation, Yuji suddenly decides...'\n"
            f"✅ GOOD: 'Yuji decides to fight the curse at minute 12.'\n\n"
            f"Return a JSON array with one narration string per segment:\n"
            f"[\"narration 1\", \"narration 2\", ...]\n\n"
            f"JSON array:"
        )
        
        print(f"📦 Batch request: {len(batch_segments)} segments", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    [video_uri, prompt],
                    request_options={"timeout": 120}
                )
                
                raw_response = response.text
                narrations = self._parse_batch_response(raw_response, len(batch_segments))
                
                print(f"✅ Batch success: got {len(narrations)} narrations", flush=True)
                return narrations
                
            except Exception as e:
                print(f"⚠️ Batch error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        raise Exception(f"Batch narration failed after {max_retries} retries: {last_error}")
    
    async def write_narration_from_facts(
        self,
        visual_facts: str,
        story_context: str = "",
        previous_narration: str = "",
        duration: float = 7.0,
        max_retries: int = 3
    ) -> str:
        """
        Transform raw visual facts into dramatic Anime Recap narration.
        
        This is a TEXT-ONLY method - no video needed. Gemini acts purely as
        a creative writer, transforming factual descriptions into storytelling.
        
        Args:
            visual_facts: Raw visual description from Memories.ai
            story_context: Overall story context for character names and plot
            previous_narration: Previous scene's narration for continuity
            duration: Scene duration in seconds (for word limit calculation)
            max_retries: Number of retry attempts
            
        Returns:
            Dramatic narration text
        """
        word_limit = max(10, int(duration * 2.5))
        
        # Build context
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        prev_info = ""
        if previous_narration:
            prev_info = f"PREVIOUS LINE: \"{previous_narration}\"\n\n"
        
        # Chronological factual narrator prompt - transforms facts into chronological narration
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Transform visual facts into continuous story flow.\n\n"
            f"{context_info}"
            f"{prev_info}"
            f"VISUAL FACTS (what happens in this scene):\n{visual_facts}\n\n"
            f"TASK: Transform the VISUAL FACTS into a chronological {word_limit}-word narration.\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character'\n"
            f"7. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone'\n"
            f"8. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context\n\n"
            f"❌ BAD: 'A classmate walks up. Someone is talking.'\n"
            f"✅ GOOD: 'A classmate walks up to Akira. Akira looks up from his book.'\n\n"
            f"OUTPUT: Write the story as it happens, not how it feels. No quotes, no labels, no explanations."
        )
        
        print(f"✍️ Writing narration from facts ({len(visual_facts)} chars) -> ~{word_limit} words", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    prompt,  # Text-only, no video
                    request_options={"timeout": 60}
                )
                
                narration = response.text.strip()
                
                if narration:
                    return narration
                
                print(f"⚠️ Empty response, retrying...", flush=True)
                
            except Exception as e:
                print(f"⚠️ Error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        raise Exception(f"Narration writing failed after {max_retries} retries: {last_error}")
    
    async def write_narration_from_facts_batch(
        self,
        visual_facts_list: List[str],
        story_context: str = "",
        durations: Optional[List[float]] = None,
        max_retries: int = 3
    ) -> List[str]:
        """
        Transform multiple visual facts into narrations in ONE API call.
        
        Batch version for efficiency - reduces API calls by ~90%.
        
        Args:
            visual_facts_list: List of raw visual descriptions
            story_context: Overall story context
            durations: List of scene durations (for word limits)
            max_retries: Number of retry attempts
            
        Returns:
            List of narration strings
        """
        if not durations:
            durations = [7.0] * len(visual_facts_list)
        
        # Calculate word limits
        word_limits = [max(10, int(d * 2.5)) for d in durations]
        avg_word_limit = sum(word_limits) // len(word_limits)
        
        # Build facts text
        facts_text = "\n\n".join([
            f"Scene {i+1} (max {word_limits[i]} words):\n{facts}"
            for i, facts in enumerate(visual_facts_list)
        ])
        
        # Build context
        context_info = ""
        if story_context:
            context_info = f"STORY CONTEXT:\n{story_context[:2000]}\n\n"
        
        # Batch prompt - chronological factual style
        prompt = (
            f"ROLE: You are a factual anime recap narrator. Report what happens chronologically.\n\n"
            f"OBJECTIVE: Transform visual facts into continuous story flow.\n\n"
            f"{context_info}"
            f"VISUAL FACTS for each scene:\n{facts_text}\n\n"
            f"TASK: Transform each scene's VISUAL FACTS into chronological narration.\n\n"
            f"STYLE RULES:\n"
            f"1. PRESENT TENSE ONLY: 'Yuji fights' not 'Yuji fought'\n"
            f"2. SIMPLE SENTENCES: Subject + Verb + Object. Max 2 clauses per sentence.\n"
            f"3. NO EMOTION WORDS: Never use 'shocked', 'suddenly', 'realizing', 'determined'\n"
            f"4. NO TRANSITIONS: Don't start with 'However', 'Meanwhile', 'Suddenly', 'Realizing'\n"
            f"5. CHRONOLOGICAL ORDER: Events must happen in sequence\n"
            f"6. CHARACTER NAMES: Use full names at first mention, then first names only. NEVER say 'someone', 'they', 'a character'\n"
            f"7. BE SPECIFIC: Say 'Shotaro sees Tokime' not 'Shotaro sees someone'\n"
            f"8. NO VAGUE WORDS: Don't say 'something', 'things', 'it' without context\n"
            f"9. ~{avg_word_limit} words per scene.\n\n"
            f"Return a JSON array with one narration string per scene:\n"
            f"[\"narration 1\", \"narration 2\", ...]\n\n"
            f"JSON array:"
        )
        
        print(f"✍️ Batch narration: {len(visual_facts_list)} scenes", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    prompt,  # Text-only
                    request_options={"timeout": 120}
                )
                
                raw_response = response.text.strip()
                narrations = self._parse_batch_response(raw_response, len(visual_facts_list))
                
                print(f"✅ Batch narration success: {len(narrations)} narrations", flush=True)
                return narrations
                
            except Exception as e:
                print(f"⚠️ Batch error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        raise Exception(f"Batch narration writing failed after {max_retries} retries: {last_error}")
    
    async def anchor_to_script(
        self,
        visual_facts: str,
        script_text: str,
        scene_index: int,
        total_scenes: int,
        max_retries: int = 3
    ) -> str:
        """
        Find the exact script sentence that matches this visual scene.
        
        The "Anchor Method" - instead of inventing narration, we find the
        matching sentence in the user's pre-written script.
        
        Args:
            visual_facts: Raw visual description from Memories.ai
            script_text: The full narration script uploaded by the user
            scene_index: Which scene this is (0-based)
            total_scenes: Total number of scenes
            max_retries: Number of retry attempts
            
        Returns:
            The matching sentence from the script
        """
        # Calculate approximate position to help AI find the right section
        position_pct = int((scene_index / total_scenes) * 100)
        position_hint = f"Scene {scene_index+1}/{total_scenes} (~{position_pct}% through the video)"
        
        # Send a relevant chunk of the script based on position
        # For a 100-scene video, scene 50 should look at the middle of the script
        script_len = len(script_text)
        chunk_size = 8000  # ~2000 words, enough context
        
        # Calculate start position based on scene position
        estimated_start = int((scene_index / total_scenes) * script_len) - (chunk_size // 2)
        estimated_start = max(0, estimated_start)
        estimated_end = min(script_len, estimated_start + chunk_size)
        
        script_chunk = script_text[estimated_start:estimated_end]
        
        # Add ellipsis indicators if we're showing a chunk
        if estimated_start > 0:
            script_chunk = "..." + script_chunk
        if estimated_end < script_len:
            script_chunk = script_chunk + "..."
        
        prompt = (
            f"TASK: Find the EXACT sentence from the Script that matches this video scene.\n\n"
            f"VIDEO VISUAL: \"{visual_facts}\"\n"
            f"POSITION: {position_hint}\n\n"
            f"SCRIPT (relevant section):\n{script_chunk}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Find the sentence that describes what's happening in the video visual.\n"
            f"2. Return ONLY that sentence from the script - no changes, no additions.\n"
            f"3. If multiple sentences match, pick the one closest to the expected position.\n"
            f"4. If no exact match exists, return the closest relevant sentence.\n\n"
            f"MATCHING SENTENCE:"
        )
        
        print(f"🔗 Anchoring scene {scene_index+1}/{total_scenes} to script...", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    prompt,
                    request_options={"timeout": 60}
                )
                
                matched = response.text.strip()
                
                # Clean up any quotes or labels
                matched = matched.strip('"\'')
                if matched.lower().startswith("matching sentence:"):
                    matched = matched[17:].strip()
                
                if matched:
                    print(f"🔗 Anchored: \"{matched[:60]}...\"", flush=True)
                    return matched
                
                print(f"⚠️ Empty anchor response, retrying...", flush=True)
                
            except Exception as e:
                print(f"⚠️ Anchor error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(3 * (attempt + 1))
        
        raise Exception(f"Anchor to script failed after {max_retries} retries: {last_error}")
    
    async def adapt_sentence_to_duration(
        self,
        sentence: str,
        duration: float,
        max_retries: int = 3
    ) -> str:
        """
        Adapt a sentence to fit a specific speaking duration.
        
        Takes the matched sentence from the script and adjusts its length
        to fit the scene duration while preserving meaning and tone.
        
        Args:
            sentence: The matched sentence from anchor_to_script()
            duration: Scene duration in seconds
            max_retries: Number of retry attempts
            
        Returns:
            Adapted sentence that fits the duration
        """
        word_limit = max(10, int(duration * 2.5))  # ~2.5 words/second speaking rate
        
        prompt = (
            f"TASK: Adapt this sentence to be spoken in {duration:.1f} seconds (~{word_limit} words).\n\n"
            f"ORIGINAL: \"{sentence}\"\n\n"
            f"RULES:\n"
            f"1. Keep the dramatic tone and style.\n"
            f"2. Keep all character names exactly as written.\n"
            f"3. Keep the key plot points and meaning.\n"
            f"4. If the original is too long, condense it.\n"
            f"5. If the original is too short, expand it slightly with dramatic flair.\n"
            f"6. Never say 'we see' or describe visuals - this is narration, not description.\n\n"
            f"ADAPTED SENTENCE:"
        )
        
        print(f"✂️ Adapting to {duration:.1f}s (~{word_limit} words)...", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    prompt,
                    request_options={"timeout": 45}
                )
                
                adapted = response.text.strip()
                
                # Clean up any quotes or labels
                adapted = adapted.strip('"\'')
                if adapted.lower().startswith("adapted sentence:"):
                    adapted = adapted[17:].strip()
                
                if adapted:
                    return adapted
                
                print(f"⚠️ Empty adapt response, retrying...", flush=True)
                
            except Exception as e:
                print(f"⚠️ Adapt error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(3 * (attempt + 1))
        
        # Fallback: return original sentence if adaptation fails
        print(f"⚠️ Adaptation failed, using original sentence", flush=True)
        return sentence
    
    async def anchor_and_adapt_batch(
        self,
        visual_facts_list: List[str],
        script_text: str,
        durations: List[float],
        start_index: int = 0,
        total_scenes: int = 0,
        max_retries: int = 3
    ) -> List[str]:
        """
        Batch version of anchor + adapt for efficiency.
        
        Processes multiple scenes in one API call to reduce latency.
        
        Args:
            visual_facts_list: List of visual descriptions
            script_text: Full narration script
            durations: List of scene durations
            start_index: Starting scene index for position calculation
            total_scenes: Total scenes in video
            max_retries: Number of retry attempts
            
        Returns:
            List of adapted narrations
        """
        if total_scenes == 0:
            total_scenes = len(visual_facts_list)
        
        # Build the batch prompt
        scenes_text = ""
        for i, (facts, dur) in enumerate(zip(visual_facts_list, durations)):
            scene_idx = start_index + i
            position_pct = int((scene_idx / total_scenes) * 100)
            word_limit = max(10, int(dur * 2.5))
            scenes_text += (
                f"\nScene {scene_idx+1} (~{position_pct}% through, {dur:.1f}s, ~{word_limit} words):\n"
                f"Visual: \"{facts}\"\n"
            )
        
        prompt = (
            f"TASK: For each scene, find the matching sentence from the Script and adapt it to fit the duration.\n\n"
            f"SCRIPT:\n{script_text[:12000]}\n\n"
            f"SCENES:{scenes_text}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. For each scene, find the script sentence that matches the visual.\n"
            f"2. Adapt each sentence to fit its word limit.\n"
            f"3. Keep dramatic tone, character names, and plot points.\n"
            f"4. Never say 'we see' - this is narration.\n\n"
            f"Return a JSON array with one adapted narration per scene:\n"
            f"[\"narration 1\", \"narration 2\", ...]\n\n"
            f"JSON array:"
        )
        
        print(f"🔗 Batch anchor+adapt: {len(visual_facts_list)} scenes", flush=True)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.model.generate_content_async(
                    prompt,
                    request_options={"timeout": 120}
                )
                
                raw_response = response.text.strip()
                narrations = self._parse_batch_response(raw_response, len(visual_facts_list))
                
                print(f"✅ Batch anchor+adapt success: {len(narrations)} narrations", flush=True)
                return narrations
                
            except Exception as e:
                print(f"⚠️ Batch anchor error (attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                last_error = e
                await asyncio.sleep(5 * (attempt + 1))
        
        raise Exception(f"Batch anchor+adapt failed after {max_retries} retries: {last_error}")
    
    def _parse_batch_response(self, raw_response: str, expected_count: int) -> List[str]:
        """
        Parse the JSON array response from batch narration request.
        """
        import json
        import re
        
        # Try to find JSON array in response
        try:
            json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
            if json_match:
                narrations = json.loads(json_match.group())
                if isinstance(narrations, list) and len(narrations) == expected_count:
                    return [str(n) for n in narrations]
        except json.JSONDecodeError:
            pass
        
        # Fallback: try to split by numbered segments
        lines = raw_response.strip().split('\n')
        narrations = []
        for line in lines:
            cleaned = re.sub(r'^(\d+[\.\):]?\s*|Segment\s*\d+:\s*)', '', line.strip())
            if cleaned and not cleaned.startswith('[') and not cleaned.startswith('{'):
                narrations.append(cleaned)
        
        if len(narrations) >= expected_count:
            return narrations[:expected_count]
        
        # If parsing fails, raise exception
        raise Exception(f"Failed to parse batch response. Got {len(narrations)} narrations, expected {expected_count}")
    
    async def delete_video(self, file_uri_or_path: str) -> bool:
        """
        Delete an uploaded video from Gemini.
        
        Args:
            file_uri_or_path: Gemini file URI or original file path
            
        Returns:
            True if deleted successfully
        """
        try:
            # If it's a URI, extract the file name
            if file_uri_or_path.startswith("https://"):
                # URI format: https://generativelanguage.googleapis.com/v1beta/files/xxx
                file_name = file_uri_or_path.split("/")[-1]
            elif file_uri_or_path in self._uploaded_files:
                file_name = self._uploaded_files[file_uri_or_path]
            else:
                # Assume it's already a file name
                file_name = file_uri_or_path
            
            genai.delete_file(file_name)
            print(f"🗑️ Deleted video from Gemini: {file_name}", flush=True)
            
            # Clean up tracking dict
            for path, name in list(self._uploaded_files.items()):
                if name == file_name:
                    del self._uploaded_files[path]
                    break
            
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to delete video: {e}", flush=True)
            return False
    
    async def cleanup_all(self):
        """Delete all uploaded videos."""
        for file_path in list(self._uploaded_files.keys()):
            await self.delete_video(file_path)

