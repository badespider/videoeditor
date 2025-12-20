# Character Name Extraction Upgrade Plan

## Current State Analysis

### Existing Implementation (`script_generator.py:_extract_names_from_dialogue`)
```python
def _extract_names_from_dialogue(self, audio_transcript: List[dict]) -> List[str]:
```

**Current Approach:**
1. Regex pattern matching for:
   - Direct address: "Kaliska!", "Dek, listen!"
   - Introductions: "I am Dek", "My name is Thea"
   - References: "Where is Thea?", "Kaliska is coming"
   - Frequency-based: Capitalized words appearing 3+ times

**Limitations:**
- ❌ Misses names not following these patterns (e.g., "Strange began to understand")
- ❌ Can't distinguish character names from proper nouns (places, titles)
- ❌ No visual context (can't see WHO is on screen)
- ❌ No speaker-to-character mapping
- ❌ No persistence across episodes
- ❌ Can't handle non-English names well
- ❌ Doesn't leverage Memories.ai's visual understanding

### Available Infrastructure

1. **Memories.ai Chat API** (`memories_client.py:get_dialogue_transcript`)
   - Already extracts dialogue with character names using video+audio context
   - Can see faces, on-screen text, visual context
   - Returns: `{"speaker": "Doctor Strange", "text": "...", "start": 0.0, "end": 2.0}`

2. **Gemini API** (`gemini_client.py`)
   - Available for text-based character analysis
   - Can understand story context and infer character identities

3. **Redis** (`job_manager.py`)
   - Already used for job state
   - Can be leveraged for character persistence

---

## Upgrade Architecture

### New Service: `CharacterExtractor`

```
backend/app/services/character_extractor.py
```

#### Core Components:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CharacterExtractor Service                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐ │
│  │   AI-Based   │   │   Visual     │   │   Character Database     │ │
│  │  Extraction  │   │  Tracking    │   │   (Redis + Postgres)     │ │
│  │  (Gemini)    │   │ (Memories)   │   │                          │ │
│  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘ │
│         │                  │                         │               │
│         └────────┬─────────┴─────────────────────────┘               │
│                  │                                                   │
│                  ▼                                                   │
│         ┌───────────────────┐                                        │
│         │  Character Merge  │  ← Deduplication & Confidence Scoring  │
│         │     Engine        │                                        │
│         └─────────┬─────────┘                                        │
│                   │                                                  │
│                   ▼                                                  │
│         ┌───────────────────┐                                        │
│         │   CharacterInfo   │  ← Unified character profile           │
│         │    Data Model     │                                        │
│         └───────────────────┘                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Implementation Plan

### Phase 1: Data Models & Database Schema

#### 1.1 Character Data Models

```python
# backend/app/models.py (additions)

@dataclass
class CharacterAppearance:
    """A character's appearance in a specific video segment."""
    start_time: float
    end_time: float
    confidence: float  # 0-1 how confident we are this is the character
    source: str  # "visual", "dialogue", "ai_inference"
    
@dataclass
class CharacterInfo:
    """Complete character profile."""
    id: str  # Unique ID (e.g., "char_abc123")
    name: str  # Primary name (e.g., "Doctor Strange")
    aliases: List[str]  # Alternative names ["Stephen", "Strange", "The Sorcerer"]
    description: str  # Visual/role description
    role: str  # "protagonist", "antagonist", "supporting", "minor"
    visual_traits: List[str]  # ["dark hair", "goatee", "red cloak"]
    first_appearance: float  # Timestamp in video
    appearances: List[CharacterAppearance]  # All appearances
    confidence: float  # Overall confidence in this character
    source_video_no: str  # Video where character was identified
    
@dataclass  
class SeriesCharacterDatabase:
    """Persistent character database for a series/channel."""
    series_id: str  # Unique series identifier
    characters: Dict[str, CharacterInfo]  # char_id -> CharacterInfo
    speaker_mappings: Dict[str, str]  # "Speaker 1" -> "char_abc123"
    created_at: datetime
    updated_at: datetime
```

#### 1.2 Database Schema (PostgreSQL - Future)

For now, use Redis with JSON serialization. Later migrate to PostgreSQL:

```sql
-- Future PostgreSQL schema
CREATE TABLE series (
    id UUID PRIMARY KEY,
    name VARCHAR(255),
    channel_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE characters (
    id UUID PRIMARY KEY,
    series_id UUID REFERENCES series(id),
    name VARCHAR(255) NOT NULL,
    aliases JSONB DEFAULT '[]',
    description TEXT,
    role VARCHAR(50),
    visual_traits JSONB DEFAULT '[]',
    confidence FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE character_appearances (
    id UUID PRIMARY KEY,
    character_id UUID REFERENCES characters(id),
    video_no VARCHAR(100) NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    source VARCHAR(50) -- 'visual', 'dialogue', 'ai_inference'
);

CREATE INDEX idx_appearances_video ON character_appearances(video_no);
CREATE INDEX idx_characters_series ON characters(series_id);
```

---

### Phase 2: AI-Based Character Extraction

#### 2.1 Gemini Character Extraction

```python
# backend/app/services/character_extractor.py

async def extract_characters_ai(
    self,
    transcript: str,
    plot_summary: str = "",
    existing_characters: Optional[List[CharacterInfo]] = None
) -> List[CharacterInfo]:
    """
    Use Gemini to identify characters with descriptions.
    
    Args:
        transcript: Full dialogue transcript
        plot_summary: Optional plot context
        existing_characters: Known characters from previous episodes
        
    Returns:
        List of CharacterInfo objects with names, descriptions, roles
    """
    # Build context from existing characters
    existing_context = ""
    if existing_characters:
        existing_context = "KNOWN CHARACTERS FROM PREVIOUS EPISODES:\n"
        for char in existing_characters:
            existing_context += f"- {char.name}: {char.description}\n"
            if char.aliases:
                existing_context += f"  Aliases: {', '.join(char.aliases)}\n"
    
    prompt = f"""Analyze this video transcript and extract ALL characters mentioned or speaking.

{existing_context}

TRANSCRIPT:
{transcript[:8000]}

{f"PLOT CONTEXT: {plot_summary[:1000]}" if plot_summary else ""}

For EACH character, provide:
1. name: Their full name or best identifier
2. aliases: Other names/titles they're called (list)
3. description: Brief visual and role description (1-2 sentences)
4. role: "protagonist", "antagonist", "supporting", or "minor"
5. visual_traits: List of distinctive visual features (e.g., ["white hair", "scar on face"])
6. confidence: 0-1 how confident you are in this identification

IMPORTANT:
- Include BOTH speaking characters AND characters only mentioned
- Use existing character names if they match someone mentioned
- Don't create duplicates of existing characters
- Mark new characters with confidence < 0.8

Return as JSON array:
[
  {{
    "name": "Doctor Strange",
    "aliases": ["Stephen", "Strange", "The Sorcerer Supreme"],
    "description": "Former neurosurgeon turned Master of the Mystic Arts. Wears a red cloak.",
    "role": "protagonist",
    "visual_traits": ["goatee", "gray temples", "red Cloak of Levitation"],
    "confidence": 0.95
  }},
  ...
]

JSON array:"""

    try:
        response = await self.gemini_model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=4096
            )
        )
        
        # Parse JSON response
        return self._parse_character_response(response.text)
        
    except Exception as e:
        print(f"⚠️ Gemini character extraction failed: {e}", flush=True)
        return []
```

#### 2.2 Visual Character Tracking (Memories.ai Integration)

```python
async def extract_characters_visual(
    self,
    video_no: str,
    unique_id: str = "default"
) -> List[CharacterInfo]:
    """
    Use Memories.ai Chat API to identify characters visually.
    
    This leverages the video understanding to:
    - Identify faces and associate with names
    - Track character appearances across scenes
    - Get visual descriptions
    """
    prompt = """Analyze this video and identify ALL characters that appear.

For EACH character visible in the video:
1. Name them (use actual character names if known, otherwise describe them)
2. Note their visual appearance (hair, clothes, distinctive features)
3. List the approximate time ranges when they appear on screen
4. Rate your confidence in the identification (0-1)

FORMAT AS JSON:
[
  {
    "name": "Character Name",
    "visual_description": "Description of appearance",
    "appearances": [{"start": 0.0, "end": 30.5}, {"start": 45.0, "end": 60.0}],
    "confidence": 0.9
  }
]

Return ONLY the JSON array."""

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.base_url}/chat",
                headers=self.headers,
                json={
                    "video_nos": [video_no],
                    "prompt": prompt,
                    "unique_id": unique_id
                }
            )
            
            result = response.json()
            content = result.get("data", {}).get("content", "")
            return self._parse_visual_character_response(content)
            
    except Exception as e:
        print(f"⚠️ Visual character extraction failed: {e}", flush=True)
        return []
```

---

### Phase 3: Character Merge Engine

#### 3.1 Deduplication & Merging

```python
def merge_characters(
    self,
    ai_characters: List[CharacterInfo],
    visual_characters: List[CharacterInfo],
    existing_characters: List[CharacterInfo]
) -> List[CharacterInfo]:
    """
    Merge characters from multiple sources, removing duplicates.
    
    Uses fuzzy name matching and visual trait comparison to identify
    the same character from different sources.
    """
    all_characters = []
    
    # Priority: existing > visual > AI
    # (existing have been verified, visual is more reliable than text-only)
    
    for char in existing_characters:
        all_characters.append(char)
    
    for char in visual_characters:
        match = self._find_matching_character(char, all_characters)
        if match:
            # Merge with existing
            self._merge_into(match, char)
        else:
            all_characters.append(char)
    
    for char in ai_characters:
        match = self._find_matching_character(char, all_characters)
        if match:
            self._merge_into(match, char)
        else:
            all_characters.append(char)
    
    return all_characters

def _find_matching_character(
    self,
    char: CharacterInfo,
    existing: List[CharacterInfo]
) -> Optional[CharacterInfo]:
    """Find a matching character using fuzzy matching."""
    from difflib import SequenceMatcher
    
    for existing_char in existing:
        # Check name similarity
        name_ratio = SequenceMatcher(
            None, 
            char.name.lower(), 
            existing_char.name.lower()
        ).ratio()
        
        if name_ratio > 0.8:
            return existing_char
        
        # Check aliases
        for alias in existing_char.aliases:
            if SequenceMatcher(None, char.name.lower(), alias.lower()).ratio() > 0.8:
                return existing_char
        
        # Check if char.name is in existing aliases
        for alias in char.aliases:
            if SequenceMatcher(None, alias.lower(), existing_char.name.lower()).ratio() > 0.8:
                return existing_char
    
    return None
```

---

### Phase 4: Persistent Character Database

#### 4.1 Redis-Based Storage (Phase 1)

```python
class CharacterDatabase:
    """Persistent character storage using Redis."""
    
    def __init__(self):
        self.redis = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True
        )
        self.prefix = "characters:"
    
    def get_series_characters(self, series_id: str) -> List[CharacterInfo]:
        """Get all characters for a series."""
        data = self.redis.get(f"{self.prefix}{series_id}")
        if data:
            chars = json.loads(data)
            return [CharacterInfo(**c) for c in chars]
        return []
    
    def save_series_characters(
        self, 
        series_id: str, 
        characters: List[CharacterInfo]
    ):
        """Save characters for a series."""
        data = json.dumps([asdict(c) for c in characters])
        self.redis.set(f"{self.prefix}{series_id}", data)
    
    def add_character(
        self, 
        series_id: str, 
        character: CharacterInfo
    ):
        """Add a single character to a series."""
        characters = self.get_series_characters(series_id)
        
        # Check for duplicates
        existing = self._find_matching(character, characters)
        if existing:
            self._merge_into(existing, character)
        else:
            characters.append(character)
        
        self.save_series_characters(series_id, characters)
    
    def get_speaker_mapping(
        self, 
        series_id: str
    ) -> Dict[str, str]:
        """Get speaker label to character name mapping."""
        data = self.redis.get(f"{self.prefix}{series_id}:speakers")
        return json.loads(data) if data else {}
    
    def save_speaker_mapping(
        self, 
        series_id: str, 
        mapping: Dict[str, str]
    ):
        """Save speaker to character mapping."""
        self.redis.set(
            f"{self.prefix}{series_id}:speakers", 
            json.dumps(mapping)
        )
```

---

### Phase 5: Integration with Pipeline

#### 5.1 Pipeline Integration Points

```python
# backend/app/workers/pipeline.py

async def process_video(self, job_id: str, job_data: dict):
    # ... existing code ...
    
    # NEW: Character extraction step (after video upload, before narration)
    series_id = job_data.get("series_id", "default")
    
    # Get existing characters from database
    char_db = CharacterDatabase()
    existing_characters = char_db.get_series_characters(series_id)
    
    # Extract characters from this video
    character_extractor = CharacterExtractor()
    
    # Multi-source extraction
    ai_characters = await character_extractor.extract_characters_ai(
        transcript=full_transcript,
        plot_summary=plot_summary,
        existing_characters=existing_characters
    )
    
    visual_characters = await character_extractor.extract_characters_visual(
        video_no=video_no,
        unique_id=job_id
    )
    
    # Merge all character sources
    merged_characters = character_extractor.merge_characters(
        ai_characters=ai_characters,
        visual_characters=visual_characters,
        existing_characters=existing_characters
    )
    
    # Save to database
    char_db.save_series_characters(series_id, merged_characters)
    
    # Build character guide for narration
    character_guide = character_extractor.build_character_guide(merged_characters)
    
    # ... continue with narration generation using character_guide ...
```

#### 5.2 Character Guide Builder

```python
def build_character_guide(
    self, 
    characters: List[CharacterInfo]
) -> str:
    """
    Build a character guide string for narration.
    
    Format:
    Woman with powers = The Ancient One
    Skeptical man = Doctor Strange
    """
    guide_lines = []
    
    for char in characters:
        if char.visual_traits or char.description:
            # Create description-based mapping
            if char.visual_traits:
                visual_desc = ", ".join(char.visual_traits[:2])
                guide_lines.append(f"{visual_desc} = {char.name}")
            
            # Add role-based mapping
            if "protagonist" in char.role:
                guide_lines.append(f"Main character = {char.name}")
            elif "antagonist" in char.role:
                guide_lines.append(f"Villain = {char.name}")
        
        # Add aliases
        for alias in char.aliases:
            if alias.lower() != char.name.lower():
                guide_lines.append(f"{alias} = {char.name}")
    
    return "\n".join(guide_lines)
```

---

## API Endpoints (Optional - for UI Integration)

```python
# backend/app/routers/characters.py

@router.get("/series/{series_id}/characters")
async def get_series_characters(series_id: str):
    """Get all characters for a series."""
    char_db = CharacterDatabase()
    characters = char_db.get_series_characters(series_id)
    return {"characters": [asdict(c) for c in characters]}

@router.post("/series/{series_id}/characters")
async def add_character(series_id: str, character: CharacterCreateRequest):
    """Manually add a character."""
    char_db = CharacterDatabase()
    char_info = CharacterInfo(
        id=str(uuid4()),
        name=character.name,
        aliases=character.aliases or [],
        description=character.description or "",
        role=character.role or "supporting",
        visual_traits=character.visual_traits or [],
        confidence=1.0,  # Manual = high confidence
        source_video_no="manual"
    )
    char_db.add_character(series_id, char_info)
    return {"character_id": char_info.id}

@router.put("/series/{series_id}/characters/{char_id}")
async def update_character(series_id: str, char_id: str, updates: CharacterUpdateRequest):
    """Update a character (correct misidentification)."""
    # ... implementation ...

@router.delete("/series/{series_id}/characters/{char_id}")
async def delete_character(series_id: str, char_id: str):
    """Delete a character."""
    # ... implementation ...
```

---

## Implementation Priority

### Phase 1: Core AI Extraction (Week 1)
- [ ] Create `CharacterExtractor` service
- [ ] Implement `extract_characters_ai()` with Gemini
- [ ] Basic `CharacterInfo` data model
- [ ] Integration with existing pipeline

### Phase 2: Visual Integration (Week 2)
- [ ] Implement `extract_characters_visual()` with Memories.ai
- [ ] Character merge engine
- [ ] Deduplication logic

### Phase 3: Persistence (Week 3)
- [ ] Redis-based `CharacterDatabase`
- [ ] Series/episode tracking
- [ ] Speaker mapping persistence

### Phase 4: API & UI (Week 4)
- [ ] REST API endpoints
- [ ] Frontend character management UI
- [ ] Manual correction workflow

---

## Success Metrics

1. **Accuracy**: >90% of characters correctly identified
2. **Consistency**: Same character uses same name across episodes
3. **Coverage**: Identify >95% of speaking characters
4. **Performance**: <5s extraction time per video
5. **Persistence**: Characters survive across processing jobs

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| AI hallucinating character names | Confidence scoring + manual review |
| Duplicate characters across sources | Fuzzy matching + merge engine |
| Performance impact | Cache characters, async processing |
| Storage growth | TTL on old series, cleanup jobs |
| Memories.ai API limits | Rate limiting, caching, fallback to Gemini-only |

