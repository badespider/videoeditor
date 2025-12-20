"""
Video Indexer Service - Creates embeddings for video scenes/chapters.

Creates semantic embeddings from Memories.ai chapters to enable
vector-based script-to-clip matching.
"""

import json
from typing import List, Dict, Optional
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings
from app.services.memories_client import MemoriesAIClient
from app.services.vector_store import VectorStore


class VideoIndexer:
    """
    Creates and stores embeddings for video scenes/chapters.
    """

    def __init__(self):
        self.settings = get_settings()
        self.memories_client = MemoriesAIClient()
        self.vector_store = VectorStore()
        
        # Initialize embedding model (cached)
        model_name = self.settings.features.vector_matching.embedding_model_name
        print(f"🤖 Loading embedding model: {model_name}", flush=True)
        self.embedding_model = SentenceTransformer(model_name)
        print(f"✅ Embedding model loaded", flush=True)

    async def index_video(
        self, 
        video_no: str, 
        video_path: Optional[str] = None
    ) -> List[Dict]:
        """
        Create embeddings for all chapters/scenes in a video.
        
        Uses fine-grained segmentation if enabled to split long chapters.
        
        Args:
            video_no: Memories.ai video identifier
            video_path: Optional video file path (not used, kept for API compatibility)
            
        Returns:
            List of embedding dicts with metadata
        """
        print(f"📚 Indexing video: {video_no}", flush=True)
        
        # Get chapters from Memories.ai
        chapters = await self.memories_client.generate_summary(
            video_no=video_no,
            summary_type="CHAPTER"
        )
        
        if not chapters:
            print(f"⚠️ No chapters found for video {video_no}", flush=True)
            return []
        
        # Apply fine-grained segmentation if enabled
        if self.vector_config.enable_fine_grained_indexing:
            chapters = await self._apply_fine_grained_segmentation(
                video_no,
                chapters
            )
        
        print(f"📖 Found {len(chapters)} chapters/segments, creating embeddings...", flush=True)
        
        # Create embeddings for each chapter
        scene_embeddings = []
        
        for idx, chapter in enumerate(chapters):
            start_time = self._parse_time(chapter.get("start", 0))
            end_time = self._parse_time(chapter.get("end", 0))
            title = chapter.get("title", f"Chapter {idx + 1}")
            description = chapter.get("description") or chapter.get("summary", "")
            
            # Get visual description from Memories.ai (or use pre-computed if available)
            visual_desc = chapter.get('visual_desc', "")
            if not visual_desc:
                try:
                    visual_desc = await self.memories_client.get_visual_description(
                        video_no=video_no,
                        start_time=start_time,
                        end_time=end_time
                    )
                except Exception as e:
                    print(f"⚠️ Could not get visual description for chapter {idx + 1}: {e}", flush=True)
            
            # Get transcription if available (from chapter metadata or separate API call)
            transcription = chapter.get("transcription") or chapter.get("text", "")
            
            # Combine into rich text representation
            scene_text = self._build_scene_text(title, description, visual_desc, transcription)
            
            # Generate embedding
            embedding = self.embedding_model.encode(scene_text, convert_to_numpy=True)
            
            metadata = {
                "title": title,
                "description": description,
                "visual_desc": visual_desc[:500] if visual_desc else "",  # Truncate for storage
                "transcription": transcription[:500] if transcription else "",
                "index": idx
            }
            
            scene_embeddings.append({
                "video_no": video_no,
                "start_time": float(start_time),
                "end_time": float(end_time),
                "embedding": embedding,
                "metadata": metadata
            })
            
            print(f"  ✓ Chapter {idx + 1}: {start_time:.1f}s - {end_time:.1f}s", flush=True)
        
        # Store in Redis/RediSearch
        await self.vector_store.store_scene_embeddings(video_no, scene_embeddings)
        
        print(f"✅ Indexed {len(scene_embeddings)} chapters for video {video_no}", flush=True)
        return scene_embeddings

    def _build_scene_text(
        self, 
        title: str, 
        description: str, 
        visual_desc: str, 
        transcription: str
    ) -> str:
        """
        Combine chapter metadata into a rich text representation for embedding.
        """
        parts = []
        
        if title:
            parts.append(f"Title: {title}")
        
        if description:
            parts.append(f"Description: {description}")
        
        if visual_desc:
            parts.append(f"Visual: {visual_desc}")
        
        if transcription:
            parts.append(f"Dialogue: {transcription}")
        
        return " ".join(parts)

    def _parse_time(self, time_str: str) -> float:
        """
        Convert timestamp string to seconds.
        
        Handles formats:
        - "00:01:30" (HH:MM:SS)
        - "01:30" (MM:SS)
        - "90" (seconds)
        - float/int directly
        """
        if isinstance(time_str, (int, float)):
            return float(time_str)
        
        if not time_str:
            return 0.0
        
        time_str = str(time_str).strip()
        
        # Try direct float conversion first
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

    async def get_video_embeddings(self, video_no: str) -> List[Dict]:
        """
        Retrieve stored embeddings for a video.
        
        Args:
            video_no: Memories.ai video identifier
            
        Returns:
            List of embedding dicts with metadata
        """
        return await self.vector_store.get_video_embeddings(video_no)

    async def is_indexed(self, video_no: str) -> bool:
        """
        Check if a video has been indexed.
        
        Args:
            video_no: Memories.ai video identifier
            
        Returns:
            True if video has embeddings stored
        """
        embeddings = await self.get_video_embeddings(video_no)
        return len(embeddings) > 0
    
    async def _apply_fine_grained_segmentation(
        self,
        video_no: str,
        chapters: List[Dict],
        unique_id: str = "default"
    ) -> List[Dict]:
        """
        Split long chapters into finer segments for better matching precision.
        
        Args:
            video_no: Video identifier
            chapters: List of chapter dicts with 'start', 'end', 'title', etc.
            unique_id: Workspace identifier
            
        Returns:
            List of fine-grained segments (chapters split if needed)
        """
        max_duration = self.vector_config.max_chapter_segment_duration
        preferred_duration = self.vector_config.preferred_segment_duration
        
        fine_scenes = []
        
        for chapter in chapters:
            start = self._parse_time(chapter.get("start", 0))
            end = self._parse_time(chapter.get("end", 0))
            duration = end - start
            
            if duration <= max_duration:
                # Chapter is short enough, use as-is
                fine_scenes.append(chapter)
                continue
            
            # Chapter is too long, split into segments
            print(f"  📐 Splitting long chapter ({duration:.1f}s): {chapter.get('title', '')[:40]}...", flush=True)
            
            # Calculate number of segments needed
            num_splits = max(2, int(duration / preferred_duration))
            segment_duration = duration / num_splits
            
            # Split chapter into segments
            for i in range(num_splits):
                seg_start = start + (i * segment_duration)
                seg_end = min(start + ((i + 1) * segment_duration), end)
                
                if seg_end <= seg_start:
                    continue
                
                # Get visual description for this segment
                visual_desc = ""
                try:
                    visual_desc = await self.memories_client.get_visual_description(
                        video_no=video_no,
                        start_time=seg_start,
                        end_time=seg_end,
                        unique_id=unique_id
                    )
                except Exception as e:
                    print(f"    ⚠️ Could not get visual description for segment {i+1}: {e}", flush=True)
                
                # Create fine-grained segment
                segment = chapter.copy()
                segment['start'] = seg_start
                segment['end'] = seg_end
                segment['title'] = f"{chapter.get('title', 'Chapter')} - Part {i+1}"
                segment['description'] = f"{chapter.get('description', '')} [Segment {i+1}/{num_splits}]"
                segment['visual_desc'] = visual_desc
                segment['parent_chapter'] = chapter.get('title')
                segment['segment_index'] = i
                segment['total_segments'] = num_splits
                
                fine_scenes.append(segment)
            
            print(f"    ✓ Split into {num_splits} segments", flush=True)
        
        if len(fine_scenes) > len(chapters):
            print(f"📊 Fine-grained segmentation: {len(chapters)} chapters → {len(fine_scenes)} segments", flush=True)
        
        return fine_scenes

