"""OpenAI-compatible provider (covers NVIDIA, LM Studio, generic endpoints)."""

import json
import re

from openai import AsyncOpenAI

from .base import Provider


class OpenAICompatibleProvider(Provider):
    """Any OpenAI-compatible HTTP endpoint."""

    def __init__(self, url: str, api_key: str, vision_model: str, reasoning_model: str, timeout: int = 90):
        super().__init__(url, api_key, vision_model, reasoning_model, timeout)
        self.client = AsyncOpenAI(base_url=url, api_key=api_key, timeout=timeout)

    def get_name(self) -> str:
        return f"OpenAI-Compatible ({self.url})"

    async def describe_screen(self, image_base64: str) -> str:
        try:
            completion = await self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "You are a precise screen activity analyst. Describe what the user is "
                                    "currently doing on their computer screen. Be specific: identify the active "
                                    "application or website, visible content, and infer the task. Keep it concise "
                                    "but detailed enough to judge productivity."
                                )
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                            }
                        ]
                    }
                ],
                temperature=0.2,
                max_tokens=400,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            return f"[Vision Error: {e}]"

    async def evaluate_focus(self, goal: str, observations: list) -> dict:
        obs_text = "\n".join(
            f"[{obs['timestamp']}] {obs['description']}" for obs in observations
        )
        prompt = (
            f"The user's stated goal for this session is: \"{goal}\"\n\n"
            f"Recent screen observations (most recent last):\n{obs_text}\n\n"
            f"You are a ruthless accountability partner. Be harsh and direct. "
            f"If the user is doing ANYTHING that is not directly advancing their stated goal, "
            f"they are BULLSHITTING. Social media, news, games, idle browsing, chatting = bullshit. "
            f"Only genuine work on the stated goal counts as on-track.\n\n"
            f"Respond ONLY with a JSON object exactly like this:\n"
            f'{{"on_track": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}'
        )
        try:
            completion = await self.client.chat.completions.create(
                model=self.reasoning_model,
                messages=[
                    {"role": "system", "content": "You are a brutally honest focus evaluator. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=400,
            )
            content = completion.choices[0].message.content.strip()
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                result = {"on_track": True, "confidence": 0.5, "reason": "parse error"}
            return result
        except Exception as e:
            return {"on_track": True, "confidence": 0.0, "reason": f"Error: {e}"}

    async def reason_with_prompt(self, prompt: str) -> str:
        """Send raw prompt to reasoning model, return raw response text."""
        completion = await self.client.chat.completions.create(
            model=self.reasoning_model,
            messages=[
                {"role": "system", "content": "You are Jarvis. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return completion.choices[0].message.content.strip()

    async def health_check(self) -> dict:
        try:
            models = await self.client.models.list()
            model_ids = [m.id for m in models.data]
            vision_ok = self.vision_model in model_ids
            reasoning_ok = self.reasoning_model in model_ids
            return {
                "ok": True,
                "models": model_ids,
                "vision_ok": vision_ok,
                "reasoning_ok": reasoning_ok,
                "error": None
            }
        except Exception as e:
            return {"ok": False, "models": [], "vision_ok": False, "reasoning_ok": False, "error": str(e)}


class NvidiaProvider(OpenAICompatibleProvider):
    """NVIDIA API - pre-configured OpenAI-compatible endpoint."""

    def get_name(self) -> str:
        return "NVIDIA NIM"


class LMStudioProvider(OpenAICompatibleProvider):
    """LM Studio local server."""

    def get_name(self) -> str:
        return f"LM Studio ({self.url})"
