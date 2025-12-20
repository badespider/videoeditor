"""
Visual Entailment Verifier - Verifies if visual content ENTAILS script descriptions.

This module implements Visual Entailment verification inspired by:
- Chen et al. "Explainable Video Entailment with Grounded Visual Evidence" (ICCV 2021)
- VidHalluc (CVPR 2025), ELV-Halluc (arXiv 2025) hallucination research

The key insight is that semantic similarity is NOT sufficient for video-text matching.
A clip can contain the same objects/characters but show completely different actions.
Visual Entailment verifies that the visual content DIRECTLY SHOWS what the script describes.

Entailment Classifications:
- ENTAIL: Visual frames DIRECTLY SHOW the described action/state happening
- CONTRADICT: Visual frames show something INCOMPATIBLE with the claim
- NEUTRAL: Frames don't provide enough evidence either way
"""

import asyncio
import hashlib
import json
import re
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import redis
import spacy

from app.config import get_settings


class EntailmentJudgment(str, Enum):
    """Entailment classification result."""
    ENTAIL = "ENTAIL"
    CONTRADICT = "CONTRADICT"
    NEUTRAL = "NEUTRAL"


@dataclass
class EntailmentResult:
    """Result of visual entailment verification."""
    judgment: EntailmentJudgment
    confidence: float
    evidence: str
    contradictions: List[str]
    frame_analyses: List[Dict]
    
    def to_dict(self) -> Dict:
        return {
            'entailment': self.judgment.value,
            'confidence': self.confidence,
            'evidence': self.evidence,
            'contradictions': self.contradictions,
            'frame_analyses': self.frame_analyses
        }


# Global NLP model cache
_nlp_model = None


def _get_nlp_model():
    """Load spaCy model (cached globally)."""
    global _nlp_model
    if _nlp_model is None:
        print("🧠 Loading spaCy model for entailment verification...", flush=True)
        _nlp_model = spacy.load("en_core_web_sm")
        print("✅ spaCy model loaded for entailment verification.", flush=True)
    return _nlp_model


