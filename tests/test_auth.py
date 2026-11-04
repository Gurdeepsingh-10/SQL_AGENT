"""
Tests for authentication endpoints.
"""
import pytest


class TestAuthentication:
    """Test suite for authentication endpoints."""

    def test_register_user(self, client):
        """Test user registration."""
        response = client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "testpassword123"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert "id" in data
        assert "hashed_password" not in data  # Should not expose password

    def test_register_duplicate_email(self, client):
        """Test registration with duplicate email."""
        # First registration
        client.post(
            "/auth/register",
            json={
                "email": "duplicate@example.com",
                "username": "user1",
                "password": "password123"
            }
        )

        # Duplicate registration
        response = client.post(
            "/auth/register",
            json={
                "email": "duplicate@example.com",
                "username": "user2",
                "password": "password123"
            }
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_login_success(self, client):
        """Test successful login."""
        # Register user
        client.post(
            "/auth/register",
            json={
                "email": "login@example.com",
                "username": "loginuser",
                "password": "password123"
            }
        )

        # Login
        response = client.post(
            "/auth/login",
            json={
                "email": "login@example.com",
                "password": "password123"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        """Test login with wrong password."""
        # Register user
        client.post(
            "/auth/register",
            json={
                "email": "wrongpass@example.com",
                "username": "wrongpassuser",
                "password": "correctpassword"
            }
        )

        # Login with wrong password
        response = client.post(
            "/auth/login",
            json={
                "email": "wrongpass@example.com",
                "password": "wrongpassword"
            }
        )

        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        """Test login with non-existent user."""
        response = client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123"
            }
        )

        assert response.status_code == 401

    def test_get_current_user(self, client):
        """Test getting current user info with valid token."""
        # Register and login
        client.post(
            "/auth/register",
            json={
                "email": "currentuser@example.com",
                "username": "currentuser",
                "password": "password123"
            }
        )

        login_response = client.post(
            "/auth/login",
            json={
                "email": "currentuser@example.com",
                "password": "password123"
            }
        )

        token = login_response.json()["access_token"]

        # Get current user
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "currentuser@example.com"
        assert data["username"] == "currentuser"

    def test_get_current_user_invalid_token(self, client):
        """Test getting current user with invalid token."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == 401