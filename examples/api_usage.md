# API Usage Examples

This document provides practical examples of using the SQL Agent API.

## Setup

First, set your base URL and get an authentication token:

```bash
export API_URL="http://localhost:8000"
export TOKEN="your-jwt-token-here"
```

## Authentication Examples

### 1. Register a New User

```bash
curl -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "username": "alice",
    "password": "SecurePass123!"
  }'
```

**Response:**
```json
{
  "id": 1,
  "email": "alice@example.com",
  "username": "alice",
  "is_active": true,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### 2. Login

```bash
curl -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "SecurePass123!"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Save this token for subsequent requests!

### 3. Get Current User Info

```bash
curl -X GET "$API_URL/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

## SQL Agent Examples

### 4. Simple Query

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me all users"
  }'
```

**Response:**
```json
{
  "success": true,
  "intent": "QUERY",
  "generated_sql": "SELECT * FROM users;",
  "results": [
    {
      "id": 1,
      "email": "john@example.com",
      "username": "john_doe",
      "full_name": "John Doe",
      "created_at": "2024-01-10T08:00:00Z"
    }
  ],
  "result_count": 1,
  "execution_time": 0.045,
  "message": "Query returned 1 row(s)"
}
```

### 5. Aggregation Query

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How many products are in the Electronics category?"
  }'
```

### 6. Filtered Query

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me products priced between $100 and $500"
  }'
```

### 7. Join Query

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me all orders with customer information"
  }'
```

### 8. Time-Based Query

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me users created in the last 7 days"
  }'
```

### 9. Insert Operation

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Add a new product called Wireless Keyboard priced at $49.99 in the Electronics category"
  }'
```

### 10. Update Operation

```bash
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Update the price of product with id 5 to $39.99"
  }'
```

## Query History Examples

### 11. Get Recent Query History

```bash
curl -X GET "$API_URL/agent/history?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

### 12. Get Only Successful Queries

```bash
curl -X GET "$API_URL/agent/history?limit=10&success_only=true" \
  -H "Authorization: Bearer $TOKEN"
```

### 13. Paginated History

```bash
curl -X GET "$API_URL/agent/history?limit=20&offset=20" \
  -H "Authorization: Bearer $TOKEN"
```

## Database Introspection Examples

### 14. List All Tables

```bash
curl -X GET "$API_URL/db/tables" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "tables": ["users", "products", "orders", "order_items"],
  "total": 4
}
```

### 15. Get Table Schema

```bash
curl -X GET "$API_URL/db/schema/products" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "table": {
    "table_name": "products",
    "columns": [
      {
        "name": "id",
        "type": "INTEGER",
        "nullable": false,
        "primary_key": true,
        "foreign_key": null
      },
      {
        "name": "name",
        "type": "VARCHAR(255)",
        "nullable": false,
        "primary_key": false,
        "foreign_key": null
      },
      {
        "name": "price",
        "type": "DECIMAL(10,2)",
        "nullable": false,
        "primary_key": false,
        "foreign_key": null
      }
    ],
    "row_count": 25
  }
}
```

### 16. Refresh Schema Cache

```bash
curl -X POST "$API_URL/db/schema/refresh" \
  -H "Authorization: Bearer $TOKEN"
```

## Python Client Example

```python
import requests

class SQLAgentClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.token = None
    
    def register(self, email, username, password):
        response = requests.post(
            f"{self.base_url}/auth/register",
            json={"email": email, "username": username, "password": password}
        )
        return response.json()
    
    def login(self, email, password):
        response = requests.post(
            f"{self.base_url}/auth/login",
            json={"email": email, "password": password}
        )
        data = response.json()
        self.token = data.get("access_token")
        return data
    
    def query(self, natural_language_query):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.post(
            f"{self.base_url}/agent/query",
            json={"query": natural_language_query},
            headers=headers
        )
        return response.json()
    
    def get_history(self, limit=10):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"{self.base_url}/agent/history?limit={limit}",
            headers=headers
        )
        return response.json()
    
    def get_tables(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"{self.base_url}/db/tables",
            headers=headers
        )
        return response.json()

# Usage
client = SQLAgentClient()

# Register and login
client.register("user@example.com", "myuser", "password123")
client.login("user@example.com", "password123")

# Query database
result = client.query("Show me all products under $100")
print(result)

# Get history
history = client.get_history()
print(history)
```

## JavaScript/Node.js Example

```javascript
const axios = require('axios');

class SQLAgentClient {
  constructor(baseURL = 'http://localhost:8000') {
    this.baseURL = baseURL;
    this.token = null;
  }

  async register(email, username, password) {
    const response = await axios.post(`${this.baseURL}/auth/register`, {
      email,
      username,
      password
    });
    return response.data;
  }

  async login(email, password) {
    const response = await axios.post(`${this.baseURL}/auth/login`, {
      email,
      password
    });
    this.token = response.data.access_token;
    return response.data;
  }

  async query(naturalLanguageQuery) {
    const response = await axios.post(
      `${this.baseURL}/agent/query`,
      { query: naturalLanguageQuery },
      { headers: { Authorization: `Bearer ${this.token}` } }
    );
    return response.data;
  }

  async getHistory(limit = 10) {
    const response = await axios.get(
      `${this.baseURL}/agent/history?limit=${limit}`,
      { headers: { Authorization: `Bearer ${this.token}` } }
    );
    return response.data;
  }
}

// Usage
(async () => {
  const client = new SQLAgentClient();
  
  await client.register('user@example.com', 'myuser', 'password123');
  await client.login('user@example.com', 'password123');
  
  const result = await client.query('Show me all products under $100');
  console.log(result);
})();
```

## Error Handling Examples

### Handling Authentication Errors

```bash
# Invalid credentials
curl -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "wrong@example.com",
    "password": "wrongpassword"
  }'
```

**Response (401):**
```json
{
  "detail": "Incorrect email or password"
}
```

### Handling Validation Errors

```bash
# Dangerous query attempt
curl -X POST "$API_URL/agent/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "DROP TABLE users"
  }'
```

**Response (200 but failed):**
```json
{
  "success": false,
  "intent": "DELETE",
  "generated_sql": "DROP TABLE users;",
  "message": "The generated query failed security validation.",
  "error": "Dangerous operations detected: DROP"
}
```

## Best Practices

1. **Always use HTTPS in production**
2. **Store tokens securely** (not in code)
3. **Implement token refresh logic**
4. **Handle errors gracefully**
5. **Validate responses before using data**
6. **Use environment variables for configuration**
7. **Implement rate limiting on client side**
8. **Log all API interactions for debugging**
