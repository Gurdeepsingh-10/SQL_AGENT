from typing import List, Dict
import json
from groq import Groq
import os

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class BatchNLPProcessor:
    """Process multiple sub-queries in parallel."""
    
    def classify_multi_intent(self, query: str) -> List[Dict]:
        """Detect and classify multiple intents in one query."""
        decompose_prompt = f"""
        Analyze this query and split it into independent sub-tasks if needed:
        
        "{query}"
        
        Return a JSON array of sub-tasks:
        [
            {{"intent": "QUERY", "query": "...", "depends_on": []}},
            {{"intent": "QUERY", "query": "...", "depends_on": [0]}}
        ]
        
        Only split if truly independent. Otherwise return single task.
        """
        
        response = groq_client.chat.completions.create(
            model="llama-3-70b-instruct",
            messages=[{"role": "user", "content": decompose_prompt}],
            temperature=0.0,
            max_tokens=200
        )
        
        return json.loads(response.choices[0].message.content)
