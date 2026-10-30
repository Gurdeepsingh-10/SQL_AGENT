import secrets
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from app.config import Settings


def make_settings(**overrides) -> Settings:
    defaults = {
        "_env_file": None,
        "SECRET_KEY": secrets.token_hex(32),
        "CONNECTION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_secret_key_too_short_rejected():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(SECRET_KEY="short-sentinel-value")
    assert "short-sentinel-value" not in str(exc_info.value)


def test_secret_key_placeholder_rejected():
    val_your_secret = "your-secret-" + "x" * 28
    with pytest.raises(ValidationError):
        make_settings(SECRET_KEY=val_your_secret)

    val_change_in_prod = "change-in-production-" + "y" * 19
    with pytest.raises(ValidationError):
        make_settings(SECRET_KEY=val_change_in_prod)


def test_secret_key_valid_accepted(valid_secret_key):
    s = make_settings(SECRET_KEY=valid_secret_key)
    assert s.SECRET_KEY == valid_secret_key


def test_secret_key_missing_rejected(monkeypatch, valid_fernet_key):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CONNECTION_ENCRYPTION_KEY=valid_fernet_key)


def test_encryption_key_invalid_rejected(monkeypatch, valid_secret_key):
    with pytest.raises(ValidationError) as exc_info:
        make_settings(CONNECTION_ENCRYPTION_KEY="invalid-sentinel-key")
    assert "invalid-sentinel-key" not in str(exc_info.value)

    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SECRET_KEY=valid_secret_key)


def test_encryption_key_valid_accepted(valid_fernet_key):
    s = make_settings(CONNECTION_ENCRYPTION_KEY=valid_fernet_key)
    assert s.CONNECTION_ENCRYPTION_KEY == valid_fernet_key


def test_safe_defaults(monkeypatch):
    for name in [
        "DEBUG",
        "ENABLE_WRITE_OPERATIONS",
        "ENABLE_DELETE_OPERATIONS",
        "ENABLE_DDL_OPERATIONS",
    ]:
        monkeypatch.delenv(name, raising=False)
    s = make_settings()
    assert s.DEBUG is False
    assert s.ENABLE_WRITE_OPERATIONS is False
    assert s.ENABLE_DELETE_OPERATIONS is False
    assert s.ENABLE_DDL_OPERATIONS is False


def test_no_hardcoded_model_defaults(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_FAST_MODEL", raising=False)
    s = make_settings()
    assert s.GROQ_MODEL == ""
    assert s.GROQ_FAST_MODEL == ""


def test_remote_postgres_gets_sslmode_require():
    s1 = make_settings(DATABASE_URL="postgresql://u:p@db.example.com/d")
    assert "sslmode=require" in s1.DATABASE_URL

    s2 = make_settings(DATABASE_URL="postgresql+psycopg2://u:p@db.example.com/d")
    assert "sslmode=require" in s2.DATABASE_URL


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer"])
def test_insecure_sslmodes_rejected(sslmode):
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL=f"postgresql://u:p@db.example.com/d?sslmode={sslmode}")


@pytest.mark.parametrize("sslmode", ["verify-full", "verify-ca", "require"])
def test_secure_sslmodes_preserved(sslmode):
    url = f"postgresql://u:p@db.example.com/d?sslmode={sslmode}"
    s = make_settings(DATABASE_URL=url)
    assert f"sslmode={sslmode}" in s.DATABASE_URL
    assert s.DATABASE_URL.count("sslmode=") == 1


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost/d",
        "postgresql://u:p@127.0.0.1/d",
        "postgresql://u:p@[::1]/d",
        "sqlite:///./a.db",
    ],
)
def test_local_and_sqlite_untouched(url):
    s = make_settings(DATABASE_URL=url)
    assert "sslmode" not in s.DATABASE_URL


def test_postgres_scheme_rejected():
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL="postgres://u:p@db.example.com/d")


def test_invalid_url_is_validation_error():
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL="not a url")


def test_database_url_errors_do_not_leak_password():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(DATABASE_URL="postgresql://user:pw-sentinel-9x@db.example.com/d?sslmode=disable")
    assert "pw-sentinel-9x" not in str(exc_info.value)



def test_conftest_sets_every_settings_field():
    import os
    from app.config import Settings
    missing = [name for name in Settings.model_fields if name not in os.environ]
    assert not missing, f"conftest.py did not set these Settings fields in os.environ: {missing}"
