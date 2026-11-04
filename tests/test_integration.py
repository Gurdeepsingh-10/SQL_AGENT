"""
Integration tests for the complete SQL Agent pipeline.
"""


def _register_and_login(client, email="integration@example.com", username="integrationuser"):
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "password123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestIntegration:
    """Integration tests for complete workflows."""

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_complete_auth_flow(self, client):
        register_response = client.post(
            "/auth/register",
            json={
                "email": "flow@example.com",
                "username": "flowuser",
                "password": "password123",
            },
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/auth/login",
            json={"email": "flow@example.com", "password": "password123"},
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]

        me_response = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "flow@example.com"

    def test_query_history_endpoint(self, client):
        headers = _register_and_login(client)
        history_response = client.get("/agent/history", headers=headers)
        assert history_response.status_code == 200
        assert "total" in history_response.json()

    def test_query_history_requires_login(self, client):
        response = client.get("/agent/history")
        assert response.status_code in (401, 403)
