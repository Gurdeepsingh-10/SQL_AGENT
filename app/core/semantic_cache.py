import hashlib
import time
from typing import Dict, List, Optional

try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError:
    pass

class SemanticQueryCache:
    """Fast semantic caching for similar queries."""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.embedding_model = SentenceTransformer(model_name)
        self.index = faiss.IndexFlatL2(384)  # L2 distance for similarity
        self.query_cache = {}  # {query_hash -> (query, sql, results, timestamp)}
        self.embeddings = []
    
    def is_similar(self, new_query: str, threshold: float = 0.95) -> Optional[Dict]:
        """Check if query is semantically similar to cached query."""
        new_embedding = self.embedding_model.encode(new_query)
        
        if len(self.embeddings) == 0:
            return None
        
        distances, indices = self.index.search(
            np.array([new_embedding], dtype=np.float32), 
            k=1
        )
        
        distance = distances[0][0]
        similarity = 1 / (1 + distance)  # Convert L2 distance to similarity
        
        if similarity >= threshold:
            cached_query = list(self.query_cache.values())[indices[0][0]]
            return {
                "sql": cached_query[1],
                "results": cached_query[2],
                "similarity": similarity
            }
        return None
    
    def cache(self, query: str, sql: str, results: List) -> None:
        """Cache a successful query."""
        embedding = self.embedding_model.encode(query)
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        
        # Add to FAISS index
        self.index.add(np.array([embedding], dtype=np.float32))
        self.embeddings.append(embedding)
        
        # Cache metadata
        self.query_cache[query_hash] = (query, sql, results, time.time())
        
        # Keep only last 1000 cached queries (memory limit)
        if len(self.query_cache) > 1000:
            oldest = min(self.query_cache.items(), key=lambda x: x[1][3])
            del self.query_cache[oldest[0]]
            self.index = faiss.IndexFlatL2(384)  # Rebuild index
            for e in self.embeddings:
                self.index.add(np.array([e], dtype=np.float32))
