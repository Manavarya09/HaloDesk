"""Configuration loader — merges defaults.yaml with environment overrides."""

import os
import yaml
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULTS = _CONFIG_DIR / "defaults.yaml"


def load_config(override_path: str | None = None) -> dict:
    """Load config from defaults.yaml, optionally overridden by another YAML, plus env vars."""
    with open(_DEFAULTS) as f:
        cfg = yaml.safe_load(f)

    if override_path and Path(override_path).exists():
        with open(override_path) as f:
            overrides = yaml.safe_load(f) or {}
        _deep_merge(cfg, overrides)

    # Environment variable overrides
    env_map = {
        "LINKUP_API_KEY": ("linkup", "api_key"),
        "OLLAMA_HOST": ("agent", "ollama_host"),
        "AGENT_EMAIL_PASSWORD": ("email", "password"),
        "AGENT_MODEL": ("agent", "model"),
    }
    for env_var, key_path in env_map.items():
        val = os.environ.get(env_var)
        if val:
            _set_nested(cfg, key_path, val)

    return cfg


def _deep_merge(base: dict, overrides: dict):
    for k, v in overrides.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _set_nested(d: dict, keys: tuple, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
