"""
Visual Temporal Validator - Frame-level visual validation for script-clip matching.

Validates that matched video clips actually contain what the script describes,
using dense frame captioning, action progression verification, and temporal state matching.
Based on Progress-Aware Video Captioning research.
"""

import asyncio
import json
from typing import List, Dict, Optional
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
import spacy
import redis

from app.config import get_settings
from app.services.memories_client import MemoriesAIClient


class VisualTemporalValidator:
    """
    Validates script-clip matches at frame level to ensure visual content
    matches what the script describes.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.vector_config = self.settings.features.vector_matching
        self.memories_client = MemoriesAIClient()
        
        # Initialize Redis for caching
        redis_config = self.settings.redis
        try:
            self.redis_client = redis.Redis(
                host=redis_config.host,
                port=redis_config.port,
                db=redis_config.db,
                password=redis_config.password if redis_config.password else None,
                decode_responses=True
            )
            # Test connection
            self.redis_client.ping()
            self.caching_enabled = True
            print(f"✅ Redis cache enabled for frame descriptions", flush=True)
        except Exception as e:
            print(f"⚠️ Redis cache unavailable: {e}, caching disabled", flush=True)
            self.caching_enabled = False
            self.redis_client = None
        
        # Load embedding model for similarity computation
        model_name = self.vector_config.embedding_model_name
        print(f"🧠 Loading embedding model for validation: {model_name}", flush=True)
        self.embedding_model = SentenceTransformer(model_name)
        
        # Load spaCy for NLP processing
        try:
            self.nlp = spacy.load("en_core_web_sm")
            print(f"✅ spaCy model loaded for validation", flush=True)
        except OSError:
            print(f"⚠️ spaCy model not found, installing...", flush=True)
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"], check=False)
            self.nlp = spacy.load("en_core_web_sm")
    
    async def validate_match(
        self,
        script_segment: str,
        candidate_clip: Dict,
        video_no: str,
        unique_id: str = "default"
    ) -> Dict:
        """
        Multi-layer validation of a candidate clip match.
        
        Args:
            script_segment: Text of the script segment
            candidate_clip: Candidate clip dict with 'start_time', 'end_time', 'confidence'
            video_no: Video identifier
            unique_id: Workspace identifier
            
        Returns:
            Dict with:
                - is_valid: bool
                - validation_score: float (0-1)
                - issues: List[str] of detected problems
                - frame_descriptions: List[Dict] of frame-level descriptions
                - recommended_adjustment: Dict with timing adjustments
        """
        start_time = candidate_clip.get('start_time', 0)
        end_time = candidate_clip.get('end_time', 0)
        
        if end_time <= start_time:
            return {
                'is_valid': False,
                'validation_score': 0.0,
                'issues': ['Invalid clip duration (end <= start)'],
                'frame_descriptions': [],
                'recommended_adjustment': {'adjust_start_by': 0, 'recommended_start': start_time}
            }
        
        # Layer 1: Get dense frame-level visual descriptions
        # Use adaptive FPS based on clip duration for better action capture
        clip_duration = end_time - start_time
        if hasattr(self.vector_config, 'get_validation_fps'):
            fps = self.vector_config.get_validation_fps(clip_duration)
        else:
            fps = getattr(self.vector_config, 'validation_fps', 1.0)
        
        print(f"    📹 Using {fps:.1f} FPS for {clip_duration:.1f}s clip ({int(clip_duration * fps)} frames)", flush=True)
        
        frame_descriptions = await self.get_dense_frame_captions(
            video_no,
            start_time,
            end_time,
            fps=fps,
            unique_id=unique_id
        )
        
        if not frame_descriptions:
            print(f"    ⚠️ No frame descriptions retrieved for clip {start_time:.1f}s-{end_time:.1f}s", flush=True)
            return {
                'is_valid': False,
                'validation_score': 0.0,
                'issues': ['Failed to get frame descriptions'],
                'frame_descriptions': [],
                'recommended_adjustment': {'adjust_start_by': 0, 'recommended_start': start_time}
            }
        
        print(f"    📹 Analyzing {len(frame_descriptions)} frames for validation...", flush=True)
        
        # Layer 2: Verify action progression
        progression_match = self.verify_action_progression(
            script_segment,
            frame_descriptions
        )
        
        # Layer 2.5: Verify temporal direction (Fix 3)
        direction_check = self.verify_temporal_direction(
            script_segment,
            frame_descriptions
        )
        
        # Layer 3: Check temporal state alignment
        state_alignment = self.check_temporal_states(
            script_segment,
            frame_descriptions
        )
        
        # Compute final validation score with direction penalty
        progression_weight = getattr(self.vector_config, 'progression_weight', 0.4)  # Reduced from 0.5
        state_weight = getattr(self.vector_config, 'state_alignment_weight', 0.3)
        direction_weight = 0.2  # NEW: Weight for direction check
        semantic_weight = getattr(self.vector_config, 'semantic_weight', 0.1)  # Reduced
        
        progression_score = progression_match['score']
        state_score = state_alignment['score']
        direction_score = 1.0 - direction_check['penalty']  # 1.0 if no conflicts, 0.7 if conflicts
        semantic_score = candidate_clip.get('similarity_score', 0.5)
        
        validation_score = (
            progression_score * progression_weight +
            state_score * state_weight +
            direction_score * direction_weight +
            semantic_score * semantic_weight
        )
        
        # Enhanced logging
        print(f"    📊 Validation scores: progression={progression_score:.2f}, "
              f"state={state_score:.2f}, direction={direction_score:.2f}, semantic={semantic_score:.2f}, "
              f"final={validation_score:.2f}", flush=True)
        
        # Check threshold - also reject if direction conflicts exist
        threshold = getattr(self.vector_config, 'validation_threshold', 0.80)  # Raised default
        is_valid = (
            validation_score >= threshold and
            not direction_check['has_direction_conflicts'] and
            not progression_match.get('has_hallucination', False)
        )
        
        if is_valid:
            print(f"    ✅ Validation passed (score: {validation_score:.2f} >= {threshold:.2f})", flush=True)
        else:
            reject_reasons = []
            if validation_score < threshold:
                reject_reasons.append(f"score {validation_score:.2f} < {threshold:.2f}")
            if direction_check['has_direction_conflicts']:
                reject_reasons.append("direction conflict")
            if progression_match.get('has_hallucination', False):
                reject_reasons.append("temporal hallucination")
            print(f"    ❌ Validation failed ({', '.join(reject_reasons)})", flush=True)
        
        # Identify issues (updated to include direction check)
        issues = self._identify_issues(
            progression_match,
            state_alignment,
            frame_descriptions,
            direction_check
        )
        
        # Recommend timing adjustment
        recommended_adjustment = self._recommend_adjustment(
            script_segment,
            frame_descriptions,
            candidate_clip
        )
        
        return {
            'is_valid': is_valid,
            'validation_score': validation_score,
            'issues': issues,
            'frame_descriptions': frame_descriptions,
            'recommended_adjustment': recommended_adjustment,
            'progression_match': progression_match,
            'state_alignment': state_alignment,
            'direction_check': direction_check
        }
    
    def _get_cache_key(self, video_no: str, start_time: float, end_time: float) -> str:
        """Generate cache key for frame description."""
        return f"frame_desc:{video_no}:{start_time:.2f}:{end_time:.2f}"
    
    def _build_frame_specific_prompt(self, timestamp: float) -> str:
        """
        Build a frame-specific prompt that captures EXACT state at a timestamp.
        
        This addresses Issue #2: prompts that ask for summaries instead of exact frame state.
        The prompt explicitly asks for CURRENT state only, not before/after.
        
        Args:
            timestamp: The exact timestamp in seconds
            
        Returns:
            Prompt string for frame-specific state query
        """
        return f"""At EXACTLY {timestamp:.2f} seconds in the video:

