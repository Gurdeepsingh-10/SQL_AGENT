# Static guard test to ensure settings.DATABASE_URL is never logged without redaction in app/main.py
from pathlib import Path


def test_database_url_logging_is_redacted_statically():
    main_py_path = Path(__file__).resolve().parent.parent / "app" / "main.py"
    content = main_py_path.read_text(encoding="utf-8")

    # Assert that app/main.py imports redact_database_url
    assert "redact_database_url" in content
    assert "from app.utils.redact import redact_database_url" in content

    # Find every occurrence of settings.DATABASE_URL
    target = "settings.DATABASE_URL"
    occurrences = []
    idx = content.find(target)
    while idx != -1:
        occurrences.append(idx)
        idx = content.find(target, idx + len(target))

    assert len(occurrences) > 0, "Expected at least one occurrence of settings.DATABASE_URL in app/main.py"

    prefix = "redact_database_url("
    for pos in occurrences:
        preceding = content[pos - len(prefix):pos]
        assert preceding == prefix, (
            f"settings.DATABASE_URL at position {pos} is not immediately inside redact_database_url("
        )

