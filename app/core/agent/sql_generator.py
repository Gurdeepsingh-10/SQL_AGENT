"""
SQL Generator - Converts natural language to SQL queries.
Uses LLM with schema context to generate accurate SQL.
"""

from groq import Groq
from typing import Dict, Any, List, Optional
from app.config import settings
from app.utils.logger import get_logger
import re

logger = get_logger(__name__)


class SQLGenerator:
    """
    Generates SQL queries from natural language using LLM (Groq).
    Provides schema context for accurate generation.
    """
    
    def __init__(self):
        """Initialize SQL generator with Groq client."""
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL
    
    def generate_sql(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str
    ) -> Dict[str, Any]:
        """
        Generate SQL query from natural language.
        
        Args:
            query: Natural language query
            intent: Classified intent (QUERY, INSERT, UPDATE, etc.)
            entities: Extracted entities from NLP processor
            schema_context: Database schema information
            
        Returns:
            Dictionary containing generated SQL and metadata
        """
        try:
            prompt = self._build_sql_generation_prompt(
                query, intent, entities, schema_context
            )
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt(intent)},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            sql = response.choices[0].message.content.strip()
            
            # Clean up the SQL (remove markdown code blocks if present)
            sql = self._clean_sql(sql)
            
            logger.info(f"Generated SQL: {sql[:100]}...")
            
            return {
                "sql": sql,
                "intent": intent,
                "confidence": 0.9,  # Could be enhanced with actual confidence scoring
                "requires_parameters": self._check_requires_parameters(sql)
            }
            
        except Exception as e:
            logger.error(f"Error generating SQL: {str(e)}")
            return {
                "sql": None,
                "intent": intent,
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _get_system_prompt(self, intent: str = "QUERY") -> str:
        """
        Get the system prompt for SQL generation.
        
        Args:
            intent: The query intent (QUERY, DDL, etc.)
        """
        base_prompt = """You are an expert SQL query generator. Your task is to convert natural language queries into accurate, safe SQL queries.

Rules:
1. Generate ONLY the SQL query, no explanations or markdown
2. Use proper SQL syntax and formatting
3. Always use parameterized queries when values are involved
4. Use appropriate JOINs when multiple tables are involved
5. Include proper WHERE clauses for filtering
6. Use aliases for better readability
7. For aggregations, use GROUP BY appropriately
8. For date/time queries, use appropriate date functions
9. Ensure queries are optimized and not overly complex"""

        if intent == "DDL" or settings.ENABLE_DDL_OPERATIONS:
            return base_prompt + "\n10. You ARE ALLOWED to generate multiple SQL statements separated by semicolons (;).\n11. You ARE ALLOWED to generate DDL statements (CREATE, DROP, ALTER) as requested.\n\nReturn ONLY the SQL query."
        else:
            return base_prompt + "\n10. You ARE ALLOWED to generate multiple SQL statements separated by semicolons (;).\n11. NEVER generate DROP, TRUNCATE, or other destructive DDL statements unless explicitly authorized.\n\nReturn ONLY the SQL query."
    
    def _build_sql_generation_prompt(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str
    ) -> str:
        """
        Build prompt for SQL generation.
        
        Args:
            query: Natural language query
            intent: Query intent
            entities: Extracted entities
            schema_context: Database schema
            
        Returns:
            Formatted prompt
        """
        prompt = f"""Convert this natural language query to SQL.

Natural Language Query: "{query}"

Intent: {intent}

Database Schema:
{schema_context}

Extracted Information:
{self._format_entities(entities)}

Generate the SQL query that fulfills this request.
Return ONLY the SQL query, nothing else."""
        
        return prompt
    
    def _format_entities(self, entities: Dict[str, Any]) -> str:
        """Format entities for prompt."""
        if not entities:
            return "No specific entities extracted"
        
        formatted = []
        for key, value in entities.items():
            if value:
                formatted.append(f"- {key}: {value}")
        
        return "\n".join(formatted) if formatted else "No specific entities extracted"
    
    def _clean_sql(self, sql: str) -> str:
        """
        Clean up generated SQL by removing markdown and extra whitespace.
        
        Args:
            sql: Raw SQL from LLM
            
        Returns:
            Cleaned SQL query
        """
        # Remove markdown code blocks
        sql = re.sub(r'```sql\s*', '', sql)
        sql = re.sub(r'```\s*', '', sql)
        
        # Remove extra whitespace
        sql = ' '.join(sql.split())
        
        # Ensure it ends with semicolon
        sql = sql.rstrip(';').strip() + ';'
        
        return sql
    
    def _check_requires_parameters(self, sql: str) -> bool:
        """
        Check if SQL query requires parameters.
        
        Args:
            sql: SQL query
            
        Returns:
            True if query has parameters
        """
        # Check for common parameter placeholders
        return bool(re.search(r'[?$:]|\bVALUES\s*\(', sql, re.IGNORECASE))
    
    def generate_multiple_candidates(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        num_candidates: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple SQL query candidates and rank them.
        
        Args:
            query: Natural language query
            intent: Query intent
            entities: Extracted entities
            schema_context: Database schema
            num_candidates: Number of candidates to generate
            
        Returns:
            List of SQL candidates with rankings
        """
        candidates = []
        
        for i in range(num_candidates):
            result = self.generate_sql(query, intent, entities, schema_context)
            if result.get('sql'):
                candidates.append({
                    'rank': i + 1,
                    'sql': result['sql'],
                    'confidence': result.get('confidence', 0.0)
                })
        
        # Sort by confidence (in a real implementation, this would be more sophisticated)
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        
        return candidates
    
    def explain_sql(self, sql: str) -> str:
        """
        Generate a human-friendly explanation of a SQL query.
        
        Args:
            sql: SQL query to explain
            
        Returns:
            Human-readable explanation
        """
        try:
            prompt = f"""Explain this SQL query in simple, non-technical language that anyone can understand.

SQL Query:
{sql}

Provide a brief, clear explanation of what this query does.
Use simple language and avoid technical jargon."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert at explaining technical concepts in simple terms."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )
            
            explanation = response.choices[0].message.content.strip()
            return explanation
            
        except Exception as e:
            logger.error(f"Error explaining SQL: {str(e)}")
            return "Unable to generate explanation"
