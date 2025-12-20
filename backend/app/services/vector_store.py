"""
Vector Store Service - Manages Redis/RediSearch vector operations.

Stores and searches video scene embeddings for semantic matching.
"""

import json
import numpy as np
from typing import List, Dict, Optional
import redis
try:
    from redis.commands.search.field import VectorField, TextField, NumericField
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType
    from redis.commands.search.query import Query
    REDIS_SEARCH_AVAILABLE = True
except ImportError:
    # RediSearch module not available - will use fallback cosine similarity
    REDIS_SEARCH_AVAILABLE = False
    print("⚠️ RediSearch module not available - vector search will use fallback method", flush=True)

from app.config import get_settings


class VectorStore:
    """
    Manages Redis/RediSearch vector operations for video embeddings.
    """

    def __init__(self):
        self.settings = get_settings()
        self.redis_config = self.settings.redis
        
        # Connect to Redis
        self.redis_client = redis.Redis(
            host=self.redis_config.host,
            port=self.redis_config.port,
            db=self.redis_config.db,
            password=self.redis_config.password if self.redis_config.password else None,
            decode_responses=False  # Keep binary for vector data
        )
        
        # Get index configuration
        self.index_name = self.settings.features.vector_matching.vector_index_name
        self.embedding_dim = self.settings.features.vector_matching.embedding_dimension
        
        # Index will be created on first use
        self._index_created = False

    async def create_index(self, index_name: Optional[str] = None):
        """
        Create RediSearch vector index if it doesn't exist.
        
        Args:
            index_name: Optional index name override
        """
        if self._index_created:
            return
        
        if not REDIS_SEARCH_AVAILABLE:
            # RediSearch not available - skip index creation, will use fallback
            self._index_created = True
            return
            
        idx_name = index_name or self.index_name
        
        try:
            # Check if index exists
            self.redis_client.ft(idx_name).info()
            print(f"✅ Vector index '{idx_name}' already exists", flush=True)
            self._index_created = True
            return
        except Exception:
            # Index doesn't exist, create it
            pass
        
        try:
            print(f"📚 Creating vector index: {idx_name}", flush=True)
            
            # Define schema
            schema = (
                VectorField(
                    "embedding",
                    "FLAT",
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dim,
                        "DISTANCE_METRIC": "COSINE"
                    }
                ),
                TextField("video_no"),
                NumericField("start_time"),
                NumericField("end_time"),
                TextField("metadata")
            )
            
            # Create index
            self.redis_client.ft(idx_name).create_index(
                schema,
                definition=IndexDefinition(
                    prefix=[f"video_embedding:"],
                    index_type=IndexType.HASH
                )
            )
            
            print(f"✅ Vector index '{idx_name}' created", flush=True)
            self._index_created = True
        except Exception as e:
            # Index might have been created by another process
            if "already exists" not in str(e).lower():
                print(f"⚠️ Error creating index: {e}", flush=True)
                raise
            else:
                self._index_created = True

    async def store_scene_embeddings(
        self, 
        video_no: str, 
        embeddings: List[Dict]
    ):
        """
        Store scene embeddings in Redis.
        
        Args:
            video_no: Video identifier
            embeddings: List of embedding dicts with keys:
                - start_time: float
                - end_time: float
                - embedding: np.ndarray
                - metadata: dict
        """
        # Ensure index exists
        if not self._index_created:
            await self.create_index()
        
        print(f"💾 Storing {len(embeddings)} embeddings for video {video_no}", flush=True)
        
        for idx, emb in enumerate(embeddings):
            key = f"video_embedding:{video_no}:scene:{idx}"
            
            # Convert embedding to bytes
            embedding_bytes = emb["embedding"].astype(np.float32).tobytes()
            
            # Store as Redis hash
            self.redis_client.hset(
                key,
                mapping={
                    "embedding": embedding_bytes,
                    "video_no": video_no,
                    "start_time": emb["start_time"],
                    "end_time": emb["end_time"],
                    "metadata": json.dumps(emb["metadata"])
                }
            )
        
        print(f"✅ Stored embeddings for video {video_no}", flush=True)

    async def get_video_embeddings(self, video_no: str) -> List[Dict]:
        """
        Retrieve all embeddings for a video.
        
        Args:
            video_no: Video identifier
            
        Returns:
            List of embedding dicts
        """
        # Scan for all keys for this video
        pattern = f"video_embedding:{video_no}:scene:*"
        keys = []
        
        cursor = 0
        while True:
            cursor, partial_keys = self.redis_client.scan(cursor, match=pattern, count=100)
            keys.extend(partial_keys)
            if cursor == 0:
                break
        
        if not keys:
            return []
        
        # Sort keys by scene index
        keys.sort(key=lambda k: int(k.split(":")[-1]))
        
        embeddings = []
        for key in keys:
            data = self.redis_client.hgetall(key)
            
            if not data:
                continue
            
            # Convert embedding bytes back to numpy array
            embedding_bytes = data.get(b"embedding")
            if embedding_bytes:
                embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            else:
                continue
            
            embeddings.append({
                "video_no": data.get(b"video_no", b"").decode("utf-8"),
                "start_time": float(data.get(b"start_time", b"0")),
                "end_time": float(data.get(b"end_time", b"0")),
                "embedding": embedding,
                "metadata": json.loads(data.get(b"metadata", b"{}").decode("utf-8"))
            })
        
        return embeddings

    async def search_similar(
        self, 
        query_embedding: np.ndarray,
        video_no: str,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Perform KNN vector search for similar clips.
        
        Args:
            query_embedding: Query embedding vector
            video_no: Filter results by video identifier
            top_k: Number of results to return
            
        Returns:
            List of similar clips with similarity scores
        """
        # Ensure index exists
        if not self._index_created:
            await self.create_index()
        
        # If RediSearch not available, use fallback immediately
        if not REDIS_SEARCH_AVAILABLE:
            return await self._fallback_search(query_embedding, video_no, top_k)
        
        try:
            # Prepare query vector (convert to bytes)
            query_vector = query_embedding.astype(np.float32).tobytes()
            
            # Build query: filter by video_no and search by vector
            # Note: Vector search syntax may vary by RediSearch version
            query = Query(f"@video_no:{video_no}").return_fields(
                "video_no", "start_time", "end_time", "metadata"
            ).dialect(2)
            
            # Perform vector search
            results = self.redis_client.ft(self.index_name).search(
                query,
                query_params={"query_vector": query_vector}
            )
            
            # Convert results
            similar_clips = []
            for doc in results.docs[:top_k]:
                # Extract similarity score (distance converted to similarity)
                # Redis returns distance, we convert to similarity: sim = 1 - distance
                distance = getattr(doc, "distance", 1.0)
                similarity = max(0.0, 1.0 - float(distance))
                
                similar_clips.append({
                    "video_no": doc.video_no,
                    "start_time": float(doc.start_time),
                    "end_time": float(doc.end_time),
                    "metadata": json.loads(doc.metadata),
                    "similarity_score": similarity
                })
            
            return similar_clips
            
        except Exception as e:
            print(f"⚠️ Vector search error: {e}", flush=True)
            # Fallback to cosine similarity on retrieved embeddings
            return await self._fallback_search(query_embedding, video_no, top_k)

    async def _fallback_search(
        self,
        query_embedding: np.ndarray,
        video_no: str,
        top_k: int
    ) -> List[Dict]:
        """
        Fallback search using cosine similarity when RediSearch is unavailable.
        
        Args:
            query_embedding: Query embedding vector
            video_no: Filter results by video identifier
            top_k: Number of results to return
            
        Returns:
            List of similar clips with similarity scores
        """
        # Get all embeddings for this video
        all_embeddings = await self.get_video_embeddings(video_no)
        
        if not all_embeddings:
            return []
        
        # Compute cosine similarities manually (avoid sklearn dependency for now)
        # Cosine similarity = dot product of normalized vectors
        def cosine_sim(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        
        similarities = []
        
        for emb in all_embeddings:
            sim = cosine_sim(query_embedding, emb["embedding"])
            
            similarities.append({
                **emb,
                "similarity_score": float(sim)
            })
        
        # Sort by similarity and return top_k
        similarities.sort(key=lambda x: x["similarity_score"], reverse=True)
        return similarities[:top_k]

    async def search_similar_with_constraints(
        self,
        query_embedding: np.ndarray,
        video_no: str,
        top_k: int = 10,
        time_window: tuple = None,
        exclude_ranges: list = None,
        max_overlap_ratio: float = 0.5
    ) -> List[Dict]:
        """
        Vector search with temporal constraints to enforce diversity.
        
        Args:
            query_embedding: Query embedding vector
            video_no: Filter results by video identifier
            top_k: Number of results to return
            time_window: Optional (start, end) tuple to constrain search to temporal region
            exclude_ranges: List of (start, end) tuples representing already-used segments
            max_overlap_ratio: Maximum allowed overlap with excluded ranges (0.0-1.0)
            
        Returns:
            List of similar clips that pass the constraints
        """
        # Get all embeddings for this video
        all_embeddings = await self.get_video_embeddings(video_no)
        
        if not all_embeddings:
            return []
        
        # Cosine similarity helper
        def cosine_sim(a, b):
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return np.dot(a, b) / (norm_a * norm_b)
        
        # Calculate overlap ratio between two time ranges
        def calculate_overlap_ratio(range1_start, range1_end, range2_start, range2_end):
            overlap = max(0, min(range1_end, range2_end) - max(range1_start, range2_start))
            range1_duration = range1_end - range1_start
            if range1_duration <= 0:
                return 0.0
            return overlap / range1_duration
        
        candidates = []
        exclude_ranges = exclude_ranges or []
        
        for emb in all_embeddings:
            start_time = emb["start_time"]
            end_time = emb["end_time"]
            
            # Filter by time window if specified
            if time_window:
                window_start, window_end = time_window
                if start_time < window_start or start_time > window_end:
                    continue
            
            # Check overlap with excluded ranges
            is_excluded = False
            max_found_overlap = 0.0
            
            for ex_start, ex_end in exclude_ranges:
                overlap_ratio = calculate_overlap_ratio(start_time, end_time, ex_start, ex_end)
                max_found_overlap = max(max_found_overlap, overlap_ratio)
                
                if overlap_ratio > max_overlap_ratio:
                    is_excluded = True
                    break
            
            if is_excluded:
                continue
            
            # Calculate similarity
            sim = cosine_sim(query_embedding, emb["embedding"])
            
            candidates.append({
                **emb,
                "similarity_score": float(sim),
                "overlap_with_used": max_found_overlap
            })
        
        # Sort by similarity and return top_k
        candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
        return candidates[:top_k]

