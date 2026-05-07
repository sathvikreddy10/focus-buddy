"""Ollama local provider."""

import json

import aiohttp

from .base import Provider


class OllamaProvider(Provider):
    """Ollama local server."""

    def __init__(self, url: str = "http://localhost:11434", api_key: str = "", vision_model: str = "", reasoning_model: str = "", timeout: int = 90):
        # Ollama doesn't use api_key typically
        super().__init__(url, api_key or "ollama", vision_model, reasoning_model, timeout)
        self.base_url = url.rstrip("/")

    def get_name(self) -> str:
        return f"Ollama ({self.base_url})"

    async def describe_screen(self, image_base64: str) -> str:
        payload = {
            "model": self.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "You are a precise screen activity analyst. Describe what the user is "
                        "currently doing on their computer screen. Be specific: identify the active "
                        "application or website, visible content, and infer the task. Keep it concise "
                        "but detailed enough to judge productivity."
                    ),
                    "images": [image_base64]
                }
            ],
            "stream": False,
            "options": {"temperature": 0.2}
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "[No response]").strip()
        except Exception as e:
            return f"[Vision Error: {e}]"

    async def evaluate_focus(self, goal: str, observations: list) -> dict:
        obs_text = "\n".join(
            f"[{obs['timestamp']}] {obs['description']}" for obs in observations
        )
        prompt = (
            f"The user's stated goal for this session is: \"{goal}\"\n\n"
            f"Recent screen observations:\n{obs_text}\n\n"
            f"You are a ruthless accountability partner. If the user is doing ANYTHING "
            f"not directly advancing their stated goal, they are BULLSHITTING.\n\n"
            f"Respond ONLY with JSON: {{\"on_track\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"brief\"}}"
        )
        payload = {
            "model": self.reasoning_model,
            "messages": [
                {"role": "system", "content": "You are a brutally honest focus evaluator. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": 0.3}
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                    data = await resp.json()
                    content = data.get("message", {}).get("content", "{}").strip()
                    import re
                    match = re.search(r'\{.*\}', content, re.DOTALL)
                    if match:
                        result = json.loads(match.group())
                    else:
                        result = {"on_track": True, "confidence": 0.5, "reason": "parse error"}
                    return result
        except Exception as e:
            return {"on_track": True, "confidence": 0.0, "reason": f"Error: {e}"}

    async def health_check(self) -> dict:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {
                        "ok": True,
                        "models": models,
                        "vision_ok": self.vision_model in models,
                        "reasoning_ok": self.reasoning_model in models,
                        "error": None
                    }
        except Exception as e:
            return {"ok": False, "models": [], "vision_ok": False, "reasoning_ok": False, "error": str(e)}
