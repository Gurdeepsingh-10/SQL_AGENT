import pytest
from app.config import settings
from app.core.agent.nlp_processor import NLPProcessor
from app.core.agent.sql_generator import SQLGenerator


@pytest.mark.parametrize("cls", [NLPProcessor, SQLGenerator])
def test_fast_model_fallback_to_primary(monkeypatch, cls):
    monkeypatch.setattr(settings, "GROQ_FAST_MODEL", "")
    monkeypatch.setattr(settings, "GROQ_MODEL", "m-primary")
    instance = cls()
    assert instance.fast_model == "m-primary"


@pytest.mark.parametrize("cls", [NLPProcessor, SQLGenerator])
def test_fast_model_uses_fast_model(monkeypatch, cls):
    monkeypatch.setattr(settings, "GROQ_FAST_MODEL", "m-fast")
    monkeypatch.setattr(settings, "GROQ_MODEL", "m-primary")
    instance = cls()
    assert instance.fast_model == "m-fast"

