"""
Script Processor Service - Processes user scripts and generates embeddings.

Segments scripts into meaningful units and creates embeddings for matching.
"""

import re
from typing import List, Dict, Optional
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings


class ScriptProcessor:
    """
    Processes user scripts and generates embeddings for semantic matching.
    """

    def __init__(self):
        self.settings = get_settings()
        self.vector_config = self.settings.features.vector_matching
        
        # Initialize embedding model (cached)
        model_name = self.vector_config.embedding_model_name
        print(f"🤖 Loading embedding model for script processing: {model_name}", flush=True)
        self.embedding_model = SentenceTransformer(model_name)
        print(f"✅ Script embedding model loaded", flush=True)
        
        # Initialize spaCy for text segmentation (optional, lazy load)
        self.nlp = None

    def _get_nlp(self):
        """Lazy load spaCy model."""
        if self.nlp is None:
            try:
                import spacy
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                print("⚠️ spaCy model 'en_core_web_sm' not found. Using simple segmentation.", flush=True)
                self.nlp = None
        return self.nlp

    async def process_script(
        self, 
        script_text: str, 
        audio_path: Optional[str] = None
    ) -> List[Dict]:
        """
        Process script and generate embeddings for each segment.
        
        Args:
            script_text: Full script text
            audio_path: Optional audio file path for timing alignment
            
        Returns:
            List of segment dicts with:
                - segment_id: int
                - text: str
                - embedding: np.ndarray
                - start_time: Optional[float]
                - end_time: Optional[float]
                - duration: Optional[float]
        """
        print(f"📝 Processing script ({len(script_text)} chars)", flush=True)
        
        # Segment script into meaningful units
        segments = self.segment_script(script_text)
        
        print(f"✂️ Segmented into {len(segments)} segments", flush=True)
        
        # If audio provided, align text to timestamps (future enhancement)
        if audio_path:
            # TODO: Implement audio-text alignment
            pass
        
        # Generate embeddings for each segment
        script_embeddings = []
        for i, segment in enumerate(segments):
            text = segment['text']
            
            # Skip empty segments
            if not text.strip():
                continue
            
            # Generate embedding
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            
            script_embeddings.append({
                'segment_id': i,
                'text': text,
                'embedding': embedding,
                'start_char': segment.get('start_char', 0),
                'end_char': segment.get('end_char', len(text)),
                'duration': segment.get('duration'),
                'start_time': segment.get('start_time'),
                'end_time': segment.get('end_time')
            })
        
        print(f"✅ Generated {len(script_embeddings)} script embeddings", flush=True)
        return script_embeddings

    def segment_script(self, script: str) -> List[Dict]:
        """
        Segment script into meaningful units.
        
        Uses spaCy for intelligent sentence segmentation if available,
        otherwise falls back to simple sentence splitting.
        
        Args:
            script: Full script text
            
        Returns:
            List of segment dicts with text, start_char, end_char
        """
        nlp = self._get_nlp()
        max_length = self.vector_config.max_script_segment_length
        
        if nlp:
            return self._segment_with_spacy(script, nlp, max_length)
        else:
            return self._segment_simple(script, max_length)

    def _segment_with_spacy(self, script: str, nlp, max_length: int) -> List[Dict]:
        """
        Segment using spaCy for better sentence detection.
        """
        doc = nlp(script)
        segments = []
        current_segment = []
        current_length = 0
        start_char = 0
        
        for sent in doc.sents:
            sent_text = sent.text.strip()
            sent_len = len(sent_text)
            
            # If adding this sentence would exceed max length, start new segment
            if current_length + sent_len > max_length and current_segment:
                # Save current segment
                segment_text = " ".join(current_segment)
                segments.append({
                    'text': segment_text,
                    'start_char': start_char,
                    'end_char': start_char + len(segment_text)
                })
                
                # Start new segment
                current_segment = [sent_text]
                start_char = sent.start_char
                current_length = sent_len
            else:
                current_segment.append(sent_text)
                current_length += sent_len + 1  # +1 for space
                if not current_segment:  # First sentence
                    start_char = sent.start_char
        
        # Add final segment
        if current_segment:
            segment_text = " ".join(current_segment)
            segments.append({
                'text': segment_text,
                'start_char': start_char,
                'end_char': start_char + len(segment_text)
            })
        
        return segments

    def _segment_simple(self, script: str, max_length: int) -> List[Dict]:
        """
        Simple segmentation using sentence boundaries (regex).
        """
        # Split on sentence boundaries (. ! ? followed by space or newline)
        sentence_pattern = r'[.!?]+\s+'
        sentences = re.split(sentence_pattern, script)
        
        segments = []
        current_segment = []
        current_length = 0
        start_char = 0
        
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            
            sent_len = len(sent)
            
            # If adding this sentence would exceed max length, start new segment
            if current_length + sent_len > max_length and current_segment:
                # Save current segment
                segment_text = " ".join(current_segment)
                segments.append({
                    'text': segment_text,
                    'start_char': start_char,
                    'end_char': start_char + len(segment_text)
                })
                
                # Start new segment
                current_segment = [sent]
                start_char = script.find(sent, start_char)
                current_length = sent_len
            else:
                current_segment.append(sent)
                current_length += sent_len + 1  # +1 for space
                if not current_segment:  # First sentence
                    start_char = script.find(sent)
        
        # Add final segment
        if current_segment:
            segment_text = " ".join(current_segment)
            segments.append({
                'text': segment_text,
                'start_char': start_char,
                'end_char': start_char + len(segment_text)
            })
        
        return segments

