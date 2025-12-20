"""
Action Boundary Detector - Detects precise action start/end points within clips.

Uses high-frequency frame sampling and visual similarity analysis to identify
natural action boundaries for more precise clip timing.
"""

from typing import List, Optional
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import get_settings
from app.services.memories_client import MemoriesAIClient


class ActionBoundaryDetector:
    """
    Detects action boundaries within video clips by analyzing visual changes.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.vector_config = self.settings.features.vector_matching
        self.memories_client = MemoriesAIClient()
        
        # Load embedding model for text similarity
        model_name = self.vector_config.embedding_model_name
        self.embedding_model = SentenceTransformer(model_name)
    
    async def detect_action_boundaries(
        self,
        video_no: str,
        start_time: float,
        end_time: float,
        unique_id: str = "default",
        sample_rate: Optional[float] = None
    ) -> List[float]:
        """
        Detect precise action start/end points within a clip.
        
        Args:
            video_no: Video identifier
            start_time: Clip start time in seconds
            end_time: Clip end time in seconds
            unique_id: Workspace identifier
            sample_rate: Seconds between samples (default from config)
            
        Returns:
            List of boundary timestamps (includes start_time and end_time)
        """
        if sample_rate is None:
            sample_rate = getattr(self.vector_config, 'boundary_sample_rate', 0.5)
        
        duration = end_time - start_time
        if duration <= 0:
            return [start_time, end_time]
        
        # Sample frames at high frequency
        timestamps = []
        current = start_time
        
        while current < end_time:
            timestamps.append(current)
            current += sample_rate
        
        # Ensure end_time is included
        if timestamps[-1] < end_time:
            timestamps.append(end_time)
        
        # Get visual descriptions for each sample
        frame_descriptions = []
        
        for i, timestamp in enumerate(timestamps):
            # Determine end of sample window
            if i < len(timestamps) - 1:
                sample_end = timestamps[i + 1]
            else:
                sample_end = min(timestamp + sample_rate, end_time)
            
            try:
                description = await self.memories_client.get_visual_description(
                    video_no=video_no,
                    start_time=timestamp,
                    end_time=sample_end,
                    unique_id=unique_id
                )
                frame_descriptions.append({
                    'time': timestamp,
                    'description': description
                })
            except Exception as e:
                print(f"⚠️ Failed to get description for {timestamp:.1f}s: {e}", flush=True)
                frame_descriptions.append({
                    'time': timestamp,
                    'description': ""
                })
        
        # Detect significant visual changes (action boundaries)
        boundaries = [start_time]
        
        similarity_threshold = getattr(
            self.vector_config, 
            'boundary_similarity_threshold', 
            0.7
        )
        
        for i in range(1, len(frame_descriptions)):
            prev_desc = frame_descriptions[i-1]['description']
            curr_desc = frame_descriptions[i]['description']
            
            if not prev_desc or not curr_desc:
                # Missing description, assume boundary
                boundaries.append(frame_descriptions[i]['time'])
                continue
            
            # Compute description similarity
            similarity = self._compute_text_similarity(prev_desc, curr_desc)
            
            # If descriptions differ significantly, it's a boundary
            if similarity < similarity_threshold:
                boundaries.append(frame_descriptions[i]['time'])
        
        boundaries.append(end_time)
        
        # Remove duplicates and sort
        boundaries = sorted(list(set(boundaries)))
        
        return boundaries
    
    def _compute_text_similarity(self, text1: str, text2: str) -> float:
        """
        Compute semantic similarity between two text descriptions.
        
        Args:
            text1: First description
            text2: Second description
            
        Returns:
            Similarity score (0-1)
        """
        if not text1 or not text2:
            return 0.0
        
        emb1 = self.embedding_model.encode(text1)
        emb2 = self.embedding_model.encode(text2)
        
        similarity = cosine_similarity(
            emb1.reshape(1, -1),
            emb2.reshape(1, -1)
        )[0][0]
        
        return float(similarity)

