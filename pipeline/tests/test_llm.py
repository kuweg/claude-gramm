"""Tests for provider selection and the LLM client abstraction."""
from __future__ import annotations

import json

import pytest

from engram import llm
from engram.config import DEFAULTS, load_config


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-haiku-4-5-20251001", "anthropic"),
        ("claude-opus-4-8", "anthropic"),
        ("gpt-4o", "openai"),
        ("gpt-5", "openai"),
        ("o3-mini", "openai"),
        ("deepseek-chat", "deepseek"),
        ("deepseek-reasoner", "deepseek"),
    ],
)
def test_infer_provider(model, expected):
    assert llm.infer_provider(model) == expected


def test_build_from_env_defaults_to_config_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ENGRAM_MODEL", raising=False)
    monkeypatch.delenv("ENGRAM_PROVIDER", raising=False)
    cfg = load_config(tmp_path / "missing.toml")  # uses DEFAULTS (a claude model)
    client = llm.build_from_env(cfg)
    assert isinstance(client, llm.AnthropicClient)
    assert client.model == DEFAULTS["model"]


def test_build_from_env_selects_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MODEL", "gpt-4o")
    cfg = load_config(tmp_path / "missing.toml")
    client = llm.build_from_env(cfg)
    assert isinstance(client, llm.OpenAICompatClient)
    assert client.model == "gpt-4o"
    assert client.base_url is None  # vanilla OpenAI
    assert client.api_key_env == "OPENAI_API_KEY"


def test_build_from_env_selects_deepseek(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MODEL", "deepseek-chat")
    cfg = load_config(tmp_path / "missing.toml")
    client = llm.build_from_env(cfg)
    assert isinstance(client, llm.OpenAICompatClient)
    assert client.base_url == "https://api.deepseek.com"
    assert client.api_key_env == "DEEPSEEK_API_KEY"
    assert client.json_schema_supported is False  # DeepSeek uses json_object mode


def test_explicit_provider_overrides_inference(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_PROVIDER", "deepseek")
    monkeypatch.setenv("ENGRAM_MODEL", "some-custom-model")
    cfg = load_config(tmp_path / "missing.toml")
    client = llm.build_from_env(cfg)
    assert isinstance(client, llm.OpenAICompatClient)
    assert client.base_url == "https://api.deepseek.com"


# --- the two client adapters translate to/from their SDK shapes -----------

class _AnthropicBlock:
    def __init__(self, text):
        self.type, self.text = "text", text


class _AnthropicResp:
    def __init__(self, text):
        self.content = [_AnthropicBlock(text)]


class _FakeAnthropicSDK:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _AnthropicResp(json.dumps({"ok": True}))


def test_anthropic_client_complete_json_uses_output_config():
    sdk = _FakeAnthropicSDK()
    client = llm.AnthropicClient("claude-haiku-4-5-20251001", _sdk=sdk)
    out = client.complete_json(system="sys", prompt="p", schema={"type": "object"})
    assert out == {"ok": True}
    assert sdk.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert sdk.calls[0]["model"] == "claude-haiku-4-5-20251001"


class _OAIMessage:
    def __init__(self, content):
        self.content = content


class _OAIChoice:
    def __init__(self, content):
        self.message = _OAIMessage(content)


class _OAIResp:
    def __init__(self, content):
        self.choices = [_OAIChoice(content)]


class _FakeOpenAISDK:
    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _OAIResp(json.dumps({"ok": True}))


def test_openai_client_json_schema_mode():
    sdk = _FakeOpenAISDK()
    client = llm.OpenAICompatClient("gpt-4o", api_key_env="OPENAI_API_KEY", _sdk=sdk)
    out = client.complete_json(system="sys", prompt="p", schema={"type": "object"})
    assert out == {"ok": True}
    assert sdk.calls[0]["response_format"]["type"] == "json_schema"
    assert sdk.calls[0]["model"] == "gpt-4o"


def test_deepseek_client_json_object_mode_embeds_schema():
    sdk = _FakeOpenAISDK()
    client = llm.OpenAICompatClient(
        "deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        json_schema_supported=False,
        _sdk=sdk,
    )
    out = client.complete_json(system="sys", prompt="p", schema={"type": "object"})
    assert out == {"ok": True}
    assert sdk.calls[0]["response_format"] == {"type": "json_object"}
    # schema is described in the prompt so the model knows the shape
    assert "schema" in sdk.calls[0]["messages"][-1]["content"].lower()
