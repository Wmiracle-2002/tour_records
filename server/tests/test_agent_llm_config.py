import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_llm_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOOTMARKS_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("FOOTMARKS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("FOOTMARKS_LLM_MODEL", "test-model")
    monkeypatch.setenv("FOOTMARKS_LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("FOOTMARKS_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("FOOTMARKS_AGENT_TOTAL_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("FOOTMARKS_AGENT_STAGE_TIMEOUT_SECONDS", "45")

    settings = Settings(_env_file=None)

    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "test-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_retries == 2
    assert settings.agent_total_timeout_seconds == 90.0
    assert settings.agent_stage_timeout_seconds == 45.0


def test_llm_settings_default_to_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FOOTMARKS_LLM_BASE_URL",
        "FOOTMARKS_LLM_API_KEY",
        "FOOTMARKS_LLM_MODEL",
        "FOOTMARKS_LLM_TIMEOUT_SECONDS",
        "FOOTMARKS_LLM_MAX_RETRIES",
        "FOOTMARKS_AGENT_TOTAL_TIMEOUT_SECONDS",
        "FOOTMARKS_AGENT_STAGE_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.llm_base_url is None
    assert settings.llm_api_key is None
    assert settings.llm_model is None
    assert settings.llm_timeout_seconds == 30.0
    assert settings.llm_max_retries == 1
    assert settings.agent_total_timeout_seconds == 120.0
    assert settings.agent_stage_timeout_seconds == 60.0


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("FOOTMARKS_LLM_TIMEOUT_SECONDS", "0"),
        ("FOOTMARKS_LLM_MAX_RETRIES", "-1"),
        ("FOOTMARKS_AGENT_TOTAL_TIMEOUT_SECONDS", "0"),
        ("FOOTMARKS_AGENT_STAGE_TIMEOUT_SECONDS", "-1"),
    ),
)
def test_llm_retry_and_timeout_bounds_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
