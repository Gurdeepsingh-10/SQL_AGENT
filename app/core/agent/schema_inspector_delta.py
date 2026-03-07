import os
import json
import hashlib
from typing import Dict, List
from sqlalchemy import inspect

class DeltaSchemaInspector:
    """Incremental schema caching with change detection."""
    
    def __init__(self, engine, cache_dir: str = ".schema_cache"):
        self.engine = engine
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_table_signatures(self) -> Dict[str, str]:
        """Get hash signatures for all tables."""
        sigs = {}
        inspector = inspect(self.engine)
        
        for table in inspector.get_table_names():
            # Hash columns + indexes + constraints
            cols = inspector.get_columns(table)
            # converting to dicts to properly format with json dumps if they contains objects
            cols_serialized = [{k: str(v) for k, v in col.items()} for col in cols]
            cols_str = json.dumps(cols_serialized, sort_keys=True)
            sigs[table] = hashlib.sha256(cols_str.encode()).hexdigest()
        
        return sigs
    
    def detect_changes(self) -> List[str]:
        """Detect which tables changed since last check."""
        current = self.get_table_signatures()
        
        prev_file = os.path.join(self.cache_dir, "schema_sigs.json")
        if os.path.exists(prev_file):
            with open(prev_file) as f:
                previous = json.load(f)
            changed = [t for t in current if current.get(t) != previous.get(t)]
        else:
            changed = list(current.keys())
        
        # Save current signatures
        with open(prev_file, "w") as f:
            json.dump(current, f)
        
        return changed
