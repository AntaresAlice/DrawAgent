import os
import re
from pathlib import Path

import yaml

from .schema import AppConfig


class ConfigLoader:
    """Multi-layer config loader with later-wins merge.

    Reference: opencode's multi-layer discovery pattern.
    Layer order:
      1. Package default template (.drawagent.default.yaml)
      2. User global (~/.drawagent/config.yaml)
      3. Project directory (walk up from cwd, find .drawagent.yaml etc.)
    """

    DISCOVERY_NAMES = [".drawagent.yaml", ".drawagent.yml", "drawagent.yaml"]

    ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

    @classmethod
    async def load(cls, project_dir: Path | None = None) -> AppConfig:
        configs: list[dict] = []

        # Layer 1: package default
        default_path = Path(__file__).parent.parent.parent.parent / ".drawagent.default.yaml"
        if default_path.exists():
            configs.append(cls._load_file(default_path))

        # Layer 2: user global
        user_config = Path.home() / ".drawagent" / "config.yaml"
        if user_config.exists():
            configs.append(cls._load_file(user_config))

        # Layer 3: project directory (walk upward)
        search_dir = project_dir or Path.cwd()
        for parent in [search_dir, *search_dir.parents]:
            found = False
            for name in cls.DISCOVERY_NAMES:
                f = parent / name
                if f.exists():
                    configs.append(cls._load_file(f))
                    found = True
                    break
            if found:
                break

        merged = cls._deep_merge(configs)
        return AppConfig(**merged)

    @classmethod
    def _load_file(cls, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls._resolve_env_vars(data)

    @classmethod
    def _resolve_env_vars(cls, data: dict) -> dict:
        """Recursively resolve ${VAR_NAME} from environment variables."""
        resolved = {}
        for key, value in data.items():
            if isinstance(value, dict):
                resolved[key] = cls._resolve_env_vars(value)
            elif isinstance(value, str):
                resolved[key] = cls._resolve_string(value)
            elif isinstance(value, list):
                resolved[key] = [
                    cls._resolve_string(v) if isinstance(v, str) else v for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    @classmethod
    def _resolve_string(cls, value: str) -> str:
        def _replacer(match):
            varname = match.group(1)
            return os.environ.get(varname, "")
        return cls.ENV_VAR_RE.sub(_replacer, value)

    @classmethod
    def _deep_merge(cls, configs: list[dict]) -> dict:
        """Merge config dicts, later wins."""
        result: dict = {}
        for cfg in configs:
            cls._merge_into(result, cfg)
        return result

    @classmethod
    def _merge_into(cls, base: dict, overlay: dict) -> None:
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                cls._merge_into(base[key], value)
            else:
                base[key] = value
