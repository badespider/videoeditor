"""
Clip Matcher Service - Core matching logic for script-to-clip matching.

Combines vector similarity search with Memories.ai validation and temporal coherence.

Enhanced with Visual Entailment verification (Stage 2.5) to address the
"Semantic Aggregation Hallucination" problem where clips are selected based on
semantic similarity but don't actually show the described actions.
"""

from typing import List, Dict, Optional
import numpy as np

from app.config import get_settings
from app.services.memories_client import MemoriesAIClient
from app.services.vector_store import VectorStore
from app.services.visual_validator import VisualTemporalValidator


class ClipMatcher:
    """
    Matches script segments to video clips using semantic similarity.
    
    Uses multi-strategy matching with Visual Entailment:
    1. Vector similarity search (primary)
    1.5. Visual grounding filter (pre-filter for object/action presence)
    2. Memories.ai visual search validation (secondary)
    2.5. Visual Entailment verification (NEW - verifies script ENTAILS visual)
    3. Frame-level visual validation
    4. Temporal coherence scoring (narrative flow)
    5. Rebalanced final selection (entailment prioritized)
    """

    def __init__(self):
        self.settings = get_settings()
        self.vector_config = self.settings.features.vector_matching
        self.memories_client = MemoriesAIClient()
        self.vector_store = VectorStore()
        
        # Initialize visual validator if enabled
        self.visual_validator = None
        if self.vector_config.enable_visual_validation:
            self.visual_validator = VisualTemporalValidator()
        
        # Initialize visual grounding filter if enabled
        self.visual_grounding_filter = None
        if getattr(self.vector_config, 'enable_visual_grounding', False):
            from app.services.visual_grounding_filter import VisualGroundingFilter
            self.visual_grounding_filter = VisualGroundingFilter(
                self.memories_client, 
                self.vector_config
            )
        
        # NEW: Initialize visual entailment verifier if enabled
        self.entailment_verifier = None
        if getattr(self.vector_config, 'enable_visual_entailment', True):
            from app.services.visual_entailment_verifier import VisualEntailmentVerifier
            self.entailment_verifier = VisualEntailmentVerifier(
                self.memories_client, 
                self.vector_config
            )
        
        self.similarity_threshold = self.vector_config.similarity_threshold
        self.semantic_weight = self.vector_config.semantic_weight
        self.validation_boost = self.vector_config.validation_boost
        self.temporal_weight = self.vector_config.temporal_coherence_weight

    async def match_script_to_clips(
        self,
        script_segments: List[Dict],
        video_no: str,
        video_duration: float = None
    ) -> List[Dict]:
        """
        Match script segments to video clips with diversity enforcement.
        
        Args:
            script_segments: List of script segment dicts with 'embedding' and 'text'
            video_no: Video identifier
            video_duration: Optional total video duration (auto-detected if not provided)
            
        Returns:
            List of match dicts with:
                - script_segment: original segment dict
                - matched_clip: best matching clip
                - confidence: final confidence score
                - alternatives: list of alternative clips
        """
        print(f"🎯 Matching {len(script_segments)} script segments to clips...", flush=True)
        
        matches = []
        
        # === DIVERSITY TRACKING STATE ===
        # Track used segments to prevent repetition
        used_segments = set()  # Set of (start_time, end_time) tuples
        
        # Get video duration for partitioning (from embeddings if not provided)
        if video_duration is None:
            all_embeddings = await self.vector_store.get_video_embeddings(video_no)
            if all_embeddings:
                video_duration = max([emb.get('end_time', 0) for emb in all_embeddings])
            else:
                video_duration = 600  # Default 10 minutes
        
        # Calculate temporal partitions (divide video into N equal regions)
        num_partitions = max(3, getattr(self.vector_config, 'num_temporal_partitions', 5))
        partition_boundaries = [
            (i * video_duration / num_partitions, (i + 1) * video_duration / num_partitions)
            for i in range(num_partitions)
        ]
        
        # Track usage per partition to enforce coverage
        partition_usage = {i: 0 for i in range(num_partitions)}
        max_clips_per_partition = getattr(self.vector_config, 'max_clips_per_partition', 2)
        
        print(f"  📊 Video duration: {video_duration:.1f}s, partitions: {num_partitions}, max per partition: {max_clips_per_partition}", flush=True)
        
        for idx, script_seg in enumerate(script_segments):
            print(f"  Matching segment {idx + 1}/{len(script_segments)}", flush=True)
            
            
            # Strategy 1: Vector similarity search WITH diversity constraints
            # Use constrained search to exclude already-used segments
            exclude_ranges = list(used_segments) if used_segments else None
            max_overlap = getattr(self.vector_config, 'max_overlap_ratio', 0.3)
            
            candidates = await self.vector_store.search_similar_with_constraints(
                query_embedding=script_seg['embedding'],
                video_no=video_no,
                top_k=10,  # Increased from 5 for more diversity options
                exclude_ranges=exclude_ranges,
                max_overlap_ratio=max_overlap
            )
            
            # Fallback to regular search if constrained search returns nothing
            if not candidates:
                print(f"    ⚠️ Constrained search found no candidates, trying unconstrained...", flush=True)
                candidates = await self.vector_store.search_similar(
                    script_seg['embedding'],
                    video_no,
                    top_k=10
                )
            
            
            if not candidates:
                print(f"    ⚠️ No candidates found for segment {idx + 1}", flush=True)
                matches.append({
                    'script_segment': script_seg,
                    'matched_clip': None,
                    'confidence': 0.0,
                    'alternatives': []
                })
                continue
            
            # Strategy 1.5: Visual Grounding Filter (PRE-FILTER before validation)
            # Eliminates candidates that don't contain required visual elements
            if self.visual_grounding_filter:
                grounding_threshold = getattr(self.vector_config, 'grounding_score_threshold', 0.65)
                grounded_candidates = await self.visual_grounding_filter.filter_candidates_by_visual_grounding(
                    script_segment=script_seg['text'],
                    video_no=video_no,
                    candidate_clips=candidates,
                    min_grounding_score=grounding_threshold
                )
                
                # If no candidates pass strict grounding, try relaxed threshold
                if not grounded_candidates:
                    print(f"    ⚠️ No candidates passed strict grounding, trying relaxed threshold...", flush=True)
                    relaxed_threshold = getattr(self.vector_config, 'grounding_relaxed_threshold', 0.50)
                    grounded_candidates = await self.visual_grounding_filter.filter_candidates_by_visual_grounding(
                        script_segment=script_seg['text'],
                        video_no=video_no,
                        candidate_clips=candidates,
                        min_grounding_score=relaxed_threshold
                    )
                
                # Ultimate fallback: use top semantic match with grounding warning
                if not grounded_candidates:
                    print(f"    ⚠️ No grounded candidates, using best semantic match with warning", flush=True)
                    best_semantic = candidates[0].copy()
                    best_semantic['grounding_score'] = 0.3  # Low grounding score
                    best_semantic['grounding_warning'] = True
                    grounded_candidates = [best_semantic]
                
                candidates = grounded_candidates
            
            # Strategy 2: Validate with Memories.ai visual search
            validated_candidates = await self.validate_with_visual_search(
                script_seg['text'],
                video_no,
                candidates
            )
            
            # **NEW Stage 2.5: Visual Entailment Verification**
            # This is the critical gate that verifies the visual content ENTAILS the script
            # Based on Chen et al. "Explainable Video Entailment with Grounded Visual Evidence" (ICCV 2021)
            if self.entailment_verifier and getattr(self.vector_config, 'enable_visual_entailment', True):
                print(f"    🔬 Applying visual entailment verification...", flush=True)
                
                entailment_threshold = getattr(self.vector_config, 'entailment_threshold', 0.70)
                entailment_verified = []
                
                # Verify entailment for each candidate
                from app.services.visual_entailment_verifier import EntailmentJudgment
                
                for candidate in validated_candidates:
                    try:
                        entailment_result = await self.entailment_verifier.verify_entailment(
                            clip_info=candidate,
                            script_segment=script_seg['text'],
                            video_no=video_no
                        )
                        
                        # Add entailment metadata to candidate
                        candidate = candidate.copy()
                        candidate['entailment_judgment'] = entailment_result.judgment.value
                        candidate['entailment_score'] = entailment_result.confidence
                        candidate['entailment_evidence'] = entailment_result.evidence
                        candidate['entailment_contradictions'] = entailment_result.contradictions
                        
                        # STRICT FILTER: Only keep ENTAIL judgments with sufficient confidence
                        if (entailment_result.judgment == EntailmentJudgment.ENTAIL and 
                            entailment_result.confidence >= entailment_threshold):
                            entailment_verified.append(candidate)
                        elif entailment_result.judgment == EntailmentJudgment.NEUTRAL and entailment_result.confidence >= 0.5:
                            # NEUTRAL with moderate confidence - keep but flag
                            candidate['entailment_warning'] = True
                            entailment_verified.append(candidate)
                        else:
                            # Log rejections for debugging
                            if getattr(self.vector_config, 'enable_validation_debug', False):
                                print(f"    ❌ ENTAILMENT_REJECTED: {candidate.get('start_time', 0):.1f}-{candidate.get('end_time', 0):.1f}s", flush=True)
                                print(f"       Judgment: {entailment_result.judgment.value}, Confidence: {entailment_result.confidence:.2f}", flush=True)
                                if entailment_result.contradictions:
                                    print(f"       Contradictions: {entailment_result.contradictions[:2]}", flush=True)
                    
                    except Exception as e:
                        print(f"    ⚠️ Entailment verification error: {e}", flush=True)
                        # On error, include candidate with neutral score
                        candidate = candidate.copy()
                        candidate['entailment_score'] = 0.5
                        candidate['entailment_warning'] = True
                        entailment_verified.append(candidate)
                
                # Fallback: if no candidates pass entailment, use best with warning
                if not entailment_verified and validated_candidates:
                    print(f"    ⚠️ No candidates passed entailment, using best semantic match with warning", flush=True)
                    best_semantic = validated_candidates[0].copy()
                    best_semantic['entailment_score'] = 0.3
                    best_semantic['entailment_warning'] = True
                    entailment_verified = [best_semantic]
                
                # Log entailment stats
                entail_count = sum(1 for c in entailment_verified if c.get('entailment_judgment') == 'ENTAIL')
                print(f"    ✅ Entailment: {entail_count}/{len(validated_candidates)} candidates verified", flush=True)
                
                validated_candidates = entailment_verified
            
            # Strategy 3: Frame-level visual validation (if enabled)
            # This provides additional temporal state and action progression verification
            validated_candidates_visual = []
            if self.visual_validator and self.vector_config.enable_visual_validation:
                print(f"    🔍 Applying frame-level visual validation...", flush=True)
                
                # Validate each candidate in parallel (with rate limiting)
                validation_tasks = []
                for candidate in validated_candidates:
                    task = self.visual_validator.validate_match(
                        script_segment=script_seg['text'],
                        candidate_clip=candidate,
                        video_no=video_no,
                        unique_id="clip_matcher"
                    )
                    validation_tasks.append((candidate, task))
                
                # Process validations
                for candidate, task in validation_tasks:
                    try:
                        validation = await task
                        
                        if validation['is_valid']:
                            # Apply timing adjustment if recommended
                            adjust_by = validation['recommended_adjustment'].get('adjust_start_by', 0)
                            if abs(adjust_by) > 0.5:  # Only adjust if significant (>0.5s)
                                candidate = candidate.copy()
                                candidate['start_time'] = max(0, candidate['start_time'] + adjust_by)
                                print(f"    ⏱️ Adjusted timing by {adjust_by:+.1f}s", flush=True)
                            
                            # Add validation metadata
                            candidate['validation_score'] = validation['validation_score']
                            candidate['validation_issues'] = validation['issues']
                            candidate['frame_descriptions'] = validation.get('frame_descriptions', [])
                            
                            validated_candidates_visual.append(candidate)
                        else:
                            # Log why candidate was rejected
                            issues = validation.get('issues', [])
                            if issues:
                                print(f"    ⚠️ Candidate rejected: {', '.join(issues[:2])}", flush=True)
                    except Exception as e:
                        print(f"    ⚠️ Validation error: {e}", flush=True)
                        # On error, include candidate anyway (fallback)
                        validated_candidates_visual.append(candidate)
                
                # If no candidates passed validation, use best semantic match with warning
                if not validated_candidates_visual and validated_candidates:
                    print(f"    ⚠️ No candidates passed visual validation, using best semantic match", flush=True)
                    best_semantic = validated_candidates[0].copy()
                    best_semantic['validation_score'] = 0.4  # Low confidence
                    best_semantic['visual_warning'] = True
                    validated_candidates_visual = [best_semantic]
                
                validated_candidates = validated_candidates_visual
            
            # Strategy 4: Apply diversity penalties
            if getattr(self.vector_config, 'enable_diversity_penalty', True):
                validated_candidates = self._apply_diversity_penalty(
                    candidates=validated_candidates,
                    used_segments=used_segments,
                    partition_usage=partition_usage,
                    partition_boundaries=partition_boundaries,
                    max_clips_per_partition=max_clips_per_partition
                )
            
            # Strategy 5: Coverage-aware selection with rebalanced scoring (entailment prioritized)
            previous_match = matches[-1] if matches else None
            video_progress = idx / len(script_segments)  # Expected progress ratio
            
            best_clip = self._select_best_with_coverage(
                candidates=validated_candidates,
                previous_match=previous_match,
                partition_boundaries=partition_boundaries,
                partition_usage=partition_usage,
                video_progress=video_progress,
                video_duration=video_duration
            )
            
            # Update tracking state
            if best_clip:
                clip_start = best_clip.get('start_time', 0)
                clip_end = best_clip.get('end_time', 0)
                used_segments.add((clip_start, clip_end))
                
                # Update partition usage
                clip_partition = self._get_partition_index(clip_start, partition_boundaries)
                partition_usage[clip_partition] = partition_usage.get(clip_partition, 0) + 1
            
            # Get alternatives (exclude best match)
            alternatives = [
                c for c in validated_candidates 
                if c.get('start_time') != best_clip.get('start_time')
            ][:3]
            
            # Calculate duration ratio for mismatch detection
            clip_duration = best_clip.get('end_time', 0) - best_clip.get('start_time', 0)
            expected_duration = script_seg.get('expected_duration', clip_duration)  # From TTS or estimate
            duration_ratio = clip_duration / expected_duration if expected_duration > 0 else 1.0
            
            # Check for duration mismatch
            duration_warning_ratio = self.vector_config.duration_mismatch_warning_ratio if hasattr(self.vector_config, 'duration_mismatch_warning_ratio') else 2.0
            duration_warning = None
            if duration_ratio > duration_warning_ratio:
                duration_warning = f"DURATION_MISMATCH: Clip is {duration_ratio:.1f}x longer than expected ({clip_duration:.1f}s vs {expected_duration:.1f}s)"
                print(f"    ⚠️ {duration_warning}", flush=True)
            elif duration_ratio < 0.5:
                duration_warning = f"DURATION_MISMATCH: Clip is too short ({clip_duration:.1f}s vs expected {expected_duration:.1f}s)"
                print(f"    ⚠️ {duration_warning}", flush=True)
            
            # Add duration info to best_clip
            best_clip['duration_ratio'] = duration_ratio
            if duration_warning:
                existing_issues = best_clip.get('validation_issues', [])
                best_clip['validation_issues'] = existing_issues + [duration_warning]
            
            matches.append({
                'script_segment': script_seg,
                'matched_clip': best_clip,
                'confidence': best_clip.get('final_score', best_clip.get('similarity_score', 0.0)),
                'alternatives': alternatives,
                'duration_ratio': duration_ratio
            })
            
            validation_score = best_clip.get('validation_score')
            validation_info = ""
            if validation_score is not None:
                validation_info = f" [validation: {validation_score:.2f}]"
                issues = best_clip.get('validation_issues', [])
                if issues:
                    validation_info += f" [issues: {len(issues)}]"
            
            # Add duration ratio to output
            duration_info = f" [duration: {duration_ratio:.1f}x]" if abs(duration_ratio - 1.0) > 0.3 else ""
            
            print(f"    ✓ Matched: {best_clip.get('start_time', 0):.1f}s - {best_clip.get('end_time', 0):.1f}s "
                  f"(confidence: {best_clip.get('final_score', 0.0):.2f}{validation_info}{duration_info})", flush=True)
            
            # Log validation details if available
            if validation_score is not None and best_clip.get('validation_issues'):
                for issue in best_clip['validation_issues'][:2]:  # Log first 2 issues
                    print(f"      ⚠️ {issue}", flush=True)
        
        # === COVERAGE STATISTICS ===
        # Calculate and log diversity metrics
        clips_with_matches = [m for m in matches if m.get('matched_clip')]
        if clips_with_matches:
            unique_clips = len(set([
                (m['matched_clip']['start_time'], m['matched_clip']['end_time']) 
                for m in clips_with_matches
            ]))
            coverage_ratio = unique_clips / len(clips_with_matches) if clips_with_matches else 0
            
            used_start_times = [m['matched_clip']['start_time'] for m in clips_with_matches]
            time_std_dev = float(np.std(used_start_times)) if len(used_start_times) > 1 else 0
            time_coverage_ratio = time_std_dev / video_duration if video_duration > 0 else 0
            
            # Calculate partition distribution
            partition_distribution = {}
            for m in clips_with_matches:
                start = m['matched_clip']['start_time']
                part_idx = self._get_partition_index(start, partition_boundaries)
                partition_distribution[part_idx] = partition_distribution.get(part_idx, 0) + 1
            
            partitions_used = len([k for k, v in partition_distribution.items() if v > 0])
            
            # Calculate grounding statistics
            grounding_scores = [
                m['matched_clip'].get('grounding_score', 0.5) 
                for m in clips_with_matches 
                if m['matched_clip'].get('grounding_score') is not None
            ]
            avg_grounding = sum(grounding_scores) / len(grounding_scores) if grounding_scores else 0
            grounding_warnings = len([
                m for m in clips_with_matches 
                if m['matched_clip'].get('grounding_warning', False)
            ])
            high_grounding = len([s for s in grounding_scores if s >= 0.65])
            
            # NEW: Calculate entailment statistics
            entailment_scores = [
                m['matched_clip'].get('entailment_score', 0.5)
                for m in clips_with_matches
                if m['matched_clip'].get('entailment_score') is not None
            ]
            avg_entailment = sum(entailment_scores) / len(entailment_scores) if entailment_scores else 0
            entail_count = len([
                m for m in clips_with_matches
                if m['matched_clip'].get('entailment_judgment') == 'ENTAIL'
            ])
            contradict_count = len([
                m for m in clips_with_matches
                if m['matched_clip'].get('entailment_judgment') == 'CONTRADICT'
            ])
            entailment_warnings = len([
                m for m in clips_with_matches
                if m['matched_clip'].get('entailment_warning', False)
            ])
            
            print(f"📊 Clip Selection Stats:", flush=True)
            print(f"   Total segments: {len(matches)}", flush=True)
            print(f"   Unique clips used: {unique_clips}", flush=True)
            print(f"   Coverage ratio: {coverage_ratio:.1%}", flush=True)
            print(f"   Time distribution std: {time_std_dev:.1f}s ({time_coverage_ratio:.1%} of video)", flush=True)
            print(f"   Partitions used: {partitions_used}/{num_partitions}", flush=True)
            print(f"   Partition distribution: {dict(sorted(partition_distribution.items()))}", flush=True)
            
            # NEW: Entailment statistics (highest priority metric)
            if entailment_scores:
                print(f"📊 Visual Entailment Stats:", flush=True)
                print(f"   Average entailment score: {avg_entailment:.2f}", flush=True)
                print(f"   ENTAIL judgments: {entail_count}/{len(entailment_scores)} ({entail_count/len(entailment_scores)*100:.0f}%)", flush=True)
                if contradict_count > 0:
                    print(f"   ⚠️ CONTRADICT judgments: {contradict_count} (these should be investigated)", flush=True)
                if entailment_warnings > 0:
                    print(f"   ⚠️ Entailment warnings: {entailment_warnings} clips used with warnings", flush=True)
            
            # Grounding statistics
            if grounding_scores:
                print(f"📊 Visual Grounding Stats:", flush=True)
                print(f"   Average grounding score: {avg_grounding:.2f}", flush=True)
                print(f"   High grounding (>=0.65): {high_grounding}/{len(grounding_scores)} ({high_grounding/len(grounding_scores)*100:.0f}%)", flush=True)
                if grounding_warnings > 0:
                    print(f"   ⚠️ Grounding warnings: {grounding_warnings} clips used without grounding", flush=True)
            
            # Warning if coverage is poor
            if coverage_ratio < 0.85:
                print(f"   ⚠️ WARNING: Coverage ratio {coverage_ratio:.1%} is below target 85%", flush=True)
            if time_coverage_ratio < 0.30:
                print(f"   ⚠️ WARNING: Time distribution {time_coverage_ratio:.1%} is below target 30%", flush=True)
            if grounding_scores and avg_grounding < 0.60:
                print(f"   ⚠️ WARNING: Average grounding score {avg_grounding:.2f} is below target 0.60", flush=True)
            if entailment_scores and avg_entailment < 0.60:
                print(f"   ⚠️ WARNING: Average entailment score {avg_entailment:.2f} is below target 0.60", flush=True)
        
        print(f"✅ Matching complete: {len(matches)} segments matched", flush=True)
        return matches

    async def validate_with_visual_search(
        self,
        query_text: str,
        video_no: str,
        candidates: List[Dict]
    ) -> List[Dict]:
        """
        Validate candidates using Memories.ai visual search.
        
        Args:
            query_text: Script segment text
            video_no: Video identifier
            candidates: List of candidate clips from vector search
            
        Returns:
            Candidates with confidence boosts if Memories.ai confirms match
        """
        validated = []
        
        for candidate in candidates:
            candidate = candidate.copy()  # Don't mutate original
            
            try:
                # Search within the candidate time window
                start_time = candidate.get('start_time', 0)
                end_time = candidate.get('end_time', 0)
                
                # Search with a small window around the candidate time
                window_padding = 30  # seconds
                search_start = max(0, start_time - window_padding)
                search_end = end_time + window_padding
                
                # Use Memories.ai search to validate
                # Note: This is a simplified validation - in practice you might
                # want to use a more sophisticated search
                search_results = await self.memories_client.search_video_windowed(
                    query=query_text,
                    video_no=video_no,
                    time_start=search_start,
                    time_end=search_end
                )
                
                # Boost confidence if Memories.ai also finds this relevant
                if search_results and len(search_results) > 0:
                    # Check if any result overlaps with our candidate
                    for result in search_results:
                        result_start = float(result.get('start', result.get('start_time', 0)))
                        result_end = float(result.get('end', result.get('end_time', result_start + 5)))
                        
                        # Check for overlap
                        if (result_start <= end_time and result_end >= start_time):
                            candidate['confidence_boost'] = self.validation_boost
                            candidate['memories_validation'] = True
                            break
                    else:
                        candidate['confidence_boost'] = 0.0
                        candidate['memories_validation'] = False
                else:
                    candidate['confidence_boost'] = 0.0
                    candidate['memories_validation'] = False
                    
            except Exception as e:
                print(f"    ⚠️ Validation error: {e}", flush=True)
                candidate['confidence_boost'] = 0.0
                candidate['memories_validation'] = False
            
            validated.append(candidate)
        
        return validated

    def apply_temporal_coherence(
        self,
        candidates: List[Dict],
        previous_match: Optional[Dict] = None
    ) -> Dict:
        """
        Score candidates based on temporal coherence (narrative flow).
        
        Prefers clips that maintain sequential narrative flow.
        
        Args:
            candidates: List of candidate clips with similarity scores
            previous_match: Previous match dict (from previous script segment)
            
        Returns:
            Best candidate with final_score added
        """
        if not previous_match:
            # First clip - just return best semantic match
            best = candidates[0].copy()
            best['temporal_score'] = 1.0
            best['final_score'] = (
                best.get('similarity_score', 0.0) * self.semantic_weight +
                best.get('confidence_boost', 0.0) +
                best.get('temporal_score', 1.0) * self.temporal_weight
            )
            return best
        
        # Get previous clip end time
        prev_clip = previous_match.get('matched_clip')
        if not prev_clip:
            # No previous clip, treat as first
            return self.apply_temporal_coherence(candidates, None)
        
        prev_end_time = prev_clip.get('end_time', 0)
        
        # Score each candidate based on temporal distance
        for candidate in candidates:
            start_time = candidate.get('start_time', 0)
            time_gap = abs(start_time - prev_end_time)
            
            # Prefer clips that come sequentially (small gap)
            if time_gap < 30:  # Within 30 seconds
                candidate['temporal_score'] = 1.0
            elif time_gap < 120:  # Within 2 minutes
                candidate['temporal_score'] = 0.8
            elif time_gap < 300:  # Within 5 minutes
                candidate['temporal_score'] = 0.5
            else:
                candidate['temporal_score'] = 0.2
            
            # Combined score (updated to include validation score if available)
            validation_score = candidate.get('validation_score')
            if validation_score is not None:
                # New scoring: 40% validation + 30% semantic + 15% visual search boost + 15% temporal
                candidate['final_score'] = (
                    validation_score * 0.4 +
                    candidate.get('similarity_score', 0.0) * 0.3 +
                    candidate.get('confidence_boost', 0.0) * 0.15 +
                    candidate.get('temporal_score', 1.0) * 0.15
                )
            else:
                # Original scoring (for backwards compatibility)
                candidate['final_score'] = (
                    candidate.get('similarity_score', 0.0) * self.semantic_weight +
                    candidate.get('confidence_boost', 0.0) +
                    candidate.get('temporal_score', 1.0) * self.temporal_weight
                )
        
        # Return best combined score
        candidates.sort(key=lambda x: x.get('final_score', 0.0), reverse=True)
        return candidates[0].copy()

    def _get_partition_index(
        self,
        start_time: float,
        partition_boundaries: List[tuple]
    ) -> int:
        """
        Map a timestamp to its partition index.
        
        Args:
            start_time: Clip start time
            partition_boundaries: List of (start, end) tuples for each partition
            
        Returns:
            Index of the partition containing this timestamp
        """
        for idx, (p_start, p_end) in enumerate(partition_boundaries):
            if start_time >= p_start and start_time < p_end:
                return idx
        # Default to last partition if beyond end
        return len(partition_boundaries) - 1

    def _calculate_overlap_ratio(
        self,
        range1: tuple,
        range2: tuple
    ) -> float:
        """
        Calculate overlap ratio between two time ranges.
        
        Args:
            range1: (start, end) tuple
            range2: (start, end) tuple
            
        Returns:
            Overlap as fraction of range1's duration (0.0 to 1.0)
        """
        start1, end1 = range1
        start2, end2 = range2
        
        overlap = max(0, min(end1, end2) - max(start1, start2))
        duration1 = end1 - start1
        
        if duration1 <= 0:
            return 0.0
        return overlap / duration1

    def _apply_diversity_penalty(
        self,
        candidates: List[Dict],
        used_segments: set,
        partition_usage: Dict[int, int],
        partition_boundaries: List[tuple],
        max_clips_per_partition: int
    ) -> List[Dict]:
        """
        Apply penalties for already-used segments and over-represented partitions.
        
        Args:
            candidates: List of candidate clips
            used_segments: Set of (start, end) tuples already used
            partition_usage: Dict mapping partition index to usage count
            partition_boundaries: List of (start, end) tuples defining partitions
            max_clips_per_partition: Maximum allowed clips per partition
            
        Returns:
            Candidates with diversity_penalty scores added
        """
        for candidate in candidates:
            start = candidate.get('start_time', 0)
            end = candidate.get('end_time', 0)
            
            # Penalty 1: Exact reuse (SEVERE)
            if (start, end) in used_segments:
                candidate['diversity_penalty'] = 0.95  # Nearly eliminate
                candidate['overlap_penalty'] = 0.95
                candidate['partition_penalty'] = 0.0
                continue
            
            # Penalty 2: Overlap with used segments
            max_overlap = 0.0
            for used_start, used_end in used_segments:
                overlap_ratio = self._calculate_overlap_ratio(
                    (start, end), (used_start, used_end)
                )
                max_overlap = max(max_overlap, overlap_ratio)
            
            candidate['overlap_penalty'] = max_overlap * 0.7  # Up to 70% penalty
            
            # Penalty 3: Partition overuse
            candidate_partition = self._get_partition_index(start, partition_boundaries)
            usage_count = partition_usage.get(candidate_partition, 0)
            
            if usage_count >= max_clips_per_partition:
                candidate['partition_penalty'] = 0.8  # Strong penalty for overuse
            else:
                # Gradual penalty as partition fills up
                candidate['partition_penalty'] = min(0.3, usage_count * 0.15)
            
            # Combined diversity penalty (weighted average)
            candidate['diversity_penalty'] = (
                candidate['overlap_penalty'] * 0.5 +
                candidate['partition_penalty'] * 0.5
            )
        
        return candidates

    def _select_best_with_coverage(
        self,
        candidates: List[Dict],
        previous_match: Optional[Dict],
        partition_boundaries: List[tuple],
        partition_usage: Dict[int, int],
        video_progress: float,
        video_duration: float
    ) -> Dict:
        """
        Select clip that balances semantic quality, temporal coherence, and coverage.
        
        Args:
            candidates: List of candidate clips with similarity and diversity scores
            previous_match: Previous match dict (from previous script segment)
            partition_boundaries: List of (start, end) tuples defining partitions
            partition_usage: Dict mapping partition index to usage count
            video_progress: Expected progress ratio (0.0 to 1.0)
            video_duration: Total video duration
            
        Returns:
            Best candidate with final_score computed using coverage-aware scoring
        """
        if not candidates:
            return None
        
        expected_position = video_progress * video_duration
        
        for candidate in candidates:
            start = candidate.get('start_time', 0)
            end = candidate.get('end_time', 0)
            
            # === TEMPORAL COHERENCE SCORING ===
            if previous_match and previous_match.get('matched_clip'):
                prev_end = previous_match['matched_clip'].get('end_time', 0)
                time_gap = start - prev_end  # Signed difference
                
                # Penalize going backward in timeline
                if start < prev_end:
                    candidate['temporal_score'] = 0.1  # Strong penalty for backtracking
                elif abs(time_gap) < 30:  # Within 30 seconds forward
                    candidate['temporal_score'] = 1.0
                elif abs(time_gap) < 120:  # Within 2 minutes
                    candidate['temporal_score'] = 0.8
                else:
                    candidate['temporal_score'] = 0.5
            else:
                candidate['temporal_score'] = 1.0  # First clip
            
            # === COVERAGE SCORE ===
            # Prefer clips near expected timeline position
            position_error = abs(start - expected_position)
            coverage_score = max(0.0, 1.0 - (position_error / video_duration))
            candidate['coverage_score'] = coverage_score
            
            # === PARTITION BALANCE BOOST ===
            candidate_partition = self._get_partition_index(start, partition_boundaries)
            partition_boost = 0.0
            
            # Strong boost for completely unused partitions
            if partition_usage.get(candidate_partition, 0) == 0:
                partition_boost = 0.3
            # Small boost for under-used partitions
            elif partition_usage.get(candidate_partition, 0) == 1:
                partition_boost = 0.1
            
            candidate['partition_boost'] = partition_boost
            
            # === FINAL SCORE CALCULATION (Rebalanced with Entailment Priority) ===
            # Based on research: Entailment > Validation > Grounding > Semantic
            validation_score = candidate.get('validation_score')
            semantic_score = candidate.get('similarity_score', 0.0)
            diversity_penalty = candidate.get('diversity_penalty', 0.0)
            grounding_score = candidate.get('grounding_score', 0.5)  # Default 0.5 if not grounded
            entailment_score = candidate.get('entailment_score', 0.5)  # NEW: Entailment score
            
            # Get rebalanced weights from config (entailment prioritized)
            entailment_weight = getattr(self.vector_config, 'weight_entailment', 0.35)  # NEW: Highest
            validation_weight = getattr(self.vector_config, 'weight_validation', 0.25)
            grounding_weight = getattr(self.vector_config, 'weight_grounding', 0.15)
            semantic_weight = getattr(self.vector_config, 'weight_semantic', 0.10)  # REDUCED
            temporal_weight = getattr(self.vector_config, 'weight_temporal', 0.10)
            coverage_weight = getattr(self.vector_config, 'weight_coverage', 0.05)
            partition_weight = getattr(self.vector_config, 'partition_balance_weight', 0.05)
            diversity_weight = getattr(self.vector_config, 'diversity_weight', 0.15)
            
            # Entailment boost for high-confidence ENTAIL judgments
            entailment_boost = 0.0
            if candidate.get('entailment_judgment') == 'ENTAIL':
                if entailment_score >= 0.85:
                    entailment_boost = 0.15  # Strong boost for confident entailment
                elif entailment_score >= 0.70:
                    entailment_boost = 0.08
            elif candidate.get('entailment_judgment') == 'CONTRADICT':
                entailment_boost = -0.20  # Penalty for contradictions
            
            # Grounding boost for high-quality grounded clips (reduced from before)
            grounding_boost = 0.0
            if grounding_score > 0.80:
                grounding_boost = 0.10  # Reduced from 0.2
            elif grounding_score > 0.70:
                grounding_boost = 0.05  # Reduced from 0.1
            
            # Warning penalty for clips with entailment/grounding warnings
            warning_penalty = 0.0
            if candidate.get('entailment_warning'):
                warning_penalty += 0.05
            if candidate.get('grounding_warning'):
                warning_penalty += 0.05
            
            if validation_score is not None:
                # Full pipeline scoring: Entailment > Validation > Grounding > Semantic
                candidate['final_score'] = (
                    entailment_score * entailment_weight +        # NEW: Entailment is #1 priority
                    validation_score * validation_weight +         # Frame-level validation
                    grounding_score * grounding_weight +           # Object/action presence
                    semantic_score * semantic_weight +             # Reduced embedding similarity
                    candidate['temporal_score'] * temporal_weight +
                    candidate['coverage_score'] * coverage_weight +
                    entailment_boost +                             # Bonus for confident entailment
                    grounding_boost +                              # Bonus for well-grounded
                    candidate['partition_boost'] * partition_weight -
                    diversity_penalty * diversity_weight -
                    warning_penalty                                # Penalty for warnings
                )
            else:
                # Without visual validation: Entailment + Grounding dominate
                candidate['final_score'] = (
                    entailment_score * 0.40 +                      # Entailment dominates
                    grounding_score * 0.25 +                       # Grounding is second
                    semantic_score * 0.15 +
                    candidate['temporal_score'] * 0.10 +
                    candidate['coverage_score'] * 0.05 +
                    entailment_boost +
                    grounding_boost +
                    candidate['partition_boost'] * partition_weight -
                    diversity_penalty * 0.15 -
                    warning_penalty
                )
        
        # Sort by final score and return best
        candidates.sort(key=lambda x: x.get('final_score', 0.0), reverse=True)
        return candidates[0].copy()

