"""Provider-agnostic LLM client (Anthropic / OpenAI / DeepSeek).

Model and provider are selected via the environment so users can switch backends
without editing config:

    ENGRAM_MODEL      overrides config.model (e.g. gpt-4o, deepseek-chat)
    ENGRAM_PROVIDER   anthropic | openai | deepseek (optional; inferred from model)

API keys come from ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY — never
config or DB (DESIGN §8). DeepSeek is OpenAI-API-compatible, so it reuses the
OpenAI SDK with a custom base_url and JSON-object output mode.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .config import Config

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

ANTHROPIC_PREFIXES = ("claude", "opus", "sonnet", "haiku", "fable", "mythos")
OPENAI_PREFIXES = ("gpt", "o1", "o3", "o4", "chatgpt")


def infer_provider(model: str) -> str:
    m = model.lower()
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith(OPENAI_PREFIXES):
        return "openai"
    if m.startswith(ANTHROPIC_PREFIXES):
        return "anthropic"
    return "anthropic"  # safe default


def build_from_env(config: Config) -> "LLMClient":
    """Build an LLM client from env overrides, falling back to config.model."""
    model = os.environ.get("ENGRAM_MODEL") or config.model
    provider = os.environ.get("ENGRAM_PROVIDER") or infer_provider(model)

    if provider == "anthropic":
        return AnthropicClient(model)
    if provider == "openai":
        return OpenAICompatClient(model, api_key_env="OPENAI_API_KEY")
    if provider == "deepseek":
        return OpenAICompatClient(
            model,
            base_url=DEEPSEEK_BASE_URL,
            api_key_env="DEEPSEEK_API_KEY",
            json_schema_supported=False,
        )
    raise ValueError(f"unknown provider {provider!r} (set ENGRAM_PROVIDER)")


class LLMClient:
    """Interface: distillation only needs structured JSON + plain text."""

    model: str

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 4096) -> dict:
        raise NotImplementedError

    def complete_text(self, *, system: str, prompt: str, max_tokens: int = 512) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, model: str, *, _sdk: Any = None):
        self.model = model
        self._sdk = _sdk

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def _text(self, response: Any) -> str:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        raise ValueError("no text block in Anthropic response")

    def complete_json(self, *, system, prompt, schema, max_tokens=4096) -> dict:
        response = self.sdk.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        return json.loads(self._text(response))

    def complete_text(self, *, system, prompt, max_tokens=512) -> str:
        response = self.sdk.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._text(response).strip()


class OpenAICompatClient(LLMClient):
    """OpenAI (ChatGPT) and DeepSeek via the OpenAI Chat Completions SDK."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        json_schema_supported: bool = True,
        _sdk: Any = None,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.json_schema_supported = json_schema_supported
        self._sdk = _sdk

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            import openai

            self._sdk = openai.OpenAI(
                base_url=self.base_url, api_key=os.environ.get(self.api_key_env)
            )
        return self._sdk

    def complete_json(self, *, system, prompt, schema, max_tokens=4096) -> dict:
        if self.json_schema_supported:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "engram_distillation", "schema": schema, "strict": True},
            }
            user_content = prompt
        else:
            # DeepSeek JSON mode: ask for json_object and describe the schema inline.
            response_format = {"type": "json_object"}
            user_content = (
                f"{prompt}\n\nReturn a JSON object matching this schema:\n"
                f"{json.dumps(schema)}"
            )
        response = self.sdk.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            response_format=response_format,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        return json.loads(response.choices[0].message.content)

    def complete_text(self, *, system, prompt, max_tokens=512) -> str:
        response = self.sdk.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
