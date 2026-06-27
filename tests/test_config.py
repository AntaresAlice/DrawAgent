"""Unit tests for config system."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from drawagent.config.loader import ConfigLoader
from drawagent.config.schema import (
    AgentAConfig,
    AgentBConfig,
    AgentCConfig,
    AppConfig,
    LoopConfig,
    MemoryConfig,
)


class TestAppConfig:
    def test_default_config(self):
        cfg = AppConfig()
        assert cfg.agent_a.model == "gpt-4o"
        assert cfg.agent_a.temperature == 0.7
        assert cfg.agent_b.model == "Z-Image-Turbo"
        assert cfg.agent_c.temperature == 0.3
        assert cfg.loop.max_iterations == 7
        assert cfg.memory.auto_load is True
        assert cfg.output_dir == "./outputs"

    def test_partial_override(self):
        cfg = AppConfig(
            agent_a=AgentAConfig(model="gpt-4o-mini", temperature=0.3),
            loop=LoopConfig(max_iterations=3),
        )
        assert cfg.agent_a.model == "gpt-4o-mini"
        assert cfg.agent_a.temperature == 0.3
        assert cfg.agent_a.api_base == "https://api.openai.com/v1"  # default
        assert cfg.loop.max_iterations == 3
        assert cfg.agent_b.model == "Z-Image-Turbo"  # default

    def test_agent_default_params(self):
        b = AgentBConfig()
        assert b.default_params["width"] == 1024
        assert b.default_params["height"] == 1024
        assert b.default_params["steps"] == 8

    def test_memory_config(self):
        m = MemoryConfig(base_dir="/tmp/mem")
        assert m.base_dir == "/tmp/mem"
        assert m.auto_load is True
        assert m.auto_save is False


class TestConfigLoader:
    def test_env_var_resolution(self):
        os.environ["TEST_FOO"] = "bar123"
        result = ConfigLoader._resolve_string("prefix_${TEST_FOO}_suffix")
        assert result == "prefix_bar123_suffix"
        del os.environ["TEST_FOO"]

    def test_env_var_not_set(self):
        result = ConfigLoader._resolve_string("${NONEXISTENT_VAR_XYZ}")
        assert result == ""

    def test_deep_merge_later_wins(self):
        base = {"a": 1, "b": {"x": 1, "y": 2}}
        overlay = {"b": {"y": 99, "z": 3}, "c": 4}
        ConfigLoader._merge_into(base, overlay)
        assert base["a"] == 1
        assert base["b"]["x"] == 1
        assert base["b"]["y"] == 99
        assert base["b"]["z"] == 3
        assert base["c"] == 4

    def test_deep_merge_multiple(self):
        c1 = {"a": {"x": 1}}
        c2 = {"a": {"y": 2}}
        c3 = {"a": {"z": 3}}
        result = ConfigLoader._deep_merge([c1, c2, c3])
        assert result["a"] == {"x": 1, "y": 2, "z": 3}

    def test_resolve_env_vars_nested(self):
        os.environ["KEY"] = "val"
        data = {"top": {"nested": "${KEY}"}, "arr": ["${KEY}"]}
        result = ConfigLoader._resolve_env_vars(data)
        assert result["top"]["nested"] == "val"
        assert result["arr"][0] == "val"
        del os.environ["KEY"]

    @pytest.mark.asyncio
    async def test_load_default_and_user_merge(self, tmp_path):
        # Only default config exists, no user/project config
        cfg = await ConfigLoader.load(project_dir=tmp_path)
        assert isinstance(cfg, AppConfig)
        assert cfg.agent_a.model == "gpt-4o"
