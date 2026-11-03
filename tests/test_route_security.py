from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user

client = TestClient(app)

PUBLIC = {
    ("GET", "/"),
    ("GET", "/health"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("GET", "/auth/github/login"),
    ("GET", "/auth/github/callback"),
}


def _depends_on(dependant, target):
    """Return True if any dependant in dependant.dependencies (searched recursively) has .call is target."""
    if not dependant:
        return False
    for sub in getattr(dependant, "dependencies", []):
        if getattr(sub, "call", None) is target:
            return True
        if _depends_on(sub, target):
            return True
    return False


def test_every_api_route_requires_auth_or_is_allowlisted():
    non_public_count = 0
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                if (method, route.path) in PUBLIC:
                    continue
                non_public_count += 1
                assert _depends_on(route.dependant, get_current_user), (
                    f"unauthenticated route: {method} {route.path}"
                )
    assert non_public_count >= 10, f"Expected at least 10 non-public routes, but only checked {non_public_count}"


def test_public_allowlist_has_no_stale_entries():
    existing_routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if method not in {"HEAD", "OPTIONS"}:
                    existing_routes.add((method, route.path))

    for entry in PUBLIC:
        assert entry in existing_routes, f"Stale entry in PUBLIC allowlist: {entry}"


def test_removed_routes_return_404():
    removed_routes = [
        ("POST", "/agent/query-stream"),
        ("GET", "/db/tables"),
        ("GET", "/db/schema/anything"),
        ("POST", "/db/schema/refresh"),
    ]
    for method, path in removed_routes:
        response = client.request(method, path)
        assert response.status_code == 404, (
            f"Expected 404 for removed route {method} {path}, got {response.status_code}"
        )

