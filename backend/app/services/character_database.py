"""
CharacterDatabase Service - Persistent Character Storage

Stores character information in Redis for persistence across video processing jobs.
This enables characters to be remembered across episodes of a series.

Phase 3 of Character Extraction Upgrade.
"""

import json
from datetime import datetime
from typing import List, Optional, Dict
from dataclasses import asdict

import redis

from app.config import get_settings
from app.models import CharacterInfo, CharacterAppearance
from app.services.name_matching import name_similarity_ratio


class CharacterDatabase:
    """
    Persistent character storage using Redis.
    
    Stores character profiles by series_id, allowing characters to be
    remembered across different video processing jobs in the same series.
    
    Redis Key Structure:
    - characters:{series_id}          -> JSON array of CharacterInfo
    - characters:{series_id}:speakers -> JSON object of speaker mappings
    - characters:{series_id}:updated  -> Timestamp of last update
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.redis_url)
        self.prefix = "characters:"
        self.ttl_seconds = 30 * 24 * 60 * 60  # 30 days TTL
    
    def get_series_characters(self, series_id: str) -> List[CharacterInfo]:
        """
        Get all characters for a series.
        
        Args:
            series_id: Unique identifier for the series/channel
            
        Returns:
            List of CharacterInfo objects, or empty list if none found
        """
        if not series_id:
            return []
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            key = f"{self.prefix}{series_id}"
            data = self.redis.get(key)
            
            if not data:
                return []
            
            # Refresh TTL on access
            self.redis.expire(key, self.ttl_seconds)
            
            # Deserialize
            chars_data = json.loads(data)
            characters = []
            
            for char_dict in chars_data:
                char = self._deserialize_character(char_dict)
                if char:
                    characters.append(char)
            
            print(f"📚 Loaded {len(characters)} characters for series '{series_id}'", flush=True)
            return characters
            
        except redis.RedisError as e:
            print(f"⚠️ Redis error loading characters: {e}", flush=True)
            return []
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decode error loading characters: {e}", flush=True)
            return []
        except Exception as e:
            print(f"⚠️ Error loading characters: {e}", flush=True)
            return []
    
    def save_series_characters(
        self,
        series_id: str,
        characters: List[CharacterInfo]
    ) -> bool:
        """
        Save characters for a series.
        
        Args:
            series_id: Unique identifier for the series/channel
            characters: List of CharacterInfo objects to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not series_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            key = f"{self.prefix}{series_id}"
            
            # Serialize characters
            chars_data = [self._serialize_character(c) for c in characters]
            data = json.dumps(chars_data)
            
            # Save with TTL
            self.redis.setex(key, self.ttl_seconds, data)
            
            # Update timestamp
            self.redis.setex(
                f"{self.prefix}{series_id}:updated",
                self.ttl_seconds,
                datetime.utcnow().isoformat()
            )
            
            print(f"💾 Saved {len(characters)} characters for series '{series_id}'", flush=True)
            return True
            
        except redis.RedisError as e:
            print(f"⚠️ Redis error saving characters: {e}", flush=True)
            return False
        except Exception as e:
            print(f"⚠️ Error saving characters: {e}", flush=True)
            return False
    
    def add_character(
        self,
        series_id: str,
        character: CharacterInfo
    ) -> bool:
        """
        Add a single character to a series.
        
        If a matching character already exists, merges the new info.
        
        Args:
            series_id: Unique identifier for the series/channel
            character: CharacterInfo object to add
            
        Returns:
            True if added/merged successfully, False otherwise
        """
        if not series_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            characters = self.get_series_characters(series_id)
            
            # Check for existing match
            existing = self._find_matching(character, characters)
            if existing:
                self._merge_into(existing, character)
                print(f"🔄 Merged character '{character.name}' with existing", flush=True)
            else:
                characters.append(character)
                print(f"➕ Added new character '{character.name}'", flush=True)
            
            return self.save_series_characters(series_id, characters)
            
        except Exception as e:
            print(f"⚠️ Error adding character: {e}", flush=True)
            return False
    
    def update_character(
        self,
        series_id: str,
        char_id: str,
        updates: Dict
    ) -> bool:
        """
        Update a specific character's fields.
        
        Args:
            series_id: Unique identifier for the series/channel
            char_id: Character ID to update
            updates: Dictionary of field updates
            
        Returns:
            True if updated successfully, False otherwise
        """
        if not series_id or not char_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            characters = self.get_series_characters(series_id)
            
            for char in characters:
                if char.id == char_id:
                    # Apply updates
                    if "name" in updates:
                        char.name = updates["name"]
                    if "aliases" in updates:
                        char.aliases = updates["aliases"]
                    if "description" in updates:
                        char.description = updates["description"]
                    if "role" in updates:
                        char.role = updates["role"]
                    if "visual_traits" in updates:
                        char.visual_traits = updates["visual_traits"]
                    if "confidence" in updates:
                        char.confidence = float(updates["confidence"])
                    
                    return self.save_series_characters(series_id, characters)
            
            print(f"⚠️ Character {char_id} not found in series {series_id}", flush=True)
            return False
            
        except Exception as e:
            print(f"⚠️ Error updating character: {e}", flush=True)
            return False
    
    def delete_character(
        self,
        series_id: str,
        char_id: str
    ) -> bool:
        """
        Delete a character from a series.
        
        Args:
            series_id: Unique identifier for the series/channel
            char_id: Character ID to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        if not series_id or not char_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            characters = self.get_series_characters(series_id)
            original_count = len(characters)
            
            characters = [c for c in characters if c.id != char_id]
            
            if len(characters) < original_count:
                return self.save_series_characters(series_id, characters)
            
            print(f"⚠️ Character {char_id} not found in series {series_id}", flush=True)
            return False
            
        except Exception as e:
            print(f"⚠️ Error deleting character: {e}", flush=True)
            return False
    
    def get_speaker_mapping(self, series_id: str) -> Dict[str, str]:
        """
        Get speaker label to character name mapping.
        
        Used to map generic speaker labels like "Speaker 1" to
        actual character names.
        
        Args:
            series_id: Unique identifier for the series/channel
            
        Returns:
            Dictionary mapping speaker labels to character names
        """
        if not series_id:
            return {}
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            key = f"{self.prefix}{series_id}:speakers"
            data = self.redis.get(key)
            
            if not data:
                return {}
            
            # Refresh TTL
            self.redis.expire(key, self.ttl_seconds)
            
            return json.loads(data)
            
        except Exception as e:
            print(f"⚠️ Error loading speaker mapping: {e}", flush=True)
            return {}
    
    def save_speaker_mapping(
        self,
        series_id: str,
        mapping: Dict[str, str]
    ) -> bool:
        """
        Save speaker to character mapping.
        
        Args:
            series_id: Unique identifier for the series/channel
            mapping: Dictionary mapping speaker labels to character names
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not series_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            key = f"{self.prefix}{series_id}:speakers"
            data = json.dumps(mapping)
            
            self.redis.setex(key, self.ttl_seconds, data)
            
            print(f"💾 Saved speaker mapping ({len(mapping)} entries) for series '{series_id}'", flush=True)
            return True
            
        except Exception as e:
            print(f"⚠️ Error saving speaker mapping: {e}", flush=True)
            return False
    
    def list_series(self) -> List[str]:
        """
        List all series IDs with character data.
        
        Returns:
            List of series IDs
        """
        try:
            # Find all character keys (excluding :speakers and :updated suffixes)
            keys = self.redis.keys(f"{self.prefix}*")
            
            series_ids = set()
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                # Remove prefix and any suffix
                series_part = key_str[len(self.prefix):]
                if ":" not in series_part:  # Main character key, not a suffix
                    series_ids.add(series_part)
            
            return sorted(list(series_ids))
            
        except Exception as e:
            print(f"⚠️ Error listing series: {e}", flush=True)
            return []
    
    def clear_series(self, series_id: str) -> bool:
        """
        Clear all character data for a series.
        
        Args:
            series_id: Unique identifier for the series/channel
            
        Returns:
            True if cleared successfully, False otherwise
        """
        if not series_id:
            return False
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            keys = [
                f"{self.prefix}{series_id}",
                f"{self.prefix}{series_id}:speakers",
                f"{self.prefix}{series_id}:updated"
            ]
            
            deleted = self.redis.delete(*keys)
            print(f"🗑️ Cleared {deleted} keys for series '{series_id}'", flush=True)
            return True
            
        except Exception as e:
            print(f"⚠️ Error clearing series: {e}", flush=True)
            return False
    
    def get_series_stats(self, series_id: str) -> Dict:
        """
        Get statistics for a series.
        
        Args:
            series_id: Unique identifier for the series/channel
            
        Returns:
            Dictionary with character count, last updated, etc.
        """
        if not series_id:
            return {}
        
        # Normalize to lowercase for case-insensitive matching
        series_id = series_id.strip().lower()
        
        try:
            characters = self.get_series_characters(series_id)
            speaker_mapping = self.get_speaker_mapping(series_id)
            
            updated = self.redis.get(f"{self.prefix}{series_id}:updated")
            updated_str = updated.decode() if isinstance(updated, bytes) else updated
            
            return {
                "series_id": series_id,
                "character_count": len(characters),
                "speaker_mapping_count": len(speaker_mapping),
                "last_updated": updated_str,
                "characters": [
                    {"id": c.id, "name": c.name, "role": c.role, "confidence": c.confidence}
                    for c in characters
                ]
            }
            
        except Exception as e:
            print(f"⚠️ Error getting series stats: {e}", flush=True)
            return {}
    
    # =========================================================================
    # Serialization Helpers
    # =========================================================================
    
    def _serialize_character(self, char: CharacterInfo) -> Dict:
        """Convert CharacterInfo to JSON-serializable dict."""
        data = asdict(char)
        
        # Ensure appearances are properly serialized
        if data.get("appearances"):
            data["appearances"] = [
                {
                    "start_time": a["start_time"],
                    "end_time": a["end_time"],
                    "confidence": a["confidence"],
                    "source": a["source"]
                }
                for a in data["appearances"]
            ]
        
        return data
    
    def _deserialize_character(self, data: Dict) -> Optional[CharacterInfo]:
        """Convert dict back to CharacterInfo object."""
        try:
            # Deserialize appearances
            appearances = []
            for app_data in data.get("appearances", []):
                appearances.append(CharacterAppearance(
                    start_time=float(app_data.get("start_time", 0)),
                    end_time=float(app_data.get("end_time", 0)),
                    confidence=float(app_data.get("confidence", 0.5)),
                    source=app_data.get("source", "database")
                ))
            
            return CharacterInfo(
                id=data.get("id", ""),
                name=data.get("name", ""),
                aliases=data.get("aliases", []) or [],
                description=data.get("description", "") or "",
                role=data.get("role", "supporting") or "supporting",
                visual_traits=data.get("visual_traits", []) or [],
                confidence=float(data.get("confidence", 0.5)),
                first_appearance=float(data.get("first_appearance", 0)),
                appearances=appearances,
                source_video_no=data.get("source_video_no", "") or ""
            )
            
        except Exception as e:
            print(f"⚠️ Error deserializing character: {e}", flush=True)
            return None
    
    def _find_matching(
        self,
        char: CharacterInfo,
        existing: List[CharacterInfo]
    ) -> Optional[CharacterInfo]:
        """Find a matching character using fuzzy name matching."""
        
        for existing_char in existing:
            # Check name similarity
            name_ratio = name_similarity_ratio(char.name, existing_char.name)
            
            if name_ratio >= 0.80:
                return existing_char
            
            # Check aliases
            for alias in existing_char.aliases:
                if name_similarity_ratio(char.name, alias) >= 0.80:
                    return existing_char
        
        return None
    
    def _merge_into(self, target: CharacterInfo, source: CharacterInfo):
        """Merge source character info into target."""
        # Add new aliases
        for alias in source.aliases:
            if alias.lower() not in [a.lower() for a in target.aliases]:
                if alias.lower() != target.name.lower():
                    target.aliases.append(alias)
        
        # Update description if empty
        if not target.description and source.description:
            target.description = source.description
        
        # Add visual traits
        for trait in source.visual_traits:
            if trait.lower() not in [t.lower() for t in target.visual_traits]:
                target.visual_traits.append(trait)
        
        # Take higher confidence
        target.confidence = max(target.confidence, source.confidence)
        
        # Merge appearances
        target.appearances.extend(source.appearances)

