"""Configuration management for Focus Buddy.

Follows the XDG Base Directory Specification:
- Config: ~/.config/buddy/config.json
- Data:   ~/.local/share/buddy/
"""

import json
import os
from pathlib import Path
from typing import Any, Optional


DEFAULT_CONFIG = {
    "version": "0.2.0",
    "default_provider": "nvidia",
    "capture_interval": 15,
    "eval_interval": 4,
    "providers": {
        "nvidia": {
            "type": "nvidia",
            "url": "https://integrate.api.nvidia.com/v1",
            "api_key": "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",
            "vision_model": "meta/llama-3.2-11b-vision-instruct",
            "reasoning_model": "qwen/qwen2.5-coder-32b-instruct",
            "timeout": 90
        }
    }
}


def _get_config_dir() -> Path:
    """Get XDG config directory."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "buddy"
    return Path.home() / ".config" / "buddy"


def _get_data_dir() -> Path:
    """Get XDG data directory."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "buddy"
    return Path.home() / ".local" / "share" / "buddy"


def get_config_path() -> Path:
    """Get the config file path."""
    return _get_config_dir() / "config.json"


def get_logs_dir() -> Path:
    """Get the logs directory."""
    return _get_data_dir() / "logs"


def ensure_dirs():
    """Ensure config and data directories exist."""
    _get_config_dir().mkdir(parents=True, exist_ok=True)
    _get_data_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config from disk, or create default if not exists."""
    ensure_dirs()
    path = get_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Merge with defaults for missing keys
            merged = DEFAULT_CONFIG.copy()
            merged.update(cfg)
            if "providers" in cfg:
                merged["providers"] = {**DEFAULT_CONFIG["providers"], **cfg["providers"]}
            return merged
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """Save config to disk."""
    ensure_dirs()
    with open(get_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get_provider_config(name: Optional[str] = None) -> dict:
    """Get config for a specific provider."""
    cfg = load_config()
    name = name or cfg.get("default_provider", "nvidia")
    providers = cfg.get("providers", {})
    if name not in providers:
        raise ValueError(f"Provider '{name}' not found. Run: buddy provider add {name}")
    return providers[name]


def add_provider(name: str, provider_cfg: dict):
    """Add or update a provider."""
    cfg = load_config()
    cfg["providers"][name] = provider_cfg
    save_config(cfg)


def remove_provider(name: str):
    """Remove a provider."""
    cfg = load_config()
    if name not in cfg.get("providers", {}):
        raise ValueError(f"Provider '{name}' not found")
    del cfg["providers"][name]
    if cfg.get("default_provider") == name:
        remaining = list(cfg["providers"].keys())
        cfg["default_provider"] = remaining[0] if remaining else ""
    save_config(cfg)


def set_default_provider(name: str):
    """Set the default provider."""
    cfg = load_config()
    if name not in cfg.get("providers", {}):
        raise ValueError(f"Provider '{name}' not found")
    cfg["default_provider"] = name
    save_config(cfg)


def list_providers() -> dict:
    """List all configured providers."""
    cfg = load_config()
    return cfg.get("providers", {})


def get(key: str, default: Any = None) -> Any:
    """Get a top-level config value."""
    cfg = load_config()
    return cfg.get(key, default)


def set_(key: str, value: Any):
    """Set a top-level config value."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
