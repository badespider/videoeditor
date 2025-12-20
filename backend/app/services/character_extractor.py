"""
CharacterExtractor Service - AI-Powered Character Identification

Extracts character names, aliases, and descriptions from video transcripts
using Gemini AI and visual analysis via Memories.ai.

Phase 1: Core AI Extraction (Gemini) - COMPLETE
Phase 2: Visual tracking via Memories.ai - COMPLETE
- Phase 3 will add: Persistent character database (Redis)
- Phase 4 will add: API endpoints and UI
"""

import re
import json
import uuid
import httpx
from typing import List, Optional, Dict

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from app.config import get_settings
from app.models import CharacterInfo, CharacterAppearance
from app.services.name_matching import name_similarity_ratio


class CharacterExtractor:
    """
    AI-powered character extraction from video transcripts and visual analysis.
    
    Uses two extraction methods:
    1. Gemini AI - Analyzes transcripts for character names, aliases, roles
    2. Memories.ai Chat API - Visual analysis to identify characters by appearance
    
    Results from both sources are merged with intelligent deduplication.
    """
    
    def __init__(self):
        self.settings = get_settings()
        
        # Configure Gemini API
        genai.configure(api_key=self.settings.gemini.api_key)
        
        # Use Gemini 2.0 Flash for character extraction
        self.model = genai.GenerativeModel(
            'gemini-2.0-flash',
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        # Memories.ai API configuration for visual extraction
        self.memories_base_url = f"{self.settings.memories.base_url}/serve/api/v1"
        self.memories_headers = {
            "Authorization": self.settings.memories.api_key
        }
        
        # Minimum confidence to include a character
        self.MIN_CONFIDENCE = 0.3
    
    async def extract_characters_ai(
        self,
        transcript: str,
        plot_summary: str = "",
        existing_characters: Optional[List[CharacterInfo]] = None
    ) -> List[CharacterInfo]:
        """
        Use Gemini to identify characters with descriptions.
        
        Args:
            transcript: Full dialogue transcript from the video
            plot_summary: Optional plot context for better identification
            existing_characters: Known characters from previous episodes/videos
            
        Returns:
            List of CharacterInfo objects with names, descriptions, roles
        """
        if not transcript or not transcript.strip():
            print("⚠️ Empty transcript, skipping character extraction", flush=True)
            return []
        
        print(f"🎭 Extracting characters from transcript ({len(transcript)} chars)...", flush=True)
        
        # Build context from existing characters
        existing_context = ""
        if existing_characters:
            existing_context = "KNOWN CHARACTERS FROM PREVIOUS EPISODES:\n"
            for char in existing_characters:
                existing_context += f"- {char.name}: {char.description}\n"
                if char.aliases:
                    existing_context += f"  Aliases: {', '.join(char.aliases)}\n"
            existing_context += "\n"
        
        # Truncate transcript if too long (keep first 8000 chars for context)
        truncated_transcript = transcript[:8000] if len(transcript) > 8000 else transcript
        
        prompt = f"""Analyze this video transcript and extract ALL characters mentioned or speaking.

{existing_context}TRANSCRIPT:
{truncated_transcript}

{f"PLOT CONTEXT: {plot_summary[:1000]}" if plot_summary else ""}

For EACH character, provide:
1. name: Their full name or best identifier (e.g., "Doctor Strange", "The Ancient One")
2. aliases: Other names/titles they're called (list). Example: ["Stephen", "Strange", "The Sorcerer Supreme"]
3. description: Brief visual and role description (1-2 sentences)
4. role: One of: "protagonist", "antagonist", "supporting", or "minor"
5. visual_traits: List of distinctive visual features mentioned (e.g., ["white hair", "scar on face", "red cloak"])
6. confidence: 0-1 how confident you are in this identification (1.0 = certain, 0.5 = likely, 0.3 = possible)

IMPORTANT:
- Include BOTH speaking characters AND characters only mentioned
- Use existing character names if they match someone mentioned
- Don't create duplicates of existing characters
- Mark new characters with confidence < 0.8 unless very clearly identified
- Exclude generic terms like "man", "woman", "person" unless they're actual character names

Return as JSON array ONLY (no other text):
[
  {{
    "name": "Doctor Strange",
    "aliases": ["Stephen", "Strange", "The Sorcerer Supreme"],
    "description": "Former neurosurgeon turned Master of the Mystic Arts. Wears a red cloak.",
    "role": "protagonist",
    "visual_traits": ["goatee", "gray temples", "red Cloak of Levitation"],
    "confidence": 0.95
  }},
  {{
    "name": "The Ancient One",
    "aliases": ["Ancient One"],
    "description": "Powerful sorcerer and mentor. Bald woman with mystical abilities.",
    "role": "supporting",
    "visual_traits": ["bald", "robes", "glowing hands"],
    "confidence": 0.9
  }}
]

JSON array:"""

        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.3,  # Lower temperature for more consistent output
                    max_output_tokens=4096
                )
            )
            
            # Parse JSON response
            characters = self._parse_character_response(response.text)
            
            # Filter by confidence
            characters = [c for c in characters if c.confidence >= self.MIN_CONFIDENCE]
            
            # Merge with existing characters if provided
            if existing_characters:
                characters = self.merge_characters(characters, existing_characters)
            
            print(f"✅ Extracted {len(characters)} characters:", flush=True)
            for char in characters[:5]:  # Log first 5
                print(f"   - {char.name} ({char.role}, conf: {char.confidence:.2f})", flush=True)
            if len(characters) > 5:
                print(f"   ... and {len(characters) - 5} more", flush=True)
            
            return characters
            
        except Exception as e:
            print(f"⚠️ Gemini character extraction failed: {e}", flush=True)
            # Fall back to basic regex extraction
            return self._fallback_regex_extraction(transcript)
    
    async def extract_characters_visual(
        self,
        video_no: str,
        unique_id: str = "default"
    ) -> List[CharacterInfo]:
        """
        Use Memories.ai Chat API to identify characters visually.
        
        Leverages video understanding to:
        - Identify faces and associate with names
        - Track character appearances across scenes
        - Get visual descriptions (hair, clothes, features)
        
        Args:
            video_no: The Memories.ai video ID
            unique_id: Workspace/user identifier
            
        Returns:
            List of CharacterInfo objects identified from visual analysis
        """
        if not video_no:
            print("⚠️ No video_no provided, skipping visual extraction", flush=True)
            return []
        
        print(f"👁️ Extracting characters visually from video {video_no}...", flush=True)
        
        prompt = """Analyze this video and identify ALL characters that appear visually.

For EACH character visible in the video:
1. Name them (use actual character names if known from dialogue, context, or on-screen text)
2. If you can't determine their name, use a descriptive identifier like "Woman in Red Dress" or "Bearded Man"
3. Describe their visual appearance in detail (hair color/style, clothing, distinctive features)
4. List the approximate time ranges when they appear on screen
5. Rate your confidence in the identification (0-1)

IMPORTANT:
- Focus on VISUAL identification - what you can SEE in the video
- Include main characters AND background/minor characters
- Note distinctive visual traits that can identify this character across scenes
- Use actual names when possible (from dialogue, titles, or context clues)

FORMAT YOUR RESPONSE AS A JSON ARRAY ONLY:
[
  {
    "name": "Doctor Strange",
    "visual_description": "Man with dark hair, graying temples, goatee. Wears a blue tunic and red Cloak of Levitation.",
    "visual_traits": ["goatee", "gray temples", "red cloak", "blue tunic"],
    "appearances": [{"start": 0.0, "end": 30.5}, {"start": 45.0, "end": 60.0}],
    "role": "protagonist",
    "confidence": 0.95
  },
  {
    "name": "The Ancient One",
    "visual_description": "Bald woman in yellow robes. Has a calm, wise demeanor.",
    "visual_traits": ["bald", "yellow robes", "celtic tattoos"],
    "appearances": [{"start": 15.0, "end": 45.0}],
    "role": "supporting",
    "confidence": 0.9
  }
]

Return ONLY the JSON array, no other text. Start with [ and end with ]"""

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{self.memories_base_url}/chat",
                    headers={
                        **self.memories_headers,
                        "Content-Type": "application/json"
                    },
                    json={
                        "video_nos": [video_no],
                        "prompt": prompt,
                        "unique_id": unique_id
                    }
                )
                
                print(f"📥 Visual extraction response: {response.status_code}", flush=True)
                response.raise_for_status()
                
                result = response.json()
                
                if result.get("code") != "0000":
                    msg = result.get("msg", "Unknown error")
                    print(f"⚠️ Memories.ai visual extraction failed: {msg}", flush=True)
                    return []
                
                # Extract the response content
                content = result.get("data", {}).get("content", "")
                
                if not content:
                    print(f"⚠️ Empty visual extraction response", flush=True)
                    return []
                
                # Parse the JSON response
                characters = self._parse_visual_character_response(content, video_no)
                
                if characters:
                    print(f"✅ Visually identified {len(characters)} characters:", flush=True)
                    for char in characters[:5]:
                        traits_preview = ", ".join(char.visual_traits[:3]) if char.visual_traits else "no traits"
                        print(f"   👁️ {char.name} ({char.role}, conf: {char.confidence:.2f}) - {traits_preview}", flush=True)
                    if len(characters) > 5:
                        print(f"   ... and {len(characters) - 5} more", flush=True)
                
                return characters
                
        except httpx.HTTPStatusError as e:
            print(f"⚠️ HTTP error during visual extraction: {e}", flush=True)
            return []
        except Exception as e:
            print(f"⚠️ Visual character extraction failed: {e}", flush=True)
            return []
    
    def _parse_visual_character_response(
        self,
        response_text: str,
        video_no: str = ""
    ) -> List[CharacterInfo]:
        """
        Parse Memories.ai visual extraction response into CharacterInfo objects.
        
        Args:
            response_text: Raw JSON response from Memories.ai Chat API
            video_no: The video ID for tracking source
            
        Returns:
            List of CharacterInfo objects with visual data
        """
        characters = []
        
        try:
            # Clean up response - find JSON array
            text = response_text.strip()
            
            # Find JSON array bounds
            start_idx = text.find('[')
            end_idx = text.rfind(']') + 1
            
            if start_idx == -1 or end_idx == 0:
                print(f"⚠️ No JSON array found in visual response", flush=True)
                return []
            
            json_str = text[start_idx:end_idx]
            data = json.loads(json_str)
            
            if not isinstance(data, list):
                print(f"⚠️ Visual response is not a list", flush=True)
                return []
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                name = item.get("name", "").strip()
                if not name:
                    continue
                
                # Parse appearances into CharacterAppearance objects
                appearances = []
                raw_appearances = item.get("appearances", [])
                if isinstance(raw_appearances, list):
                    for app in raw_appearances:
                        if isinstance(app, dict):
                            appearances.append(CharacterAppearance(
                                start_time=float(app.get("start", 0)),
                                end_time=float(app.get("end", 0)),
                                confidence=float(item.get("confidence", 0.5)),
                                source="visual"
                            ))
                
                # Get first appearance time
                first_appearance = 0.0
                if appearances:
                    first_appearance = min(a.start_time for a in appearances)
                
                # Create CharacterInfo object
                char = CharacterInfo(
                    id=f"char_vis_{uuid.uuid4().hex[:8]}",
                    name=name,
                    aliases=[],  # Visual extraction typically gives canonical names
                    description=item.get("visual_description", "") or "",
                    role=item.get("role", "supporting") or "supporting",
                    visual_traits=item.get("visual_traits", []) or [],
                    confidence=float(item.get("confidence", 0.7)),
                    first_appearance=first_appearance,
                    appearances=appearances,
                    source_video_no=video_no
                )
                
                characters.append(char)
            
            return characters
            
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed for visual response: {e}", flush=True)
            return []
        except Exception as e:
            print(f"⚠️ Error parsing visual character response: {e}", flush=True)
            return []
    
    def _parse_character_response(self, response_text: str) -> List[CharacterInfo]:
        """
        Parse Gemini's JSON response into CharacterInfo objects.
        
        Args:
            response_text: Raw response from Gemini
            
        Returns:
            List of CharacterInfo objects
        """
        characters = []
        
        try:
            # Clean up response - find JSON array
            text = response_text.strip()
            
            # Find JSON array bounds
            start_idx = text.find('[')
            end_idx = text.rfind(']') + 1
            
            if start_idx == -1 or end_idx == 0:
                print(f"⚠️ No JSON array found in response", flush=True)
                return []
            
            json_str = text[start_idx:end_idx]
            data = json.loads(json_str)
            
            if not isinstance(data, list):
                print(f"⚠️ Response is not a list", flush=True)
                return []
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                name = item.get("name", "").strip()
                if not name:
                    continue
                
                # Create CharacterInfo object
                char = CharacterInfo(
                    id=f"char_{uuid.uuid4().hex[:8]}",
                    name=name,
                    aliases=item.get("aliases", []) or [],
                    description=item.get("description", "") or "",
                    role=item.get("role", "supporting") or "supporting",
                    visual_traits=item.get("visual_traits", []) or [],
                    confidence=float(item.get("confidence", 0.5)),
                    first_appearance=0.0,
                    appearances=[],
                    source_video_no=""
                )
                
                characters.append(char)
            
            return characters
            
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed: {e}", flush=True)
            return []
        except Exception as e:
            print(f"⚠️ Error parsing character response: {e}", flush=True)
            return []
    
    def _fallback_regex_extraction(self, transcript: str) -> List[CharacterInfo]:
        """
        Basic regex-based character extraction as fallback.
        
        Uses the same patterns as ScriptGenerator._extract_names_from_dialogue()
        but returns CharacterInfo objects.
        """
        print("⚠️ Using fallback regex extraction", flush=True)
        
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
            'yes', 'okay', 'ok', 'please', 'thank', 'thanks', 'sorry',
            'hello', 'hi', 'hey', 'goodbye', 'bye', 'well', 'oh', 'ah', 'um',
            'uh', 'like', 'know', 'think', 'want', 'go', 'come', 'see', 'look',
            'get', 'make', 'take', 'give', 'find', 'tell', 'say', 'said',
            'father', 'mother', 'brother', 'sister', 'son', 'daughter',
            'man', 'woman', 'boy', 'girl', 'child', 'children', 'people',
            'one', 'two', 'three', 'first', 'second', 'last'
        }
        
        found_names = set()
        
        # Pattern 1: Direct address - "Name!" or "Name," or "Name?"
        direct_address = re.findall(r'\b([A-Z][a-z]{2,15})[!?,]', transcript)
        for name in direct_address:
            if name.lower() not in common_words:
                found_names.add(name)
        
        # Pattern 2: Introductions
        intro_patterns = [
            r"I am ([A-Z][a-z]{2,15})",
            r"[Mm]y name is ([A-Z][a-z]{2,15})",
            r"[Cc]all me ([A-Z][a-z]{2,15})",
            r"I'm ([A-Z][a-z]{2,15})"
        ]
        for pattern in intro_patterns:
            matches = re.findall(pattern, transcript)
            for name in matches:
                if name.lower() not in common_words:
                    found_names.add(name)
        
        # Pattern 3: Repeated capitalized words (likely names if mentioned 3+ times)
        capitalized_words = re.findall(r'\b([A-Z][a-z]{2,15})\b', transcript)
        word_counts = {}
        for word in capitalized_words:
            if word.lower() not in common_words:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        for word, count in word_counts.items():
            if count >= 3:
                found_names.add(word)
        
        # Convert to CharacterInfo objects
        characters = []
        for name in found_names:
            char = CharacterInfo(
                id=f"char_{uuid.uuid4().hex[:8]}",
                name=name,
                aliases=[],
                description="",
                role="supporting",
                visual_traits=[],
                confidence=0.4,  # Lower confidence for regex extraction
                first_appearance=0.0,
                appearances=[],
                source_video_no=""
            )
            characters.append(char)
        
        return characters
    
    def merge_characters(
        self,
        new_characters: List[CharacterInfo],
        existing_characters: List[CharacterInfo]
    ) -> List[CharacterInfo]:
        """
        Merge new characters with existing ones, removing duplicates.
        
        Uses fuzzy name matching to identify the same character
        from different sources.
        
        Args:
            new_characters: Newly extracted characters
            existing_characters: Known characters from database/previous extraction
            
        Returns:
            Merged list with duplicates removed
        """
        all_characters = list(existing_characters)  # Start with existing
        
        for new_char in new_characters:
            match = self._find_matching_character(new_char, all_characters)
            if match:
                # Merge new info into existing
                self._merge_into(match, new_char)
            else:
                all_characters.append(new_char)
        
        return all_characters
    
    def merge_all_sources(
        self,
        ai_characters: List[CharacterInfo],
        visual_characters: List[CharacterInfo],
        existing_characters: Optional[List[CharacterInfo]] = None
    ) -> List[CharacterInfo]:
        """
        Merge characters from multiple extraction sources with priority ordering.
        
        Priority order:
        1. Existing characters (from database - highest trust)
        2. Visual characters (more reliable for identity)
        3. AI/transcript characters (good for context and aliases)
        
        Uses both fuzzy name matching AND visual trait comparison
        for better deduplication.
        
        Args:
            ai_characters: Characters extracted from transcript by Gemini
            visual_characters: Characters identified visually by Memories.ai
            existing_characters: Known characters from database (Phase 3)
            
        Returns:
            Merged list with duplicates removed, prioritizing reliable sources
        """
        existing_characters = existing_characters or []
        
        print(f"🔀 Merging characters from {len(existing_characters)} existing + {len(visual_characters)} visual + {len(ai_characters)} AI...", flush=True)
        
        # Start with existing characters (highest priority)
        merged = list(existing_characters)
        
        # Add visual characters (priority 2)
        # Visual identification is more reliable for identity
        for visual_char in visual_characters:
            match = self._find_matching_character_enhanced(visual_char, merged)
            if match:
                # Merge visual info into existing (visual gets priority for name and traits)
                self._merge_visual_into(match, visual_char)
            else:
                merged.append(visual_char)
        
        # Add AI characters (priority 3)
        # Good for context, aliases, and role information
        for ai_char in ai_characters:
            match = self._find_matching_character_enhanced(ai_char, merged)
            if match:
                # Merge AI info into existing (AI adds context)
                self._merge_into(match, ai_char)
            else:
                # Lower confidence for AI-only characters
                ai_char.confidence = min(ai_char.confidence, 0.7)
                merged.append(ai_char)
        
        # Sort by confidence (highest first)
        merged.sort(key=lambda c: c.confidence, reverse=True)
        
        print(f"✅ Merged to {len(merged)} unique characters", flush=True)
        
        return merged
    
    def _find_matching_character_enhanced(
        self,
        char: CharacterInfo,
        existing: List[CharacterInfo]
    ) -> Optional[CharacterInfo]:
        """
        Find a matching character using both name AND visual trait matching.
        
        Enhanced matching that considers:
        1. Name similarity (fuzzy matching)
        2. Alias matching
        3. Visual trait overlap (for visually identified characters)
        
        Args:
            char: Character to find match for
            existing: List of existing characters
            
        Returns:
            Matching CharacterInfo or None
        """
        best_match = None
        best_score = 0.0
        
        for existing_char in existing:
            score = 0.0
            
            # Name similarity (weight: 0.6)
            name_ratio = name_similarity_ratio(char.name, existing_char.name)
            score += name_ratio * 0.6
            
            # Alias matching (weight: 0.2)
            alias_match = False
            for alias in existing_char.aliases:
                if name_similarity_ratio(char.name, alias) >= 0.80:
                    alias_match = True
                    break
            if not alias_match:
                for new_alias in char.aliases:
                    if name_similarity_ratio(new_alias, existing_char.name) >= 0.80:
                        alias_match = True
                        break
            if alias_match:
                score += 0.2
            
            # Visual trait similarity (weight: 0.2)
            visual_similarity = self._calculate_visual_similarity(char, existing_char)
            score += visual_similarity * 0.2
            
            # Check if this is the best match so far
            if score > best_score:
                best_score = score
                best_match = existing_char
        
        # Threshold for considering it a match
        if best_score >= 0.5:
            return best_match
        
        return None
    
    def _calculate_visual_similarity(
        self,
        char1: CharacterInfo,
        char2: CharacterInfo
    ) -> float:
        """
        Calculate visual trait similarity between two characters.
        
        Compares visual traits to identify if they might be the same character
        (e.g., both have "goatee" and "red cloak" = likely same person).
        
        Args:
            char1: First character
            char2: Second character
            
        Returns:
            Similarity score from 0.0 to 1.0
        """
        if not char1.visual_traits or not char2.visual_traits:
            return 0.0
        
        # Normalize traits to lowercase
        traits1 = set(t.lower().strip() for t in char1.visual_traits)
        traits2 = set(t.lower().strip() for t in char2.visual_traits)
        
        if not traits1 or not traits2:
            return 0.0
        
        # Calculate Jaccard similarity
        intersection = len(traits1 & traits2)
        union = len(traits1 | traits2)
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def _merge_visual_into(self, target: CharacterInfo, source: CharacterInfo):
        """
        Merge visual character info into target, giving priority to visual data.
        
        Visual sources are more reliable for:
        - Character name (can see who is speaking)
        - Visual traits (direct observation)
        - Appearances (actual on-screen time)
        
        Args:
            target: Existing character to update
            source: Visual character with new info
        """
        # If visual name is more specific, update the target name
        # (e.g., "Doctor Strange" is more specific than "Strange")
        if len(source.name) > len(target.name) and target.name.lower() in source.name.lower():
            # Add old name as alias
            if target.name.lower() not in [a.lower() for a in target.aliases]:
                target.aliases.append(target.name)
            # Update to more complete name
            target.name = source.name
        elif source.name.lower() != target.name.lower():
            # Add visual name as alias if different
            if source.name.lower() not in [a.lower() for a in target.aliases]:
                target.aliases.append(source.name)
        
        # Visual description is usually more accurate
        if source.description and (not target.description or len(source.description) > len(target.description)):
            target.description = source.description
        
        # Visual traits from visual source are more reliable
        for trait in source.visual_traits:
            if trait.lower() not in [t.lower() for t in target.visual_traits]:
                target.visual_traits.append(trait)
        
        # Update confidence (visual source slightly boosted)
        visual_boost = 1.1
        target.confidence = max(target.confidence, min(source.confidence * visual_boost, 1.0))
        
        # Merge appearances
        target.appearances.extend(source.appearances)
        
        # Update first appearance if visual has earlier timestamp
        if source.first_appearance > 0:
            if target.first_appearance == 0 or source.first_appearance < target.first_appearance:
                target.first_appearance = source.first_appearance
        
        # Update source video if not set
        if not target.source_video_no and source.source_video_no:
            target.source_video_no = source.source_video_no
    
    def _find_matching_character(
        self,
        char: CharacterInfo,
        existing: List[CharacterInfo]
    ) -> Optional[CharacterInfo]:
        """
        Find a matching character using fuzzy name matching.
        
        Args:
            char: Character to find match for
            existing: List of existing characters
            
        Returns:
            Matching CharacterInfo or None
        """
        for existing_char in existing:
            # Check name similarity
            name_ratio = name_similarity_ratio(char.name, existing_char.name)
            
            if name_ratio >= 0.80:
                return existing_char
            
            # Check if new name matches any existing alias
            for alias in existing_char.aliases:
                if name_similarity_ratio(char.name, alias) >= 0.80:
                    return existing_char
            
            # Check if any new alias matches existing name or aliases
            for new_alias in char.aliases:
                if name_similarity_ratio(new_alias, existing_char.name) >= 0.80:
                    return existing_char
                for existing_alias in existing_char.aliases:
                    if name_similarity_ratio(new_alias, existing_alias) >= 0.80:
                        return existing_char
        
        return None
    
    def _merge_into(self, target: CharacterInfo, source: CharacterInfo):
        """
        Merge source character info into target.
        
        Updates target with additional info from source.
        """
        # Add new aliases (avoiding duplicates)
        for alias in source.aliases:
            if alias.lower() not in [a.lower() for a in target.aliases]:
                if alias.lower() != target.name.lower():
                    target.aliases.append(alias)
        
        # Add source name as alias if different
        if source.name.lower() != target.name.lower():
            if source.name.lower() not in [a.lower() for a in target.aliases]:
                target.aliases.append(source.name)
        
        # Update description if target is empty
        if not target.description and source.description:
            target.description = source.description
        
        # Add new visual traits
        for trait in source.visual_traits:
            if trait.lower() not in [t.lower() for t in target.visual_traits]:
                target.visual_traits.append(trait)
        
        # Update confidence (take higher)
        target.confidence = max(target.confidence, source.confidence)
        
        # Merge appearances
        target.appearances.extend(source.appearances)
    
    def build_character_guide(self, characters: List[CharacterInfo]) -> str:
        """
        Build a character guide string for narration.
        
        Creates a mapping of descriptions/aliases to proper names
        that can be used by the narration generator.
        
        Format:
        Woman with powers = The Ancient One
        Skeptical man = Doctor Strange
        Stephen = Doctor Strange
        
        Args:
            characters: List of CharacterInfo objects
            
        Returns:
            Character guide string for narration
        """
        if not characters:
            return ""
        
        guide_lines = []
        
        for char in characters:
            # Skip low-confidence characters
            if char.confidence < self.MIN_CONFIDENCE:
                continue
            
            # Add visual trait mappings
            if char.visual_traits:
                # Use first 2 traits to create description
                if len(char.visual_traits) >= 2:
                    visual_desc = f"{char.visual_traits[0]}, {char.visual_traits[1]}"
                    guide_lines.append(f"{visual_desc} = {char.name}")
                elif len(char.visual_traits) == 1:
                    guide_lines.append(f"person with {char.visual_traits[0]} = {char.name}")
            
            # Add role-based mapping for main characters
            if char.role == "protagonist":
                guide_lines.append(f"Main character = {char.name}")
                guide_lines.append(f"Hero = {char.name}")
            elif char.role == "antagonist":
                guide_lines.append(f"Villain = {char.name}")
                guide_lines.append(f"Antagonist = {char.name}")
            
            # Add aliases
            for alias in char.aliases:
                if alias.lower() != char.name.lower():
                    guide_lines.append(f"{alias} = {char.name}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_lines = []
        for line in guide_lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)
        
        guide = "\n".join(unique_lines)
        
        if guide:
            print(f"📝 Built character guide with {len(unique_lines)} mappings", flush=True)
        
        return guide

