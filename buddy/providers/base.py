"""Base provider interface for AI backends."""

from abc import ABC, abstractmethod
from typing import Optional


class Provider(ABC):
    """Abstract base for vision + reasoning providers."""

    def __init__(self, url: str, api_key: str, vision_model: str, reasoning_model: str, timeout: int = 90):
        self.url = url
        self.api_key = api_key
        self.vision_model = vision_model
        self.reasoning_model = reasoning_model
        self.timeout = timeout

    @abstractmethod
    async def describe_screen(self, image_base64: str) -> str:
        """Send screenshot to vision model, return description."""
        ...

    @abstractmethod
    async def evaluate_focus(self, goal: str, observations: list) -> dict:
        """Send observations to reasoning model, return {on_track, confidence, reason}."""
        ...

    @abstractmethod
    async def reason_with_prompt(self, prompt: str) -> str:
        """Send a raw prompt to the reasoning model, return raw text response."""
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """Check if provider is reachable. Returns {ok: bool, models: list, error: str}."""
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable provider name."""
        ...