class VisualEntailmentVerifier:
    """
    Verifies if the visual content ENTAILS the script description.
    
    This goes beyond simple object detection to verify that:
    1. The described AGENT is visible
    2. The described ACTION is being performed
    3. The ACTION is being performed BY the correct AGENT
    4. The temporal relationship matches (if applicable)
    
    This addresses the "Semantic Aggregation Hallucination" problem where
    LVMs correctly perceive individual elements but fail at binding them.
    """
    
    def __init__(self, memories_client, config):
        """
        Initialize the visual entailment verifier.
        
        Args:
            memories_client: MemoriesAIClient instance for visual queries
            config: VectorMatchingConfig with entailment settings
        """
        self.memories = memories_client
        self.config = config
        self.nlp = _get_nlp_model()
        
        # Get settings
        self.settings = get_settings()
        
        # Initialize Redis for caching
        self.redis_client = None
        try:
            self.redis_client = redis.Redis(
                host=self.settings.redis.host,
                port=self.settings.redis.port,
                db=self.settings.redis.db,
                password=self.settings.redis.password if self.settings.redis.password else None,
                decode_responses=True
            )
            self.redis_client.ping()
            print("✅ Redis connected for entailment cache.", flush=True)
        except Exception as e:
            print(f"⚠️ Redis not available for entailment cache: {e}", flush=True)
            self.redis_client = None
        
        # Get config values with defaults
        self.frame_samples = getattr(config, 'entailment_frame_samples', 5)
        self.threshold = getattr(config, 'entailment_threshold', 0.70)
        
        print(f"🔬 VisualEntailmentVerifier initialized (samples={self.frame_samples}, threshold={self.threshold})", flush=True)
    
    def _sample_frames_adaptive(
        self,
        start_time: float,
        end_time: float,
        min_frames: int = 5,
        max_frames: int = 7
    ) -> List[Dict]:
        """
        Adaptively sample frames across the clip duration.
        
        For short clips (<5s): sample more densely
        For long clips (>15s): sample at key points (start, 1/4, 1/2, 3/4, end)
        
        Args:
            start_time: Clip start time in seconds
            end_time: Clip end time in seconds
            min_frames: Minimum frames to sample
            max_frames: Maximum frames to sample
            
        Returns:
            List of frame dicts with 'timestamp' and 'index'
        """
        duration = end_time - start_time
        
        if duration <= 0:
            return [{'timestamp': start_time, 'index': 0}]
        
        # Adaptive frame count based on duration
        if duration < 3:
            num_frames = min(min_frames, max(2, int(duration * 2)))
        elif duration < 10:
            num_frames = min_frames
        else:
            num_frames = max_frames
        
        # Generate evenly spaced timestamps
        frames = []
        for i in range(num_frames):
            if num_frames == 1:
                t = start_time + duration / 2
            else:
                t = start_time + (i / (num_frames - 1)) * duration
            frames.append({
                'timestamp': round(t, 2),
                'index': i
            })
        
        return frames
    
    def _extract_script_claims(self, script_segment: str) -> List[Dict]:
        """
        Extract testable claims from the script segment.
        
        A claim is an agent-action-object triple that can be verified visually.
        
        Args:
            script_segment: The script text to analyze
            
        Returns:
            List of claim dicts with 'agent', 'action', 'object', 'full_text'
        """
        doc = self.nlp(script_segment)
        claims = []
        
        for token in doc:
            if token.pos_ == "VERB" and token.dep_ in ("ROOT", "conj", "advcl", "relcl"):
                # Find subject (agent)
                subjects = []
                for child in token.children:
                    if child.dep_ in ("nsubj", "nsubjpass"):
                        # Get full noun phrase
                        subject_phrase = " ".join([w.text for w in child.subtree])
                        subjects.append(subject_phrase)
                
                # Find object (patient)
                objects = []
                for child in token.children:
                    if child.dep_ in ("dobj", "pobj", "attr"):
                        object_phrase = " ".join([w.text for w in child.subtree])
                        objects.append(object_phrase)
                
                # Create claims for each subject
                for subj in subjects:
                    claim = {
                        'agent': subj.strip(),
                        'action': token.lemma_.lower(),
                        'object': objects[0].strip() if objects else None,
                        'full_text': f"{subj} {token.text}" + (f" {objects[0]}" if objects else "")
                    }
                    claims.append(claim)
        
        # If no structured claims found, treat whole segment as a claim
        if not claims:
            claims.append({
                'agent': None,
                'action': None,
                'object': None,
                'full_text': script_segment
            })
        
        return claims
    
    def _build_entailment_prompt(
        self,
        script_segment: str,
        claims: List[Dict],
        frames: List[Dict],
        start_time: float,
        end_time: float
    ) -> str:
        """
        Build the entailment verification prompt for Memories.ai.
        
        This prompt asks the LVMM to act as a precise video-text entailment judge,
        determining if the visual evidence ENTAILS, CONTRADICTS, or is NEUTRAL to
        the script claim.
        
        Args:
            script_segment: The script text being verified
            claims: Extracted agent-action claims
            frames: Frame timestamps to analyze
            start_time: Clip start time
            end_time: Clip end time
            
        Returns:
            Entailment verification prompt string
        """
        # Format claims for the prompt
        claims_text = "\n".join([
            f"  - Claim {i+1}: {c['full_text']}"
            for i, c in enumerate(claims[:3])  # Limit to 3 claims
        ])
        
        # Format frame timestamps
        frame_times = ", ".join([f"{f['timestamp']:.1f}s" for f in frames])
        
        return f"""You are a precise VIDEO-TEXT ENTAILMENT JUDGE.

SCRIPT CLAIM TO VERIFY:
"{script_segment}"

KEY CLAIMS TO CHECK:
{claims_text}

VIDEO SEGMENT: {start_time:.1f}s to {end_time:.1f}s
SAMPLE FRAMES: {frame_times}

YOUR TASK: Determine if the visual evidence in this video segment ENTAILS, CONTRADICTS, or is NEUTRAL to the script claim.

DEFINITIONS:
- ENTAIL: The visual frames DIRECTLY SHOW the described action/state happening. The agent performs the action.
- CONTRADICT: The visual frames show something INCOMPATIBLE with the claim (different action, different agent doing it, opposite state).
- NEUTRAL: Frames don't provide enough evidence either way (agent not visible, action unclear, etc.)

FOR EACH FRAME, analyze:
1. Is the claimed AGENT visible? (YES/NO, describe if visible)
2. What ACTION is the agent ACTUALLY performing? (be specific)
3. Does this match the claimed action? (YES/NO/PARTIAL)
4. Any CONTRADICTIONS with the script? (list specific mismatches)

CRITICAL BINDING CHECK:
- If script says "A does X", verify A is doing X, not B doing X
- If script says "A attacks B", verify A is the attacker, not B attacking A
- If script says "A enters", verify A is entering, not exiting

FINAL JUDGMENT (required):
ENTAILMENT: [ENTAIL/CONTRADICT/NEUTRAL]
CONFIDENCE: [0.0 to 1.0, where 1.0 = absolute certainty]
EVIDENCE: [Which specific frames/moments support your judgment]
CONTRADICTIONS: [List any specific mismatches between script and visual, or "None"]

Be LITERAL and PRECISE. Do NOT infer actions not visible. Do NOT assume based on context."""
    
    def _parse_entailment_response(self, response: str) -> Dict:
        """
        Parse the LVMM response to extract entailment judgment.
        
        Args:
            response: Raw response from Memories.ai
            
        Returns:
            Dict with 'judgment', 'confidence', 'evidence', 'contradictions', 'frame_details'
        """
        response_upper = response.upper()
        response_lower = response.lower()
        
        # Default values
        result = {
            'judgment': EntailmentJudgment.NEUTRAL,
            'confidence': 0.5,
            'evidence': '',
            'contradictions': [],
            'frame_details': response
        }
        
        # Extract judgment
        # Look for explicit ENTAILMENT: line first
        entailment_match = re.search(r'ENTAILMENT:\s*(ENTAIL|CONTRADICT|NEUTRAL)', response_upper)
        if entailment_match:
            judgment_str = entailment_match.group(1)
            if judgment_str == "ENTAIL":
                result['judgment'] = EntailmentJudgment.ENTAIL
            elif judgment_str == "CONTRADICT":
                result['judgment'] = EntailmentJudgment.CONTRADICT
            else:
                result['judgment'] = EntailmentJudgment.NEUTRAL
        else:
            # Fallback: count positive vs negative indicators
            entail_indicators = ['directly shows', 'clearly shows', 'matches', 'confirms', 
                                 'entail', 'visible', 'performing', 'is doing']
            contradict_indicators = ['contradicts', 'opposite', 'instead', 'not visible',
                                     'different action', 'mismatch', 'incompatible', 'wrong']
            
            entail_count = sum(1 for ind in entail_indicators if ind in response_lower)
            contradict_count = sum(1 for ind in contradict_indicators if ind in response_lower)
            
            if contradict_count > entail_count:
                result['judgment'] = EntailmentJudgment.CONTRADICT
            elif entail_count > contradict_count + 1:  # Require stronger evidence for ENTAIL
                result['judgment'] = EntailmentJudgment.ENTAIL
            else:
                result['judgment'] = EntailmentJudgment.NEUTRAL
        
        # Extract confidence
        confidence_match = re.search(r'CONFIDENCE:\s*(\d+\.?\d*)', response_upper)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                # Normalize if given as percentage
                if confidence > 1.0:
                    confidence = confidence / 100.0
                result['confidence'] = max(0.0, min(1.0, confidence))
            except ValueError:
                pass
        
        # Extract evidence
        evidence_match = re.search(r'EVIDENCE:\s*(.+?)(?=CONTRADICTIONS:|$)', response, re.IGNORECASE | re.DOTALL)
        if evidence_match:
            result['evidence'] = evidence_match.group(1).strip()[:500]  # Limit length
        
        # Extract contradictions
        contradictions_match = re.search(r'CONTRADICTIONS:\s*(.+?)(?=$)', response, re.IGNORECASE | re.DOTALL)
        if contradictions_match:
            contradictions_text = contradictions_match.group(1).strip()
            if contradictions_text.lower() not in ('none', 'none.', 'n/a', ''):
                # Split by common delimiters
                contras = re.split(r'[;\n\-•]', contradictions_text)
                result['contradictions'] = [c.strip() for c in contras if c.strip() and len(c.strip()) > 3][:5]
        
        return result
    
    def _get_cache_key(self, video_no: str, start_time: float, end_time: float, script_hash: str) -> str:
        """Generate cache key for entailment query."""
        return f"entailment:{video_no}:{start_time:.2f}:{end_time:.2f}:{script_hash}"
    
    async def verify_entailment(
        self,
        clip_info: Dict,
        script_segment: str,
        video_no: str = None
    ) -> EntailmentResult:
        """
        Verify if the visual content of a clip ENTAILS the script description.
        
        This is the main entry point for entailment verification.
        
        Args:
            clip_info: Dict with 'start_time', 'end_time', and optionally 'video_no'
            script_segment: The script text to verify against
            video_no: Video identifier (can also be in clip_info)
            
        Returns:
            EntailmentResult with judgment, confidence, evidence, and contradictions
        """
        start_time = clip_info.get('start_time', 0)
        end_time = clip_info.get('end_time', 0)
        video_no = video_no or clip_info.get('video_no', '')
        
        if not video_no:
            return EntailmentResult(
                judgment=EntailmentJudgment.NEUTRAL,
                confidence=0.0,
                evidence="No video_no provided",
                contradictions=["Missing video identifier"],
                frame_analyses=[]
            )
        
        if end_time <= start_time:
            return EntailmentResult(
                judgment=EntailmentJudgment.NEUTRAL,
                confidence=0.0,
                evidence="Invalid clip duration",
                contradictions=["end_time <= start_time"],
                frame_analyses=[]
            )
        
        # Check cache
        script_hash = hashlib.md5(script_segment.encode()).hexdigest()[:8]
        cache_key = self._get_cache_key(video_no, start_time, end_time, script_hash)
        
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    cached_data = json.loads(cached)
                    return EntailmentResult(
                        judgment=EntailmentJudgment(cached_data['judgment']),
                        confidence=cached_data['confidence'],
                        evidence=cached_data['evidence'],
                        contradictions=cached_data['contradictions'],
                        frame_analyses=cached_data.get('frame_analyses', [])
                    )
            except Exception:
                pass
        
        # Extract claims from script
        claims = self._extract_script_claims(script_segment)
        
        # Sample frames adaptively
        frames = self._sample_frames_adaptive(start_time, end_time, self.frame_samples)
        
        # Build entailment prompt
        prompt = self._build_entailment_prompt(
            script_segment, claims, frames, start_time, end_time
        )
        
        # Query Memories.ai
        try:
            response = await self.memories.get_visual_description(
                video_no=video_no,
                start_time=start_time,
                end_time=end_time,
                unique_id=f"entailment_{video_no}",
                custom_prompt=prompt
            )
        except Exception as e:
            print(f"    ⚠️ Entailment query error: {e}", flush=True)
            return EntailmentResult(
                judgment=EntailmentJudgment.NEUTRAL,
                confidence=0.0,
                evidence=f"API error: {str(e)}",
                contradictions=[],
                frame_analyses=[]
            )
        
        # Parse response
        parsed = self._parse_entailment_response(response)
        
        result = EntailmentResult(
            judgment=parsed['judgment'],
            confidence=parsed['confidence'],
            evidence=parsed['evidence'],
            contradictions=parsed['contradictions'],
            frame_analyses=[{
                'raw_response': response[:1000],  # Truncate for storage
                'claims_checked': [c['full_text'] for c in claims[:3]]
            }]
        )
        
        # Cache result (24 hour TTL)
        if self.redis_client:
            try:
                cache_data = {
                    'judgment': result.judgment.value,
                    'confidence': result.confidence,
                    'evidence': result.evidence,
                    'contradictions': result.contradictions,
                    'frame_analyses': result.frame_analyses
                }
                self.redis_client.setex(cache_key, 24 * 60 * 60, json.dumps(cache_data))
            except Exception:
                pass
        
        return result
    
    async def verify_entailment_batch(
        self,
        candidates: List[Dict],
        script_segment: str,
        video_no: str
    ) -> List[Tuple[Dict, EntailmentResult]]:
        """
        Verify entailment for multiple candidates in parallel.
        
        Args:
            candidates: List of candidate clip dicts
            script_segment: The script text to verify against
            video_no: Video identifier
            
        Returns:
            List of (candidate, EntailmentResult) tuples
        """
        # Rate limit concurrent requests
        semaphore = asyncio.Semaphore(3)
        
        async def verify_one(candidate):
            async with semaphore:
                result = await self.verify_entailment(candidate, script_segment, video_no)
                return (candidate, result)
        
        tasks = [verify_one(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        verified = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"    ⚠️ Entailment batch error: {result}", flush=True)
                verified.append((candidates[i], EntailmentResult(
                    judgment=EntailmentJudgment.NEUTRAL,
                    confidence=0.0,
                    evidence=f"Error: {str(result)}",
                    contradictions=[],
                    frame_analyses=[]
                )))
            else:
                verified.append(result)
        
        return verified

