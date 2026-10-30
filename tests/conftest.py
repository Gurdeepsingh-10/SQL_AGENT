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