1. What is the primary character CURRENTLY doing at THIS INSTANT?
   - NOT what they were doing before
   - NOT what they're about to do
   - What they ARE doing RIGHT NOW at this exact moment

2. What POSITION/POSE are they in at THIS EXACT MOMENT?
   - Body position (standing, sitting, crouching, etc.)
   - Limb positions (arms raised, lowered, extended, etc.)
   - Facing direction (toward camera, away, left, right)

3. What is the STATE of key objects at THIS TIMESTAMP?
   - Current location of objects
   - Current condition/position
   - Who is holding/touching them

Be SNAPSHOT-SPECIFIC. Describe only the CURRENT FRAME at {timestamp:.2f}s.
Do NOT describe what happened before or what happens next.
Be concise and factual."""
    
    async def get_frame_state_at_timestamp(
        self,
        video_no: str,
        timestamp: float,
        unique_id: str = "default"
    ) -> str:
        """
        Get EXACT visual state at a specific timestamp (100ms window).
        
        This is used for precise state verification where we need to know
        exactly what's visible at a specific moment.
        
        Args:
            video_no: Video identifier
            timestamp: Exact timestamp in seconds
            unique_id: Workspace identifier
            
        Returns:
            Frame-specific description of current state
        """
        prompt = self._build_frame_specific_prompt(timestamp)
        
        # Query tiny 100ms window for frame-specific state
        return await self.memories_client.get_visual_description(
            video_no=video_no,
            start_time=timestamp,
            end_time=timestamp + 0.1,  # 100ms window for single frame
            unique_id=unique_id,
            custom_prompt=prompt
        )
    
    async def get_dense_frame_captions(
        self,
        video_no: str,
        start_time: float,
        end_time: float,
        fps: float = 1.0,
        unique_id: str = "default"
    ) -> List[Dict]:
        """
        Get detailed frame-by-frame descriptions using Memories.ai.
        
        Args:
            video_no: Video identifier
            start_time: Clip start time in seconds
            end_time: Clip end time in seconds
            fps: Frames per second to sample (default 1.0 = 1 frame/second)
            unique_id: Workspace identifier
            
        Returns:
            List of frame description dicts with 'timestamp', 'description', 'frame_index'
        """
        duration = end_time - start_time
        num_frames = max(1, int(duration * fps))
        frame_descriptions = []
        
        # Prepare batch requests for parallel processing
        frame_requests = []
        for i in range(num_frames):
            timestamp = start_time + (i / fps)
            frame_end = min(timestamp + (1 / fps), end_time)
            
            frame_requests.append({
                'index': i,
                'start': timestamp,
                'end': frame_end
            })
        
        # Process frames (with caching and rate limiting)
        batch_size = 5
        cache_misses = []
        
        # Check cache first
        for frame_req in frame_requests:
            cache_key = self._get_cache_key(video_no, frame_req['start'], frame_req['end'])
            
            if self.caching_enabled:
                try:
                    cached_desc = self.redis_client.get(cache_key)
                    if cached_desc:
                        frame_descriptions.append({
                            'timestamp': frame_req['start'],
                            'description': cached_desc,
                            'frame_index': frame_req['index']
                        })
                        continue
                except Exception as e:
                    print(f"⚠️ Cache read error: {e}", flush=True)
            
            # Cache miss - need to fetch
            cache_misses.append(frame_req)
        
        # Fetch missing descriptions (with rate limiting)
        for batch_start in range(0, len(cache_misses), batch_size):
            batch = cache_misses[batch_start:batch_start + batch_size]
            
            # Process batch in parallel
            tasks = []
            for frame_req in batch:
                # Use frame-specific prompt for accurate state capture
                frame_prompt = self._build_frame_specific_prompt(frame_req['start'])
                task = self.memories_client.get_visual_description(
                    video_no=video_no,
                    start_time=frame_req['start'],
                    end_time=frame_req['end'],
                    unique_id=unique_id,
                    custom_prompt=frame_prompt
                )
                tasks.append((frame_req, task))
            
            # Wait for batch to complete
            for frame_req, task in tasks:
                try:
                    description = await task
                    
                    # Cache the result (24 hour TTL)
                    if self.caching_enabled:
                        cache_key = self._get_cache_key(video_no, frame_req['start'], frame_req['end'])
                        try:
                            self.redis_client.setex(cache_key, 86400, description)  # 24 hours
                        except Exception as e:
                            print(f"⚠️ Cache write error: {e}", flush=True)
                    
                    frame_descriptions.append({
                        'timestamp': frame_req['start'],
                        'description': description,
                        'frame_index': frame_req['index']
                    })
                except Exception as e:
                    print(f"⚠️ Failed to get frame description for {frame_req['start']:.1f}s: {e}", flush=True)
                    # Use empty description as fallback
                    frame_descriptions.append({
                        'timestamp': frame_req['start'],
                        'description': "",
                        'frame_index': frame_req['index']
                    })
        
        if cache_misses and self.caching_enabled:
            print(f"  💾 Cached {len(cache_misses)} frame descriptions", flush=True)
        
        return sorted(frame_descriptions, key=lambda x: x['timestamp'])
    
    def verify_action_progression(
        self,
        script_text: str,
        frame_descriptions: List[Dict]
    ) -> Dict:
        """
        Verify if the visual progression matches script narrative.
        
        Args:
            script_text: Script segment text
            frame_descriptions: List of frame description dicts
            
        Returns:
            Dict with 'score', 'has_hallucination', 'aligned_actions', 'visual_sequence'
        """
        # Extract action verbs and states from script
        script_actions = self._extract_action_sequence(script_text)
        
        # Extract actual visual actions from frame descriptions
        visual_actions = [
            self._extract_action_sequence(frame['description'])
            for frame in frame_descriptions
            if frame.get('description')
        ]
        
        if not visual_actions:
            return {
                'score': 0.0,
                'has_hallucination': True,
                'aligned_actions': script_actions,
                'visual_sequence': []
            }
        
        # Compute progression alignment
        alignment_score = self._compute_temporal_alignment(
            script_actions,
            visual_actions
        )
        
        # Detect temporal hallucination
        has_hallucination = self._detect_temporal_hallucination(
            script_actions,
            visual_actions
        )
        
        return {
            'score': alignment_score,
            'has_hallucination': has_hallucination,
            'aligned_actions': script_actions,
            'visual_sequence': visual_actions
        }
    
    def verify_temporal_direction(
        self,
        script_text: str,
        frame_descriptions: List[Dict]
    ) -> Dict:
        """
        Verify actions flow in the correct temporal direction.
        
        Detects conflicts where script describes one action but visual shows opposite
        (e.g., script says "enters" but visual shows "exits").
        
        Args:
            script_text: Script segment text
            frame_descriptions: List of frame description dicts
            
        Returns:
            Dict with 'has_direction_conflicts', 'conflicts', 'penalty'
        """
        # Define opposite action pairs
        opposites = {
            'enter': ['exit', 'leave', 'depart'],
            'exit': ['enter', 'arrive', 'approach'],
            'leave': ['arrive', 'enter', 'come'],
            'arrive': ['leave', 'exit', 'depart'],
            'come': ['go', 'leave', 'depart'],
            'go': ['come', 'arrive', 'return'],
            'raise': ['lower', 'drop', 'put down'],
            'lower': ['raise', 'lift', 'pick up'],
            'lift': ['drop', 'lower', 'put down'],
            'drop': ['lift', 'raise', 'pick up'],
            'pick up': ['put down', 'drop', 'set down'],
            'put down': ['pick up', 'lift', 'grab'],
            'open': ['close', 'shut'],
            'close': ['open'],
            'start': ['finish', 'end', 'stop', 'complete'],
            'finish': ['start', 'begin'],
            'begin': ['end', 'finish', 'stop'],
            'end': ['begin', 'start'],
            'approach': ['retreat', 'withdraw', 'back away'],
            'retreat': ['approach', 'advance'],
            'advance': ['retreat', 'withdraw'],
            'stand': ['sit', 'lie', 'fall'],
            'sit': ['stand', 'rise'],
            'rise': ['fall', 'sit', 'lie'],
            'fall': ['rise', 'stand', 'get up'],
            'attack': ['defend', 'retreat'],
            'defend': ['attack'],
            'push': ['pull'],
            'pull': ['push'],
        }
        
        # Check if direction checking is enabled
        if not getattr(self.vector_config, 'enable_direction_checking', True):
            return {'has_direction_conflicts': False, 'conflicts': [], 'penalty': 0.0}
        
        # Extract action verbs from script
        script_doc = self.nlp(script_text)
        script_verbs = []
        for token in script_doc:
            if token.pos_ == "VERB":
                script_verbs.append(token.lemma_.lower())
        
        # Check each frame for opposite actions
        direction_conflicts = []
        
        for frame in frame_descriptions:
            if not frame.get('description'):
                continue
            
            frame_doc = self.nlp(frame['description'])
            frame_verbs = [token.lemma_.lower() for token in frame_doc if token.pos_ == "VERB"]
            
            for script_verb in script_verbs:
                if script_verb in opposites:
                    opposite_verbs = opposites[script_verb]
                    for frame_verb in frame_verbs:
                        if frame_verb in opposite_verbs or any(opp in frame_verb for opp in opposite_verbs):
                            direction_conflicts.append({
                                'timestamp': frame.get('timestamp', 0),
                                'script_action': script_verb,
                                'conflicting_action': frame_verb,
                                'frame_description': frame['description'][:100]
                            })
        
        has_conflicts = len(direction_conflicts) > 0
        
        # Debug logging if enabled
        if has_conflicts and getattr(self.vector_config, 'enable_validation_debug', False):
            print(f"    ⚠️ Direction conflicts detected: {len(direction_conflicts)}", flush=True)
            for conflict in direction_conflicts[:2]:  # Show first 2
                print(f"      Script: '{conflict['script_action']}' vs Visual: '{conflict['conflicting_action']}' at {conflict['timestamp']:.1f}s", flush=True)
        
        return {
            'has_direction_conflicts': has_conflicts,
            'conflicts': direction_conflicts,
            'penalty': 0.3 if has_conflicts else 0.0
        }
    
    def _extract_action_sequence(self, text: str) -> Dict:
        """
        Extract action verbs and progression keywords from text.
        
        Returns:
            Dict with 'actions', 'states', 'temporal_markers'
        """
        if not text:
            return {'actions': [], 'states': [], 'temporal_markers': []}
        
        doc = self.nlp(text)
        
        actions = []
        for token in doc:
            if token.pos_ == "VERB":
                # Get verb with its modifiers
                action_phrase = " ".join([
                    child.text for child in token.subtree
                ])
                actions.append(action_phrase.lower())
        
        # Also extract state indicators
        state_keywords = ["starts", "begins", "continues", "finishes", 
                         "already", "still", "about to", "just", "going to", "will"]
        words = text.lower().split()
        states = [word for word in words if any(kw in word for kw in state_keywords)]
        
        return {
            'actions': actions,
            'states': states,
            'temporal_markers': states
        }
    
    def _compute_temporal_alignment(
        self,
        script_actions: Dict,
        visual_actions: List[Dict]
    ) -> float:
        """
        Check if visual sequence matches script progression.
        
        Returns alignment score (0-1).
        """
        if not script_actions.get('actions'):
            return 0.5  # Neutral score if no actions in script
        
        # Embed script actions
        script_text = " ".join(script_actions['actions'])
        script_embedding = self.embedding_model.encode(script_text)
        
        # Find best matching visual frame sequence
        visual_embeddings = []
        for va in visual_actions:
            if va.get('actions'):
                vis_text = " ".join(va['actions'])
                vis_emb = self.embedding_model.encode(vis_text)
                visual_embeddings.append(vis_emb)
        
        if not visual_embeddings:
            return 0.0
        
        # Compute progression score (similarity should increase over time for good progression)
        similarities = []
        for vis_emb in visual_embeddings:
            sim = cosine_similarity(
                script_embedding.reshape(1, -1),
                vis_emb.reshape(1, -1)
            )[0][0]
            similarities.append(sim)
        
        # Check if similarity increases over time (good progression)
        if len(similarities) > 1:
            is_progressive = all(
                similarities[i] <= similarities[i+1]
                for i in range(len(similarities)-1)
            )
        else:
            is_progressive = True
        
        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
        
        # Penalize if not progressive
        if not is_progressive and len(similarities) > 2:
            avg_similarity *= 0.7
        
        return avg_similarity
    
    def _detect_temporal_hallucination(
        self,
        script_actions: Dict,
        visual_actions: List[Dict]
    ) -> bool:
        """
        Detect if script describes actions NOT visible in frames.
        
        Returns True if hallucination detected.
        """
        script_states = set(script_actions.get('states', []))
        
        hallucination_indicators = {
            'already': 'past',
            'just': 'past',
            'about to': 'future',
            'going to': 'future',
            'will': 'future'
        }
        
        # Check for temporal mismatches
        for state in script_states:
            for indicator, expected_time in hallucination_indicators.items():
                if indicator in state.lower():
                    # Get visual states
                    visual_states = [
                        word for va in visual_actions
                        for word in va.get('states', [])
                    ]
                    
                    if expected_time == 'future':
                        # Script says "about to X" but visual shows "already X"
                        if any('already' in vs or 'just' in vs for vs in visual_states):
                            return True
                    
                    if expected_time == 'past':
                        # Script says "already X" but visual shows "about to X"
                        if any('about to' in vs or 'going to' in vs or 'will' in vs for vs in visual_states):
                            return True
        
        return False
    
    def check_temporal_states(
        self,
        script_text: str,
        frame_descriptions: List[Dict]
    ) -> Dict:
        """
        Verify object/character states match at specific timestamps.
        
        Returns dict with 'score' and 'entity_matches'.
        """
        # Extract key objects/characters from script
        script_entities = self._extract_entities(script_text)
        
        if not script_entities:
            return {'score': 0.5, 'entity_matches': []}
        
        # Check state consistency across frames
        state_matches = []
        
        for entity in script_entities:
            # Find entity mentions in frame descriptions
            entity_frames = []
            for frame in frame_descriptions:
                desc = frame.get('description', '')
                if entity.lower() in desc.lower():
                    state = self._extract_entity_state(entity, desc)
                    entity_frames.append({
                        'frame': frame,
                        'state': state
                    })
            
            if entity_frames:
                # Verify states are consistent with script
                script_state = self._extract_entity_state(entity, script_text)
                
                # Count matching vs non-matching frames
                matches = sum(
                    1 for ef in entity_frames
                    if self._states_compatible(script_state, ef['state'])
                )
                
                match_ratio = matches / len(entity_frames) if entity_frames else 0
                state_matches.append({
                    'entity': entity,
                    'match_ratio': match_ratio,
                    'script_state': script_state,
                    'visual_states': [ef['state'] for ef in entity_frames]
                })
        
        if not state_matches:
            return {'score': 0.5, 'entity_matches': []}
        
        avg_state_alignment = sum(sm['match_ratio'] for sm in state_matches) / len(state_matches)
        
        return {
            'score': avg_state_alignment,
            'entity_matches': state_matches
        }
    
    def _extract_entities(self, text: str) -> List[str]:
        """Extract key objects/characters from text."""
        if not text:
            return []
        
        doc = self.nlp(text)
        
        # Extract named entities
        entities = [
            ent.text for ent in doc.ents
            if ent.label_ in ['PERSON', 'ORG', 'GPE', 'PRODUCT']
        ]
        
        # Also extract common nouns that might be key objects
        nouns = [
            chunk.text for chunk in doc.noun_chunks
            if chunk.root.pos_ == 'NOUN' and len(chunk.text.split()) <= 3
        ]
        
        # Combine and deduplicate
        all_entities = list(set(entities + nouns))
        
        # Filter out very common words
        common_words = {'the', 'a', 'an', 'this', 'that', 'it', 'they', 'he', 'she', 'we', 'you'}
        filtered = [e for e in all_entities if e.lower() not in common_words]
        
        return filtered[:10]  # Limit to top 10 entities
    
    def _extract_entity_state(self, entity: str, text: str) -> str:
        """Extract the state/condition of an entity from text."""
        if not text or not entity:
            return "not mentioned"
        
        doc = self.nlp(text)
        
        # Find sentences mentioning the entity
        entity_sentences = [
            sent.text for sent in doc.sents
            if entity.lower() in sent.text.lower()
        ]
        
        if not entity_sentences:
            return "not mentioned"
        
        # Extract state descriptors (adjectives, prepositions, verbs)
        state_words = []
        for sent in entity_sentences:
            sent_doc = self.nlp(sent)
            for token in sent_doc:
                if token.pos_ in ['ADJ', 'ADP', 'VERB']:
                    # Check if related to the entity
                    if entity.lower() in token.head.text.lower() or entity.lower() in token.text.lower():
                        state_words.append(token.text)
        
        return " ".join(state_words) if state_words else "present"
    
    def _states_compatible(self, state1: str, state2: str) -> bool:
        """
        Check if two state descriptions are compatible.
        
        Uses stricter threshold (0.8) and explicit position conflict detection.
        """
        if not state1 or not state2 or state1 == "not mentioned" or state2 == "not mentioned":
            return state1 == state2
        
        # Get stricter threshold from config (default 0.8, raised from 0.6)
        threshold = getattr(self.vector_config, 'state_compatibility_threshold', 0.8)
        
        # Check for explicit position/direction conflicts FIRST
        # These are definitive mismatches regardless of embedding similarity
        position_conflicts = {
            'up': ['down', 'lowered', 'dropped'],
            'down': ['up', 'raised', 'lifted'],
            'raised': ['lowered', 'down', 'dropped'],
            'lowered': ['raised', 'up', 'lifted'],
            'lifted': ['dropped', 'lowered', 'down'],
            'dropped': ['lifted', 'raised', 'up'],
            'forward': ['backward', 'back', 'behind'],
            'backward': ['forward', 'ahead', 'front'],
            'open': ['closed', 'shut'],
            'closed': ['open', 'opened'],
            'left': ['right'],
            'right': ['left'],
            'standing': ['sitting', 'lying', 'crouching', 'kneeling'],
            'sitting': ['standing', 'lying'],
            'lying': ['standing', 'sitting'],
            'inside': ['outside'],
            'outside': ['inside'],
            'high': ['low'],
            'low': ['high'],
            'near': ['far', 'distant'],
            'far': ['near', 'close'],
        }
        
        state1_lower = state1.lower()
        state2_lower = state2.lower()
        
        for position, opposites in position_conflicts.items():
            if position in state1_lower:
                if any(opp in state2_lower for opp in opposites):
                    if getattr(self.vector_config, 'enable_validation_debug', False):
                        print(f"      ⚠️ Position conflict: '{position}' in script vs {opposites} in visual", flush=True)
                    return False  # Definitive conflict
            # Check reverse direction too
            if position in state2_lower:
                if any(opp in state1_lower for opp in opposites):
                    if getattr(self.vector_config, 'enable_validation_debug', False):
                        print(f"      ⚠️ Position conflict: '{position}' in visual vs {opposites} in script", flush=True)
                    return False  # Definitive conflict
        
        # Compute semantic similarity with stricter threshold
        emb1 = self.embedding_model.encode(state1)
        emb2 = self.embedding_model.encode(state2)
        
        similarity = cosine_similarity(
            emb1.reshape(1, -1),
            emb2.reshape(1, -1)
        )[0][0]
        
        return similarity >= threshold
    
    def _identify_issues(
        self,
        progression_match: Dict,
        state_alignment: Dict,
        frame_descriptions: List[Dict],
        direction_check: Dict = None
    ) -> List[str]:
        """Identify specific synchronization issues."""
        issues = []
        
        if progression_match.get('has_hallucination'):
            issues.append("TEMPORAL_HALLUCINATION: Script describes actions not visible in frames")
        
        if progression_match.get('score', 0) < 0.6:
            issues.append("POOR_PROGRESSION: Visual sequence doesn't match script narrative flow")
        
        if state_alignment.get('score', 0) < 0.5:
            issues.append("STATE_MISMATCH: Object/character states don't match script description")
        
        # Check for timing issues
        if len(frame_descriptions) < 3:
            issues.append("CLIP_TOO_SHORT: Not enough frames to capture full action")
        
        # Check for direction conflicts (Fix 3)
        if direction_check and direction_check.get('has_direction_conflicts'):
            conflicts = direction_check.get('conflicts', [])
            if conflicts:
                first_conflict = conflicts[0]
                issues.append(
                    f"DIRECTION_CONFLICT: Script action '{first_conflict['script_action']}' "
                    f"conflicts with visual action '{first_conflict['conflicting_action']}' "
                    f"at {first_conflict['timestamp']:.1f}s"
                )
        
        return issues
    
    def _recommend_adjustment(
        self,
        script_segment: str,
        frame_descriptions: List[Dict],
        candidate_clip: Dict
    ) -> Dict:
        """
        Recommend timing adjustments to improve sync.
        
        Returns dict with 'adjust_start_by', 'recommended_start', 'confidence', 'reason'.
        """
        # Find the frame that best matches the START of the script action
        script_start_action = self._extract_action_sequence(script_segment)
        
        if not script_start_action.get('actions'):
            return {
                'adjust_start_by': 0,
                'recommended_start': candidate_clip.get('start_time', 0),
                'confidence': 0.5,
                'reason': 'No actions detected in script'
            }
        
        best_start_frame = None
        best_start_score = 0
        
        for frame in frame_descriptions:
            if not frame.get('description'):
                continue
            
            frame_actions = self._extract_action_sequence(frame['description'])
            score = self._compute_action_similarity(
                script_start_action,
                frame_actions
            )
            
            if score > best_start_score:
                best_start_score = score
                best_start_frame = frame
        
        if best_start_frame and best_start_score > 0.5:
            time_adjustment = best_start_frame['timestamp'] - candidate_clip.get('start_time', 0)
            
            return {
                'adjust_start_by': time_adjustment,
                'recommended_start': best_start_frame['timestamp'],
                'confidence': best_start_score,
                'reason': f"Action begins at frame {best_start_frame['frame_index']}"
            }
        
        return {
            'adjust_start_by': 0,
            'recommended_start': candidate_clip.get('start_time', 0),
            'confidence': best_start_score if best_start_frame else 0.0,
            'reason': 'No better start point found'
        }
    
    def _compute_action_similarity(self, actions1: Dict, actions2: Dict) -> float:
        """Compare two action sequences for similarity."""
        acts1 = actions1.get('actions', [])
        acts2 = actions2.get('actions', [])
        
        if not acts1 or not acts2:
            return 0.0
        
        text1 = " ".join(acts1)
        text2 = " ".join(acts2)
        
        emb1 = self.embedding_model.encode(text1)
        emb2 = self.embedding_model.encode(text2)
        
        return cosine_similarity(emb1.reshape(1, -1), emb2.reshape(1, -1))[0][0]

