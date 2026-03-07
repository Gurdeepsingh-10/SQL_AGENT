import hashlib
import time
from typing import Optional
import pickle

class GroqResponseCache:
    """HTTP-level cache for Groq API responses."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get_cache_key(self, prompt: str, model: str, temp: float) -> str:
        """Generate deterministic cache key."""
        key_str = f"{model}|{temp}|{prompt}"
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get(self, prompt: str, model: str, temp: float) -> Optional[str]:
        """Retrieve cached response."""
        key = self.get_cache_key(prompt, model, temp)
        if key in self.cache:
            response, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return response
            del self.cache[key]
        return None
    
    def set(self, prompt: str, model: str, temp: float, response: str) -> None:
        """Cache a response."""
        key = self.get_cache_key(prompt, model, temp)
        self.cache[key] = (response, time.time())

groq_cache = GroqResponseCache()
