"""Hierarchical config loading: default.yaml -> {env}.yaml -> env vars (QT_ prefix)."""

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _apply_env_overrides(config: dict, prefix: str = "QT") -> dict:
    """Override config values with QT_-prefixed environment variables.

    Mapping: QT_REDIS_HOST -> config["redis"]["host"]
    Special cases handled for known flat keys.
    """
    flat_map = {
        "QT_ENV": ("app", "env"),
        "QT_REDIS_HOST": ("redis", "host"),
        "QT_REDIS_PORT": ("redis", "port"),
        "QT_BINANCE_API_KEY": ("binance", "api_key"),
        "QT_BINANCE_API_SECRET": ("binance", "api_secret"),
        "QT_ALPACA_API_KEY": ("alpaca", "api_key"),
        "QT_ALPACA_API_SECRET": ("alpaca", "api_secret"),
        "QT_TELEGRAM_BOT_TOKEN": ("monitoring", "telegram", "bot_token"),
        "QT_TELEGRAM_CHAT_ID": ("monitoring", "telegram", "chat_id"),
        "QT_DATABASE_HOST": ("database", "host"),
        "QT_DATABASE_PORT": ("database", "port"),
        "QT_DB_PASSWORD": ("database", "password"),
    }

    for env_key, path in flat_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            # Navigate to the nested key and set it
            node = config
            for part in path[:-1]:
                node = node.setdefault(part, {})
            # Auto-cast port numbers
            if path[-1] == "port":
                try:
                    value = int(value)
                except ValueError:
                    pass
            node[path[-1]] = value

    return config


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def load_config() -> dict[str, Any]:
    """Load and return the merged configuration dictionary."""
    # 1. Load base defaults
    config = _load_yaml(_CONFIG_DIR / "default.yaml")

    # 2. Determine environment and merge env-specific overrides
    env = os.environ.get("QT_ENV", config.get("app", {}).get("env", "dev"))
    env_config = _load_yaml(_CONFIG_DIR / f"{env}.yaml")
    config = _deep_merge(config, env_config)

    # 3. Apply environment variable overrides
    config = _apply_env_overrides(config)

    # Ensure env is set correctly after all merges
    config.setdefault("app", {})["env"] = env

    return config


def get_nested(config: dict, *keys, default=None):
    """Safely get a nested config value: get_nested(cfg, 'redis', 'host')."""
    node = config
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return default
        if node is None:
            return default
    return node
