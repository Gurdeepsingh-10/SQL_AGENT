from pathlib import Path
from app.config import Settings


def _parse_env_example_names():
    """Read .env.example and return the set of NAME keys from non-comment lines."""
    env_example_path = Path(__file__).resolve().parent.parent / ".env.example"
    content = env_example_path.read_text(encoding="utf-8")
    names = set()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name:
                names.add(name)
    return names


def test_all_env_example_names_are_settings_fields():
    names = _parse_env_example_names()
    known_fields = set(Settings.model_fields.keys())
    for name in names:
        assert name in known_fields, (
            f".env.example key {name!r} is not a field of Settings"
        )


def test_required_keys_present_in_env_example():
    names = _parse_env_example_names()
    assert "SECRET_KEY" in names
    assert "CONNECTION_ENCRYPTION_KEY" in names


def test_no_langchain_names_in_env_example():
    names = _parse_env_example_names()
    for name in names:
        assert not name.startswith("LANGCHAIN_"), (
            f".env.example contains {name!r} which starts with LANGCHAIN_; use LANGSMITH_* instead"
        )

