"""Shared test fixtures for DrawAgent."""

import pytest

from drawagent.config.schema import (
    AgentAConfig,
    AgentCConfig,
    AppConfig,
)
from drawagent.core.events import EventBus
from drawagent.core.types import Session


@pytest.fixture
def app_config():
    return AppConfig(
        agent_a=AgentAConfig(api_key="sk-test"),
        agent_c=AgentCConfig(api_key="sk-test"),
    )


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def fresh_session():
    return Session(id="test-session", user_request="draw a cat")


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test.db")
