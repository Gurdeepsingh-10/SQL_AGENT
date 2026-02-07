"""
Integration tests for the complete SQL Agent pipeline.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_integration.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user_token():
    """Create a test user and return authentication token."""
    # Register user
    client.post(
        "/auth/register",
        json={
            "email": "integration@example.com",
            "username": "integrationuser",
            "password": "password123"
        }
    )
    
    # Login
    response = client.post(
        "/auth/login",
        json={
            "email": "integration@example.com",
            "password": "password123"
        }
    )
    
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def setup_test_data():
    """Set up test data in database."""
    # Create a test table with sample data
    with engine.connect() as conn:
        # Create products table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                category TEXT
            )
        """))
        
        # Insert sample data
        conn.execute(text("""
            INSERT INTO products (name, price, category) VALUES
            ('Laptop', 999.99, 'Electronics'),
            ('Mouse', 29.99, 'Electronics'),
            ('Desk', 299.99, 'Furniture'),
            ('Chair', 199.99, 'Furniture')
        """))
        
        conn.commit()
    
    yield
    
    # Cleanup
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS products"))
        conn.commit()


class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_health_check(self):
        """Test API health check."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_complete_auth_flow(self):
        """Test complete authentication flow."""
        # Register
        register_response = client.post(
            "/auth/register",
            json={
                "email": "flow@example.com",
                "username": "flowuser",
                "password": "password123"
            }
        )
        assert register_response.status_code == 201
        
        # Login
        login_response = client.post(
            "/auth/login",
            json={
                "email": "flow@example.com",
                "password": "password123"
            }
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        
        # Access protected endpoint
        me_response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "flow@example.com"
    
    def test_database_introspection(self, test_user_token, setup_test_data):
        """Test database introspection endpoints."""
        headers = {"Authorization": f"Bearer {test_user_token}"}
        
        # Get table list
        tables_response = client.get("/db/tables", headers=headers)
        assert tables_response.status_code == 200
        tables = tables_response.json()["tables"]
        assert "products" in tables
        
        # Get table schema
        schema_response = client.get("/db/schema/products", headers=headers)
        assert schema_response.status_code == 200
        schema = schema_response.json()["table"]
        assert schema["table_name"] == "products"
        assert len(schema["columns"]) > 0
    
    def test_schema_info_query(self, test_user_token, setup_test_data):
        """Test schema information query through agent."""
        headers = {"Authorization": f"Bearer {test_user_token}"}
        
        # Note: This test requires OpenAI API key to work
        # Skipping actual agent query test in basic integration
        # In production, you'd mock the OpenAI calls
        
        # Test query history endpoint instead
        history_response = client.get("/agent/history", headers=headers)
        assert history_response.status_code == 200
        assert "total" in history_response.json()


# Cleanup
def teardown_module(module):
    """Clean up test database after tests."""
    import os
    if os.path.exists("./test_integration.db"):
        os.remove("./test_integration.db")
