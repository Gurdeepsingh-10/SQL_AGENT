# AI-Powered SQL Agent Backend

A production-ready FastAPI backend that enables non-technical users to interact with SQL databases using natural language. The system uses LLM-powered agents to understand user intent, generate safe SQL queries, and return human-friendly responses.

## 🌟 Features

- **Natural Language Processing**: Convert plain English to SQL queries
- **Intent Classification**: Automatically determine query type (SELECT, INSERT, UPDATE, etc.)
- **Schema-Aware Generation**: Uses database schema context for accurate SQL generation
- **Security First**: Multiple validation layers prevent SQL injection and dangerous operations
- **JWT Authentication**: Secure user authentication with JWT tokens
- **Query History**: Track all user queries and execution results
- **Database Introspection**: Explore database schema through API
- **Comprehensive Logging**: Audit trail for all operations
- **OpenAPI Documentation**: Interactive API docs with Swagger UI

## 🏗️ Architecture

```
# AI SQL Agent Backend

A powerful, secure, and intelligent backend for an AI-powered SQL agent. This system allows users to query their own Supabase PostgreSQL databases using natural language, featuring a robust multi-database architecture.

## 🚀 Key Features

- **Multi-Database Support**: Users can add and manage multiple target Database connections.
- **Dynamic Connection Management**: Agent dynamically switches between databases per query.
- **Secure Architecture**:
    - Primary Database: Handles auth, users, and query history.
    - Target Databases: User-provided databases for analysis.
    - **Encryption**: Connection strings are encrypted at rest (Fernet/AES).
- **Advanced NLP to SQL**:
    - Uses **Groq (Llama 3)** for high-speed inference.
    - Supports complex, multi-statement queries (e.g., "Create table X; Insert data Y").
    - Handles DDL operations (CREATE, DROP, ALTER) when enabled.
- **Robust Security**:
    - JWT Authentication & GitHub OAuth.
    - Configurable safety levels (ReadOnly vs. Unrestricted).
    - SQL Injection protection (when validation is active).

## �️ Tech Stack

- **Framework**: FastAPI (Python 3.12+)
- **Database**: PostgreSQL (Supabase) via SQLAlchemy
- **LLM Engine**: Groq API (Llama 3 70B)
- **Security**: PyJWT, Fernet Encryption, Passlib
- **Validation**: SQLParse, Regex-based safety checks

## � Installation & Setup

1.  **Clone the repository**
    ```bash
    git clone <repo-url>
    cd sql_agent_backend
    ```

2.  **Create Virtual Environment**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Environment Configuration**
    Create a `.env` file based on `.env.example`:
    ```ini
    DATABASE_URL="postgresql://user:pass@host:5432/dbname" # Primary System DB
    GROQ_API_KEY="gsk_..."
    GROQ_MODEL="llama-3.3-70b-versatile"
    CONNECTION_ENCRYPTION_KEY="<generated-key>"
    
    # Operation Modes
    ENABLE_DDL_OPERATIONS=True
    ENABLE_WRITE_OPERATIONS=True
    ENABLE_DELETE_OPERATIONS=True
    ```

5.  **Run Migrations** (if using Alembic)
    ```bash
    alembic upgrade head
    ```

6.  **Start the Server**
    ```bash
    uvicorn app.main:app --reload
    ```

## 📖 API Usage Guide

### 1. Authentication
- **Register**: `POST /auth/register`
- **Login**: `POST /auth/login` (Get JWT Token)

### 2. Manage Database Connections
- **Add Target DB**: `POST /connections/add`
    ```json
    {
      "connection_name": "My Sales DB",
      "connection_url": "postgresql://user:pass@host:5432/sales_db",
      "is_default": true
    }
    ```
- **List Connections**: `GET /connections/list`
- **Test Connection**: `POST /connections/test`

### 3. AI Query Agent
- **Execute Query**: `POST /agent/query`
    ```json
    {
      "connection_id": 1,  // Optional: ID of target DB to query
      "query": "Create a table named reports with id and title columns; Insert a sample report."
    }
    ```

## 🛡️ Security Note
The system is currently configured in **Unrestricted Mode** for testing/development flexibility:
- DDL statements (CREATE, DROP) are allowed.
- Multiple SQL statements per request are allowed.
- Validation checks are permissive.

**For Production:** Set `ENABLE_DDL_OPERATIONS=False` in `.env` and re-enable validation logic in `validator.py`.

## 🤝 Contributing
Contributions are welcome! Please fork the repo and submit a PR.
GROQ_API_KEY=your-groq-api-key-here
GROQ_MODEL=llama3-70b-8192

# SQL Agent Settings
ENABLE_WRITE_OPERATIONS=True
ENABLE_DELETE_OPERATIONS=False
ENABLE_DDL_OPERATIONS=False
```

### 3. Initialize Database (Optional)

Load example schema:

```bash
sqlite3 sql_agent.db < examples/example_schema.sql
```

### 4. Run the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### 5. Access Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 📚 API Usage

### Authentication

#### Register a User

```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "johndoe",
    "password": "securepassword123"
  }'
```

#### Login

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "securepassword123"
  }'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### SQL Agent Queries

#### Process Natural Language Query

