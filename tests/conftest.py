import os
import sys
import shutil
import secrets
import tempfile
from pathlib import Path
import pytest
from cryptography.fernet import Fernet

# Stop app/config.py from loading the real .env during tests;
# this must happen before any app.* import so load_dotenv() is a no-op.
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False

_TEST_TEMP_DIR = tempfile.mkdtemp(prefix="sqlagent_tests_")
_TEST_DB_PATH = Path(_TEST_TEMP_DIR) / "test.db"

os.environ["SECRET_KEY"] = secrets.token_hex(32)
os.environ["CONNECTION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["GROQ_API_KEY"] = "dummy-not-a-key"
os.environ["GROQ_MODEL"] = "test-model-primary"
os.environ["GROQ_FAST_MODEL"] = "test-model-fast"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_API_KEY"] = ""
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_PROJECT"] = "sqlagent-tests"
os.environ["APP_NAME"] = "AI SQL Agent"
os.environ["DEBUG"] = "false"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000"
os.environ["MAX_QUERY_COMPLEXITY"] = "100"
os.environ["QUERY_TIMEOUT_SECONDS"] = "30"
os.environ["ENABLE_WRITE_OPERATIONS"] = "false"
os.environ["ENABLE_DELETE_OPERATIONS"] = "false"
os.environ["ENABLE_DDL_OPERATIONS"] = "false"
os.environ["GITHUB_CLIENT_ID"] = ""
os.environ["GITHUB_CLIENT_SECRET"] = ""
os.environ["GITHUB_REDIRECT_URI"] = "http://localhost:8000/auth/github/callback"


@pytest.fixture
def valid_secret_key() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def valid_fernet_key() -> str:
    return Fernet.generate_key().decode()


def pytest_sessionfinish(session, exitstatus):
    if "app.database" in sys.modules:
        sys.modules["app.database"].engine.dispose()
    shutil.rmtree(_TEST_TEMP_DIR, ignore_errors=True)


@pytest.fixture
def client(tmp_path):
    """Fresh SQLite database and TestClient for every test; nothing is written to the repo."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.main import app
    from app.database import Base, get_db

    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
