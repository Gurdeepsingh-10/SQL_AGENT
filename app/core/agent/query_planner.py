import hashlib
from typing import Dict, List
from sqlalchemy import text

class QueryPlanner:
    """Cache and reuse query execution plans."""
    
    def __init__(self):
        self.plan_cache = {}
    
    def analyze_plan(self, engine, sql: str) -> List[Dict]:
        """Get query execution plan (EXPLAIN output)."""
        cache_key = hashlib.sha256(sql.encode()).hexdigest()
        
        if cache_key in self.plan_cache:
            return self.plan_cache[cache_key]
        
        # Execute EXPLAIN QUERY PLAN
        with engine.connect() as conn:
            result = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"))
            plan = [dict(row._mapping) for row in result]
        
        self.plan_cache[cache_key] = plan
        return plan
    
    def is_fast_query(self, plan: List[Dict]) -> bool:
        """Estimate if query is <100ms based on plan."""
        # Check for full table scans, expensive joins, etc.
        for step in plan:
            if "SCAN" in str(step).upper():
                return False  # Likely slow
        return True
