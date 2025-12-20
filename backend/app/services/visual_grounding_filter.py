"""
Visual Grounding Filter Service - Pre-filters video clips based on visual content.

This service verifies that candidate video clips actually contain the visual elements
(objects, actions, states) described in the script BEFORE semantic matching.
This solves the fundamental semantic vs. visual grounding gap.

Based on research showing that text-only semantic matching causes 40-60% visual
hallucination in video-language tasks.
"""

import asyncio
import hashlib
import json
import numpy as np
import redis
import spacy
from typing import List, Dict, Set, Optional

from app.config import get_settings

# Global NLP model cache
_nlp_model = None


def _get_nlp_model():
    """Load spaCy model (cached globally)."""
    global _nlp_model
    if _nlp_model is None:
        print("🧠 Loading spaCy model for visual grounding...", flush=True)
        _nlp_model = spacy.load("en_core_web_sm")
        print("✅ spaCy model loaded for visual grounding.", flush=True)
    return _nlp_model


class VisualGroundingFilter:
    """
    Pre-filters video segments using visual object/action grounding
    before semantic matching. Ensures candidates actually contain
    the visual elements described in the script.
    """

    def __init__(self, memories_client, config):
        """
        Initialize the visual grounding filter.
        
        Args:
            memories_client: MemoriesAIClient instance for visual queries
            config: VectorMatchingConfig with grounding settings
        """
        self.memories = memories_client
        self.config = config
        self.nlp = _get_nlp_model()
        
        # Get settings
        self.settings = get_settings()
        
        # Initialize Redis for caching (optional)
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
            print("✅ Redis connected for visual grounding cache.", flush=True)
        except Exception as e:
            print(f"⚠️ Redis not available for grounding cache: {e}", flush=True)
            self.redis_client = None
        
        # Action verb categories for visual verification
        # These help match script verbs to visual actions
        self.action_verbs = {
            'motion': {
                'walk', 'run', 'jump', 'fly', 'swim', 'climb', 'fall', 'move',
                'step', 'sprint', 'dash', 'leap', 'dive', 'crawl', 'slide',
                'roll', 'tumble', 'stumble', 'stagger', 'rush', 'hurry'
            },
            'interaction': {
                'grab', 'hold', 'throw', 'catch', 'push', 'pull', 'lift',
                'carry', 'drop', 'pick', 'place', 'put', 'take', 'give',
                'hand', 'pass', 'toss', 'release', 'grip', 'grasp'
            },
            'combat': {
                'punch', 'kick', 'slash', 'block', 'dodge', 'attack', 'fight',
                'strike', 'hit', 'swing', 'stab', 'shoot', 'fire', 'aim',
                'defend', 'counter', 'parry', 'evade', 'charge', 'lunge'
            },
            'transformation': {
                'open', 'close', 'break', 'build', 'create', 'destroy',
                'transform', 'change', 'morph', 'shatter', 'explode', 'collapse',
                'assemble', 'disassemble', 'repair', 'fix', 'unlock', 'lock'
            },
            'communication': {
                'speak', 'shout', 'whisper', 'listen', 'read', 'write',
                'talk', 'yell', 'scream', 'cry', 'laugh', 'smile', 'frown',
                'nod', 'shake', 'gesture', 'point', 'wave', 'signal'
            },
            'perception': {
                'look', 'see', 'watch', 'stare', 'glance', 'gaze', 'observe',
                'notice', 'spot', 'find', 'discover', 'search', 'scan'
            },
            'state_change': {
                'stand', 'sit', 'lie', 'kneel', 'crouch', 'lean', 'turn',
                'face', 'enter', 'exit', 'leave', 'arrive', 'appear', 'disappear',
                'emerge', 'vanish', 'rise', 'lower', 'raise'
            }
        }
        
        # Create reverse lookup: verb -> category
        self.verb_to_category = {}
        for category, verbs in self.action_verbs.items():
            for verb in verbs:
                self.verb_to_category[verb] = category
        
        # Get all action verbs as a flat set
        self.all_action_verbs = set()
        for verbs in self.action_verbs.values():
            self.all_action_verbs.update(verbs)
        
        print(f"👁️ VisualGroundingFilter initialized with {len(self.all_action_verbs)} action verbs", flush=True)

    def _extract_visual_requirements(self, script_segment: str) -> Dict:
        """
        Extract specific visual elements that MUST be present in the video:
        - Objects (nouns, proper nouns)
        - Actions (verbs)
        - Spatial relationships
        - States/attributes
        - Agent-action bindings (WHO-DOES-WHAT)
        
        Args:
            script_segment: The script text to analyze
            
        Returns:
            Dict with required_objects, required_actions, spatial_relations, required_states, agent_action_bindings
        """
        doc = self.nlp(script_segment)
        
        requirements = {
            'required_objects': set(),
            'required_actions': set(),
            'action_categories': set(),
            'spatial_relations': [],
            'required_states': set(),
            'agent_action_bindings': [],  # NEW: WHO-DOES-WHAT bindings
            'raw_text': script_segment
        }
        
        for token in doc:
            # Extract objects (nouns, proper nouns)
            if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop:
                lemma = token.lemma_.lower()
                # Filter out very common/generic nouns
                if len(lemma) > 2 and lemma not in {'way', 'thing', 'time', 'moment', 'day'}:
                    requirements['required_objects'].add(lemma)
            
            # Extract actions (verbs)
            if token.pos_ == 'VERB' and not token.is_stop:
                action = token.lemma_.lower()
                # Filter auxiliary verbs
                if action not in {'be', 'have', 'do', 'will', 'would', 'could', 'should', 'may', 'might', 'can'}:
                    requirements['required_actions'].add(action)
                    
                    # Categorize action for better matching
                    if action in self.verb_to_category:
                        requirements['action_categories'].add(self.verb_to_category[action])
            
            # Extract spatial prepositions with their objects
            if token.dep_ == 'prep' and token.text.lower() in {
                'in', 'on', 'near', 'behind', 'above', 'below', 'beside',
                'under', 'over', 'through', 'into', 'onto', 'toward', 'towards'
            }:
                # Find the object of the preposition
                for child in token.children:
                    if child.dep_ == 'pobj' and child.pos_ in ['NOUN', 'PROPN']:
                        requirements['spatial_relations'].append({
                            'preposition': token.text.lower(),
                            'object': child.lemma_.lower()
                        })
            
            # Extract states (adjectives)
            if token.pos_ == 'ADJ' and not token.is_stop:
                state = token.text.lower()
                # Filter common/non-visual adjectives
                if state not in {'good', 'bad', 'new', 'old', 'great', 'little', 'big', 'small'}:
                    requirements['required_states'].add(state)
        
        # NEW: Extract agent-action bindings (WHO-DOES-WHAT)
        # This is critical for preventing the binding hallucination problem
        if getattr(self.config, 'grounding_requires_action_binding', True):
            requirements['agent_action_bindings'] = self._extract_agent_action_bindings(doc)
        
        return requirements
    
    def _extract_agent_action_bindings(self, doc) -> List[Dict]:
        """
        Extract WHO-DOES-WHAT relationships from parsed text.
        
        Uses dependency parsing to find subject-verb-object relationships.
        This addresses the "binding test" problem from VELOCITI benchmark
        where models fail to associate the correct agent with the correct action.
        
        Args:
            doc: spaCy Doc object
            
        Returns:
            List of binding dicts with 'agent', 'action', 'patient', 'full_phrase'
        """
        bindings = []
        
        for token in doc:
            if token.pos_ == "VERB" and token.dep_ in ("ROOT", "conj", "advcl", "relcl", "ccomp", "xcomp"):
                action = token.lemma_.lower()
                
                # Skip auxiliary verbs
                if action in {'be', 'have', 'do', 'will', 'would', 'could', 'should', 'may', 'might', 'can'}:
                    continue
                
                # Find subject (agent) - the one DOING the action
                agents = []
                for child in token.children:
                    if child.dep_ in ("nsubj", "nsubjpass"):
                        # Get full noun phrase for the agent
                        agent_phrase = " ".join([w.text for w in child.subtree])
                        agents.append(agent_phrase.strip())
                
                # Find object (patient) - the one RECEIVING the action
                patients = []
                for child in token.children:
                    if child.dep_ in ("dobj", "pobj", "attr", "iobj"):
                        patient_phrase = " ".join([w.text for w in child.subtree])
                        patients.append(patient_phrase.strip())
                
                # Create bindings for each agent
                for agent in agents:
                    binding = {
                        'agent': agent,
                        'action': action,
                        'patient': patients[0] if patients else None,
                        'full_phrase': f"{agent} {token.text}" + (f" {patients[0]}" if patients else "")
                    }
                    bindings.append(binding)
        
        return bindings[:5]  # Limit to 5 most important bindings

    def _build_targeted_visual_query(self, timestamp: float, requirements: Dict) -> str:
        """
        Build Memories.ai prompt focused on specific visual elements from script.
        
        Enhanced with WHO-DOES-WHAT binding verification to prevent the
        "binding hallucination" problem where models see both agent and action
        but fail to verify the agent is actually performing the action.
        
        Args:
            timestamp: The timestamp to query
            requirements: Dict from _extract_visual_requirements()
            
        Returns:
            Targeted prompt string for Memories.ai
        """
        objects_str = ', '.join(requirements['required_objects']) if requirements['required_objects'] else "any visible characters or objects"
        actions_str = ', '.join(requirements['required_actions']) if requirements['required_actions'] else "any actions"
        
        # Build agent-action binding section if bindings exist
        binding_section = ""
        bindings = requirements.get('agent_action_bindings', [])
        if bindings and getattr(self.config, 'grounding_requires_action_binding', True):
            binding_checks = []
            for i, binding in enumerate(bindings[:3]):  # Limit to 3 bindings
                agent = binding.get('agent', 'unknown')
                action = binding.get('action', 'unknown')
                patient = binding.get('patient', '')
                patient_str = f" to/with {patient}" if patient else ""
                binding_checks.append(
                    f"   {i+1}. Is '{agent}' PERFORMING '{action}'{patient_str}?\n"
                    f"      - Agent visible: YES/NO\n"
                    f"      - Agent's actual action: [describe what they're doing]\n"
                    f"      - Binding valid: YES/NO"
                )
            
            binding_section = f"""

5. **CRITICAL ENTITY-ACTION BINDING CHECK:**
   Verify WHO is doing WHAT - this is essential for accurate matching.
   
{chr(10).join(binding_checks)}

   IMPORTANT: If Agent A is doing Action X but script claims Agent B is doing Action X,
   mark the binding as INVALID and explain the mismatch."""
        
        return f"""At timestamp {timestamp:.2f} seconds, provide a FACTUAL INVENTORY:

1. OBJECT PRESENCE CHECK:
   Looking specifically for: {objects_str}
   - Which of these objects/characters are VISIBLE in the frame?
   - List ONLY what you can actually see, not inferred ones
   - If an object is NOT visible, explicitly state "NOT VISIBLE"

2. ACTION DETECTION:
   Looking specifically for actions like: {actions_str}
   - What action is CURRENTLY HAPPENING at this instant?
   - Use precise action verbs (e.g., "punching" not "fighting")
   - If no action is happening, state "static/idle"

3. SPATIAL LAYOUT:
   - Where are the key objects positioned relative to each other?
   - What is in the foreground vs background?

4. VISUAL STATES:
   - What is the condition/state of key objects? (open/closed, standing/sitting, etc.)
{binding_section}

Be LITERAL. Only describe what is directly visible at {timestamp:.2f}s.
Do NOT infer, interpret, or fill gaps with context."""

    def _parse_visual_response(self, response: str, requirements: Dict) -> Dict:
        """
        Parse Memories.ai response to extract detected elements.
        
        Enhanced to extract agent-action binding validation results.
        
        Args:
            response: Raw response from Memories.ai
            requirements: Original requirements dict
            
        Returns:
            Dict with detected objects, actions, states, binding_results
        """
        response_lower = response.lower()
        
        frame_data = {
            'objects': set(),
            'actions': set(),
            'states': set(),
            'binding_results': [],  # NEW: Agent-action binding validation results
            'binding_valid_count': 0,
            'binding_invalid_count': 0,
            'raw_response': response
        }
        
        # Check for required objects
        for obj in requirements['required_objects']:
            # Look for object mention AND confirmation it's visible
            # Avoid false positives where "NOT VISIBLE" follows the object
            obj_lower = obj.lower()
            if obj_lower in response_lower:
                # Check if "not visible" appears near the object mention
                obj_idx = response_lower.find(obj_lower)
                context_after = response_lower[obj_idx:obj_idx + 50]
                context_before = response_lower[max(0, obj_idx - 30):obj_idx]
                
                if 'not visible' not in context_after and 'not visible' not in context_before:
                    if 'cannot see' not in context_after and 'can\'t see' not in context_after:
                        frame_data['objects'].add(obj)
        
        # NEW: Parse agent-action binding results
        bindings = requirements.get('agent_action_bindings', [])
        if bindings:
            frame_data['binding_results'] = self._parse_binding_results(response, bindings)
            frame_data['binding_valid_count'] = sum(
                1 for b in frame_data['binding_results'] if b.get('is_valid', False)
            )
            frame_data['binding_invalid_count'] = sum(
                1 for b in frame_data['binding_results'] if not b.get('is_valid', True)
            )
        
        # Check for required actions and their synonyms
        for action in requirements['required_actions']:
            action_lower = action.lower()
            
            # Direct match
            if action_lower in response_lower:
                frame_data['actions'].add(action)
                continue
            
            # Check for synonyms within same category
            if action_lower in self.verb_to_category:
                category = self.verb_to_category[action_lower]
                for synonym in self.action_verbs[category]:
                    if synonym in response_lower:
                        # Map back to the required action
                        frame_data['actions'].add(action)
                        break
            
            # Check for -ing forms (e.g., "punch" -> "punching")
            ing_form = action_lower + 'ing'
            if ing_form in response_lower:
                frame_data['actions'].add(action)
            
            # Check for -ed forms
            ed_form = action_lower + 'ed'
            if ed_form in response_lower:
                frame_data['actions'].add(action)
        
        # Check for states
        for state in requirements['required_states']:
            if state.lower() in response_lower:
                frame_data['states'].add(state)
        
        return frame_data
    
    def _parse_binding_results(self, response: str, bindings: List[Dict]) -> List[Dict]:
        """
        Parse agent-action binding validation results from the response.
        
        Looks for explicit "Binding valid: YES/NO" markers and infers
        validity from context if not explicitly stated.
        
        Args:
            response: Raw response from Memories.ai
            bindings: List of agent-action bindings to check
            
        Returns:
            List of binding result dicts with 'agent', 'action', 'is_valid', 'reason'
        """
        response_lower = response.lower()
        results = []
        
        for binding in bindings:
            agent = binding.get('agent', '').lower()
            action = binding.get('action', '').lower()
            
            result = {
                'agent': binding.get('agent', ''),
                'action': binding.get('action', ''),
                'is_valid': None,
                'reason': ''
            }
            
            # Look for explicit "Binding valid: YES/NO" near the agent mention
            if agent in response_lower:
                agent_idx = response_lower.find(agent)
                # Look in a window around the agent mention
                window_start = max(0, agent_idx - 50)
                window_end = min(len(response_lower), agent_idx + 200)
                context = response_lower[window_start:window_end]
                
                # Check for explicit binding validity markers
                if 'binding valid: yes' in context or 'binding: yes' in context:
                    result['is_valid'] = True
                    result['reason'] = 'Explicit binding validation passed'
                elif 'binding valid: no' in context or 'binding: no' in context or 'binding invalid' in context:
                    result['is_valid'] = False
                    result['reason'] = 'Explicit binding validation failed'
                elif 'not visible' in context or 'cannot see' in context:
                    result['is_valid'] = False
                    result['reason'] = f'Agent "{binding.get("agent")}" not visible'
                elif action in context:
                    # Agent is mentioned and action is mentioned nearby
                    # Check if there's a negative context
                    if 'not ' + action in context or 'instead of ' + action in context:
                        result['is_valid'] = False
                        result['reason'] = f'Agent visible but not performing "{action}"'
                    else:
                        result['is_valid'] = True
                        result['reason'] = 'Agent and action both present in context'
                else:
                    result['is_valid'] = None  # Inconclusive
                    result['reason'] = 'Could not determine binding validity'
            else:
                result['is_valid'] = False
                result['reason'] = f'Agent "{binding.get("agent")}" not mentioned in response'
            
            results.append(result)
        
        return results

    def _compute_grounding_score(self, requirements: Dict, analysis: Dict) -> float:
        """
        Compute how well the clip is grounded in required visual elements.
        
        Score components (rebalanced for binding verification):
        - Object presence: 30% (reduced from 40%)
        - Action presence: 30% (reduced from 40%)
        - Agent-action binding: 25% (NEW - critical for accuracy)
        - State/attribute match: 15% (reduced from 20%)
        
        Args:
            requirements: Original requirements from script
            analysis: Aggregated analysis from all frames
            
        Returns:
            Grounding score between 0.0 and 1.0
        """
        scores = []
        
        # Object grounding (30% weight - reduced)
        if requirements['required_objects']:
            detected = analysis.get('detected_objects', set())
            required = requirements['required_objects']
            object_recall = len(detected & required) / len(required)
            scores.append(('objects', object_recall, 0.30))
        
        # Action grounding (30% weight - reduced)
        if requirements['required_actions']:
            detected = analysis.get('detected_actions', set())
            required = requirements['required_actions']
            action_recall = len(detected & required) / len(required)
            scores.append(('actions', action_recall, 0.30))
        
        # NEW: Agent-action binding grounding (25% weight - critical)
        # This verifies WHO is doing WHAT, not just that objects/actions exist
        bindings = requirements.get('agent_action_bindings', [])
        if bindings and getattr(self.config, 'grounding_requires_action_binding', True):
            binding_valid_count = analysis.get('binding_valid_count', 0)
            binding_invalid_count = analysis.get('binding_invalid_count', 0)
            total_bindings = len(bindings)
            
            if total_bindings > 0:
                # Calculate binding score
                # Valid bindings contribute positively, invalid bindings are penalized
                if binding_valid_count + binding_invalid_count > 0:
                    binding_score = binding_valid_count / (binding_valid_count + binding_invalid_count)
                else:
                    binding_score = 0.5  # Neutral if no explicit results
                
                # Apply penalty if any bindings are explicitly invalid
                if binding_invalid_count > 0:
                    binding_score *= 0.7  # 30% penalty for any invalid binding
                
                scores.append(('bindings', binding_score, 0.25))
        
        # State grounding (15% weight - reduced)
        if requirements['required_states']:
            detected = analysis.get('detected_states', set())
            required = requirements['required_states']
            state_recall = len(detected & required) / len(required)
            scores.append(('states', state_recall, 0.15))
        
        # Weighted average
        if not scores:
            return 1.0  # No specific requirements, all clips are valid
        
        # Normalize weights
        total_weight = sum(weight for _, _, weight in scores)
        if total_weight == 0:
            return 1.0
        
        normalized_scores = [(name, score, weight / total_weight) for name, score, weight in scores]
        final_score = sum(score * norm_weight for _, score, norm_weight in normalized_scores)
        
        return final_score

    def _get_cache_key(self, video_no: str, timestamp: float, requirements: Dict) -> str:
        """Generate cache key for grounding query."""
        # Create hash of requirements for cache key
        req_str = json.dumps({
            'objects': sorted(requirements['required_objects']),
            'actions': sorted(requirements['required_actions'])
        }, sort_keys=True)
        req_hash = hashlib.md5(req_str.encode()).hexdigest()[:8]
        return f"grounding:{video_no}:{timestamp:.2f}:{req_hash}"

    async def _analyze_clip_visual_content(
        self,
        video_no: str,
        start_time: float,
        end_time: float,
        requirements: Dict
    ) -> Dict:
        """
        Get DETAILED visual analysis of clip focusing on required elements.
        Uses targeted Memories.ai queries.
        
        Args:
            video_no: Video identifier
            start_time: Clip start time
            end_time: Clip end time
            requirements: Visual requirements from script
            
        Returns:
            Dict with detected_objects, detected_actions, detected_states, frame_analyses
        """
        duration = end_time - start_time
        
        # Sample frames depending on duration
        sample_count = getattr(self.config, 'grounding_sample_frames', 3)
        if duration < 3:
            sample_count = min(2, sample_count)
        elif duration > 10:
            sample_count = min(5, sample_count + 1)
        
        sample_times = np.linspace(start_time, end_time, sample_count)
        
        analysis = {
            'detected_objects': set(),
            'detected_actions': set(),
            'detected_states': set(),
            'binding_valid_count': 0,  # NEW: Track binding validations
            'binding_invalid_count': 0,
            'binding_results': [],
            'frame_analyses': [],
            'cache_hits': 0,
            'api_calls': 0
        }
        
        # Process each sample frame
        for timestamp in sample_times:
            # Check cache first
            cache_key = self._get_cache_key(video_no, timestamp, requirements)
            cached_result = None
            
            if self.redis_client:
                try:
                    cached_result = self.redis_client.get(cache_key)
                    if cached_result:
                        frame_data = json.loads(cached_result)
                        # Convert lists back to sets
                        frame_data['objects'] = set(frame_data.get('objects', []))
                        frame_data['actions'] = set(frame_data.get('actions', []))
                        frame_data['states'] = set(frame_data.get('states', []))
                        analysis['cache_hits'] += 1
                except Exception:
                    cached_result = None
            
            if cached_result is None:
                # Build targeted prompt
                prompt = self._build_targeted_visual_query(timestamp, requirements)
                
                # Query Memories.ai
                try:
                    response = await self.memories.get_visual_description(
                        video_no=video_no,
                        start_time=max(0, timestamp - 0.5),
                        end_time=timestamp + 0.5,
                        unique_id=f"grounding_{video_no}",
                        custom_prompt=prompt
                    )
                    analysis['api_calls'] += 1
                    
                    # Parse response
                    frame_data = self._parse_visual_response(response, requirements)
                    
                    # Cache the result
                    if self.redis_client:
                        try:
                            cache_data = {
                                'objects': list(frame_data['objects']),
                                'actions': list(frame_data['actions']),
                                'states': list(frame_data['states']),
                                'binding_results': frame_data.get('binding_results', []),
                                'binding_valid_count': frame_data.get('binding_valid_count', 0),
                                'binding_invalid_count': frame_data.get('binding_invalid_count', 0),
                                'raw_response': frame_data.get('raw_response', '')
                            }
                            self.redis_client.setex(cache_key, 24 * 60 * 60, json.dumps(cache_data))
                        except Exception:
                            pass
                            
                except Exception as e:
                    print(f"    ⚠️ Grounding query error at {timestamp:.1f}s: {e}", flush=True)
                    frame_data = {'objects': set(), 'actions': set(), 'states': set(), 
                                  'binding_results': [], 'binding_valid_count': 0, 'binding_invalid_count': 0}
            
            analysis['frame_analyses'].append({
                'timestamp': timestamp,
                **frame_data
            })
            
            # Aggregate findings
            analysis['detected_objects'].update(frame_data.get('objects', set()))
            analysis['detected_actions'].update(frame_data.get('actions', set()))
            analysis['detected_states'].update(frame_data.get('states', set()))
            
            # Aggregate binding results (NEW)
            analysis['binding_valid_count'] += frame_data.get('binding_valid_count', 0)
            analysis['binding_invalid_count'] += frame_data.get('binding_invalid_count', 0)
            analysis['binding_results'].extend(frame_data.get('binding_results', []))
        
        return analysis

    async def filter_candidates_by_visual_grounding(
        self,
        script_segment: str,
        video_no: str,
        candidate_clips: List[Dict],
        min_grounding_score: float = None
    ) -> List[Dict]:
        """
        Filter candidates by checking if they actually contain
        the visual elements (objects, actions, states) described in script.
        
        This runs BEFORE semantic matching to eliminate false positives.
        
        Args:
            script_segment: The script text
            video_no: Video identifier
            candidate_clips: List of candidate clip dicts
            min_grounding_score: Minimum score to pass (default from config)
            
        Returns:
            List of candidates that passed visual grounding filter
        """
        if min_grounding_score is None:
            min_grounding_score = getattr(self.config, 'grounding_score_threshold', 0.65)
        
        # Step 1: Extract visual requirements from script
        requirements = self._extract_visual_requirements(script_segment)
        
        # If no specific visual requirements, skip filtering
        if not requirements['required_objects'] and not requirements['required_actions']:
            print(f"    ℹ️ No specific visual requirements, skipping grounding filter", flush=True)
            for candidate in candidate_clips:
                candidate['grounding_score'] = 1.0
                candidate['grounding_details'] = {'skipped': True}
            return candidate_clips
        
        print(f"    🔍 Grounding filter: objects={list(requirements['required_objects'])[:5]}, actions={list(requirements['required_actions'])[:3]}", flush=True)
        
        # Step 2: Check each candidate for visual grounding
        grounded_candidates = []
        rejected_count = 0
        total_api_calls = 0
        total_cache_hits = 0
        
        # Process candidates with rate limiting
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent Memories.ai requests
        
        async def analyze_candidate(candidate):
            async with semaphore:
                start = candidate['start_time']
                end = candidate['end_time']
                
                # Get dense visual analysis for this clip
                visual_analysis = await self._analyze_clip_visual_content(
                    video_no, start, end, requirements
                )
                
                # Compute grounding score
                grounding_score = self._compute_grounding_score(requirements, visual_analysis)
                
                return {
                    'candidate': candidate,
                    'grounding_score': grounding_score,
                    'visual_analysis': visual_analysis
                }
        
        # Analyze all candidates
        tasks = [analyze_candidate(c) for c in candidate_clips]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                print(f"    ⚠️ Grounding analysis error: {result}", flush=True)
                continue
            
            candidate = result['candidate']
            grounding_score = result['grounding_score']
            visual_analysis = result['visual_analysis']
            
            total_api_calls += visual_analysis.get('api_calls', 0)
            total_cache_hits += visual_analysis.get('cache_hits', 0)
            
            if grounding_score >= min_grounding_score:
                candidate['grounding_score'] = grounding_score
                candidate['grounding_details'] = {
                    'detected_objects': list(visual_analysis['detected_objects']),
                    'detected_actions': list(visual_analysis['detected_actions']),
                    'detected_states': list(visual_analysis['detected_states']),
                    'required_objects': list(requirements['required_objects']),
                    'required_actions': list(requirements['required_actions'])
                }
                grounded_candidates.append(candidate)
            else:
                rejected_count += 1
                # Log rejected candidates for debugging
                if getattr(self.config, 'enable_validation_debug', False):
                    print(f"    ❌ REJECTED (grounding={grounding_score:.2f}): {candidate['start_time']:.1f}-{candidate['end_time']:.1f}s", flush=True)
                    print(f"       Required: obj={list(requirements['required_objects'])[:3]}, act={list(requirements['required_actions'])[:3]}", flush=True)
                    print(f"       Found: obj={list(visual_analysis['detected_objects'])[:3]}, act={list(visual_analysis['detected_actions'])[:3]}", flush=True)
        
        print(f"    ✅ Grounding: {len(grounded_candidates)}/{len(candidate_clips)} passed (API calls: {total_api_calls}, cache hits: {total_cache_hits})", flush=True)
        
        return grounded_candidates