```bash
curl -X POST "http://localhost:8000/agent/query" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me all users created in the last 7 days"
  }'
```

Response:
```json
{
  "success": true,
  "intent": "QUERY",
  "generated_sql": "SELECT * FROM users WHERE created_at >= DATE('now', '-7 days');",
  "results": [...],
  "result_count": 5,
  "execution_time": 0.123,
  "message": "Query returned 5 row(s)"
}
```

#### Get Query History

```bash
curl -X GET "http://localhost:8000/agent/history?limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Database Introspection

#### List All Tables

```bash
curl -X GET "http://localhost:8000/db/tables" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### Get Table Schema

```bash
curl -X GET "http://localhost:8000/db/schema/users" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🧪 Testing

Run tests:

```bash
# All tests
pytest

# With coverage
pytest --cov=app tests/

# Specific test file
pytest tests/test_auth.py -v
```

## 🔒 Security Features

### Multi-Layer Validation

1. **Keyword Blacklist**: Blocks dangerous SQL operations (DROP, TRUNCATE, etc.)
2. **Operation Permissions**: Configurable permissions for write/delete/DDL operations
3. **SQL Injection Detection**: Pattern-based injection attempt detection
4. **Syntax Validation**: Ensures valid SQL syntax
5. **Schema Validation**: Verifies tables and columns exist
6. **Complexity Limits**: Prevents resource-intensive queries

### Default Security Settings

- ✅ SELECT queries: **Enabled**
- ✅ INSERT/UPDATE: **Enabled** (configurable)
- ❌ DELETE: **Disabled** (configurable)
- ❌ DDL operations: **Disabled** (configurable)

## 📁 Project Structure

```
sql_agent_backend/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration
│   ├── database.py             # Database setup
│   ├── models/                 # SQLAlchemy models
│   │   ├── user.py
│   │   └── query_history.py
│   ├── schemas/                # Pydantic schemas
│   │   ├── auth.py
│   │   ├── agent.py
│   │   └── database.py
│   ├── core/                   # Business logic
│   │   ├── security.py
│   │   ├── middleware.py
│   │   └── agent/
│   │       ├── nlp_processor.py
│   │       ├── sql_generator.py
│   │       ├── validator.py
│   │       ├── executor.py
│   │       └── schema_inspector.py
│   ├── api/                    # API routes
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── agent.py
│   │       └── database.py
│   └── utils/
│       └── logger.py
├── tests/                      # Test suite
├── examples/                   # Example queries and schema
├── requirements.txt
├── .env.example
└── README.md
```

## 🎯 Example Queries

See [examples/sample_queries.md](examples/sample_queries.md) for comprehensive examples.

**Simple Queries:**
- "Show me all users"
- "How many products do we have?"
- "Find products priced under $100"

**Complex Queries:**
- "Show me total sales for each user"
- "What's the average order value by category?"
- "Find users who haven't placed orders in the last 30 days"

**Write Operations:**
- "Add a new product called 'Laptop' priced at $999"
- "Update the status of order 123 to 'shipped'"

## 🛠️ Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///./sql_agent.db` |
| `SECRET_KEY` | JWT secret key | Required |
| `GROQ_API_KEY` | Groq API key | Required |
| `GROQ_MODEL` | Model to use | `llama3-70b-8192` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT token expiry | `30` |
| `MAX_QUERY_COMPLEXITY` | Maximum query complexity score | `100` |
| `QUERY_TIMEOUT_SECONDS` | Query execution timeout | `30` |
| `ENABLE_WRITE_OPERATIONS` | Allow INSERT/UPDATE | `True` |
| `ENABLE_DELETE_OPERATIONS` | Allow DELETE | `False` |
| `ENABLE_DDL_OPERATIONS` | Allow DDL (CREATE/DROP/ALTER) | `False` |

## 📊 Monitoring and Logging

Logs are written to:
- Console output (stdout)
- `logs/sql_agent.log` file

Log levels:
- INFO: Normal operations
- WARNING: Potential issues
- ERROR: Execution failures

## 🚧 Production Deployment

### Security Checklist

- [ ] Change `SECRET_KEY` to a strong random value
- [ ] Use PostgreSQL instead of SQLite
- [ ] Enable HTTPS/TLS
- [ ] Set `DEBUG=False`
- [ ] Configure proper CORS origins
- [ ] Set up rate limiting
- [ ] Enable query result size limits
- [ ] Configure database connection pooling
- [ ] Set up monitoring and alerting
- [ ] Regular security audits

### Recommended Setup

```bash
# Use production WSGI server
pip install gunicorn

# Run with gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License.

## 🆘 Troubleshooting

### Groq API Errors

**Issue**: "Groq API key not found"
**Solution**: Set `GROQ_API_KEY` in `.env` file

### Database Connection Errors

**Issue**: "Could not connect to database"
**Solution**: Verify `DATABASE_URL` is correct and database is accessible

### Authentication Errors

**Issue**: "Invalid authentication credentials"
**Solution**: Ensure JWT token is included in Authorization header: `Bearer YOUR_TOKEN`

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Check [examples/sample_queries.md](examples/sample_queries.md) for usage examples
- Review API documentation at `/docs`

## 🎓 Learn More

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [OpenAI API Documentation](https://platform.openai.com/docs/)

---

