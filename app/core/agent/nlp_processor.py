from groq import Groq
from typing import Dict, Any, List
from app.config import settings
from app.utils.logger import get_logger
import json

logger = get_logger(__name__)


class NLPProcessor:
    """
    Processes natural language queries to extract intent and entities.
    Uses Groq (Llama 3 / Mixtral) for understanding.
    """
    
    # Intent types
    INTENT_QUERY = "QUERY"
    INTENT_INSERT = "INSERT"
    INTENT_UPDATE = "UPDATE"
    INTENT_DELETE = "DELETE"
    INTENT_DDL = "DDL"  # CREATE, DROP, ALTER tables
    INTENT_SCHEMA_INFO = "SCHEMA_INFO"
    INTENT_UNKNOWN = "UNKNOWN"
    
    def __init__(self):
        """Initialize NLP processor with Groq client."""
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL
        
    def classify_intent(self, query: str, schema_context: str = "") -> Dict[str, Any]:
        """
        Classify the intent of a natural language query.
        
        Args:
            query: Natural language query from user
            schema_context: Optional database schema context
            
        Returns:
            Dictionary containing intent, confidence, and extracted entities
        """
        try:
            prompt = self._build_intent_classification_prompt(query, schema_context)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a database expert. You must classify natural language queries into intents (QUERY, DDL, etc.). Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            logger.info(f"Classified intent: {result.get('intent')} with confidence {result.get('confidence')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error classifying intent: {str(e)}")
            return {
                "intent": self.INTENT_UNKNOWN,
                "confidence": 0.0,
                "entities": {},
                "error": str(e)
            }
    
    def _build_intent_classification_prompt(self, query: str, schema_context: str) -> str:
        """
        Build prompt for intent classification.
        
        Args:
            query: User's natural language query
            schema_context: Database schema information
            
        Returns:
            Formatted prompt string
        """
        prompt = f"""Analyze the following natural language database query and classify its intent.

Query: "{query}"

Database Schema:
{schema_context if schema_context else "No tables found (Database is empty). You can create new tables."}

Classify the query into one of these intents:
- QUERY: Retrieving/reading data (SELECT)
- INSERT: Adding new data (INSERT INTO)
- UPDATE: Modifying existing data (UPDATE)
- DELETE: Removing data (DELETE FROM)
- DDL: Creating, modifying, or dropping database structures (CREATE TABLE, DROP TABLE, ALTER TABLE, CREATE INDEX, etc.)
- SCHEMA_INFO: Asking about database structure (what tables exist, describe table, etc.)
- UNKNOWN: Cannot determine intent

Also extract key entities:
- tables: List of table names mentioned or implied
- columns: List of column names mentioned or implied
- conditions: Any filtering conditions
- aggregations: Any aggregation operations (count, sum, avg, etc.)
- time_range: Any time-based filters

Return your analysis as a JSON object with this structure:
{{
    "intent": "INTENT_TYPE",
    "confidence": 0.95,
    "entities": {{
        "tables": ["table1", "table2"],
        "columns": ["col1", "col2"],
        "conditions": ["condition description"],
        "aggregations": ["aggregation type"],
        "time_range": "time range description"
    }},
    "reasoning": "Brief explanation of classification"
}}

Examples:
Query: "Show all students" -> Intent: QUERY
Query: "Create a table named students with name and age" -> Intent: DDL
Query: "Drop the temporary table" -> Intent: DDL
Query: "Add a column for email to users table" -> Intent: DDL
Query: "Insert a new user called John" -> Intent: INSERT
Query: "What tables are in the database?" -> Intent: SCHEMA_INFO

Return ONLY the JSON object, no additional text."""
        
        return prompt
    
    def extract_entities(self, query: str, intent: str, schema_context: str = "") -> Dict[str, Any]:
        """
        Extract detailed entities from the query based on intent.
        
        Args:
            query: Natural language query
            intent: Classified intent
            schema_context: Database schema context
            
        Returns:
            Dictionary of extracted entities
        """
        try:
            prompt = f"""Extract detailed information from this database query.

Query: "{query}"
Intent: {intent}

Database Schema:
{schema_context if schema_context else "No schema information available"}

Extract the following information as applicable:
- Target tables
- Columns to select/update/insert
- Filter conditions
- Sort order
- Limit/offset
- Join conditions
- Values to insert/update

Return as JSON object with relevant fields.
Return ONLY the JSON object."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert at extracting structured information from natural language. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            entities = json.loads(result_text)
            
            logger.info(f"Extracted entities: {list(entities.keys())}")
            
            return entities
            
        except Exception as e:
            logger.error(f"Error extracting entities: {str(e)}")
            return {}
    
    def validate_query_safety(self, query: str) -> Dict[str, Any]:
        """
        Check if a query contains potentially dangerous operations.
        
        Args:
            query: Natural language query
            
        Returns:
            Dictionary with safety assessment
        """
        dangerous_keywords = [
            'drop', 'truncate', 'alter table', 'create table',
            'grant', 'revoke', 'exec', 'execute', 'shutdown'
        ]
        
        query_lower = query.lower()
        
        found_dangerous = []
        for keyword in dangerous_keywords:
            if keyword in query_lower:
                found_dangerous.append(keyword)
        
        is_safe = len(found_dangerous) == 0
        
        return {
            "is_safe": is_safe,
            "dangerous_keywords": found_dangerous,
            "message": "Query appears safe" if is_safe else f"Query contains dangerous operations: {', '.join(found_dangerous)}"
        }
