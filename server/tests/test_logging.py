import logging

from app.core.config import Settings
from app.main import create_app


def test_create_app_enables_info_logging_for_agent_diagnostics() -> None:
    create_app(Settings(_env_file=None, token_secret="test-only-secret"))

    assert logging.getLogger("app.api.agent").level == logging.INFO
    assert logging.getLogger("footmarks.agent").level == logging.INFO
