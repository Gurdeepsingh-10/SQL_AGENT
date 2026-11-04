def _register(client):
    return client.post(
        "/auth/register",
        json={"email": "iso@example.com", "username": "isouser", "password": "password123"},
    )


def test_database_is_isolated_first(client):
    assert _register(client).status_code == 201


def test_database_is_isolated_second(client):
    # Passes only if every test gets a fresh database; a shared database returns 400 here.
    assert _register(client).status_code == 201


def test_client_installs_db_override(client):
    from app.main import app
    from app.database import get_db

    assert get_db in app.dependency_overrides


def test_db_override_removed_after_test():
    # Runs after the tests above; fails if the fixture leaks its override.
    from app.main import app
    from app.database import get_db

    assert get_db not in app.dependency_overrides

