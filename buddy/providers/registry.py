"""Provider registry - maps names to provider classes and handles discovery."""

from typing import Optional, Type

from .base import Provider
from .openai_compatible import NvidiaProvider, LMStudioProvider, OpenAICompatibleProvider
from .ollama import OllamaProvider


# Registry of provider types
_PROVIDER_TYPES = {
    "nvidia": NvidiaProvider,
    "lmstudio": LMStudioProvider,
    "openai": OpenAICompatibleProvider,
    "ollama": OllamaProvider,
}


def get_provider_class(provider_type: str) -> Optional[Type[Provider]]:
    """Get provider class by type string."""
    return _PROVIDER_TYPES.get(provider_type.lower())


def list_provider_types() -> dict:
    """List available provider types."""
    return {
        name: cls.__doc__ or name
        for name, cls in _PROVIDER_TYPES.items()
    }


def create_provider(cfg: dict) -> Provider:
    """Create a provider instance from config dict."""
    ptype = cfg.get("type", "openai").lower()
    cls = get_provider_class(ptype)
    if not cls:
        raise ValueError(f"Unknown provider type: {ptype}. Available: {list(_PROVIDER_TYPES.keys())}")
    return cls(
        url=cfg.get("url", ""),
        api_key=cfg.get("api_key", ""),
        vision_model=cfg.get("vision_model", ""),
        reasoning_model=cfg.get("reasoning_model", ""),
        timeout=cfg.get("timeout", 90)
    )


def get_provider(name: str, cfg_dict: Optional[dict] = None):
    """Get provider by name from config, or from explicit dict."""
    from .. import config
    if cfg_dict:
        return create_provider(cfg_dict)
    provider_cfg = config.get_provider_config(name)
    return create_provider(provider_cfg)
