"""LLM helpers — Ollama chat with Tool Calling and JSON fallback."""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Generator, TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel

from config.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# webui 容器内通过 compose 服务名访问 ollama
OLLAMA_BASE_URL = "http://ollama:11434/v1"

_model_override: ContextVar[str | None] = ContextVar("model_override", default=None)


def is_llm_available() -> bool:
    return bool(settings.ollama_model)


def get_chat_client() -> OpenAI | None:
    if not is_llm_available():
        return None
    return OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL)


def default_chat_model() -> str:
    return settings.ollama_model


def chat_model() -> str:
    override = _model_override.get()
    if override:
        return override
    return default_chat_model()


@contextmanager
def use_model(model: str | None) -> Generator[None, None, None]:
    """Temporarily override the chat model for a single request."""
    if not model or not model.strip():
        yield
        return
    token = _model_override.set(model.strip())
    try:
        yield
    finally:
        _model_override.reset(token)


def _ollama_root_url() -> str:
    base = OLLAMA_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def list_ollama_models() -> list[dict[str, Any]]:
    """Return models installed in the Ollama container."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{_ollama_root_url()}/api/tags")
            resp.raise_for_status()
            return [
                {
                    "name": item["name"],
                    "size": item.get("size"),
                    "modified_at": item.get("modified_at"),
                }
                for item in resp.json().get("models", [])
            ]
    except Exception as exc:
        logger.warning("Failed to list Ollama models: %s", exc)
        return []


def list_available_models() -> dict[str, Any]:
    default = default_chat_model()
    models = list_ollama_models()
    names = {m["name"] for m in models}
    return {
        "default": default,
        "default_available": default in names,
        "models": models,
        "reachable": bool(models),
    }


def pydantic_to_tool(model: type[BaseModel], name: str, description: str) -> dict[str, Any]:
    schema = model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def llm_tool_call(
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]],
    tool_name: str,
    *,
    temperature: float = 0.3,
) -> dict[str, Any] | None:
    """Call LLM with a forced tool choice; fall back to JSON-in-content mode."""
    client = get_chat_client()
    if client is None:
        return None

    try:
        resp = client.chat.completions.create(
            model=chat_model(),
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": tool_name}},
            temperature=temperature,
        )
        message = resp.choices[0].message
        if message.tool_calls:
            args = message.tool_calls[0].function.arguments
            data = json.loads(args) if isinstance(args, str) else args
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("Tool call failed for %s: %s", tool_name, exc)

    schema_hint = tools[0]["function"]["parameters"] if tools else {}
    fallback_messages = messages + [
        {
            "role": "user",
            "content": (
                f"请以合法 JSON 输出，符合 schema：\n{json.dumps(schema_hint, ensure_ascii=False)}"
            ),
        }
    ]
    try:
        resp = client.chat.completions.create(
            model=chat_model(),
            messages=fallback_messages,
            temperature=temperature,
        )
        return _extract_json(resp.choices[0].message.content or "")
    except Exception as exc:
        logger.warning("JSON fallback failed for %s: %s", tool_name, exc)
        return None


def llm_with_tools(
    system: str,
    user: str,
    model: type[T],
    tool_name: str,
    tool_description: str,
    *,
    temperature: float = 0.3,
) -> T | None:
    """Run tool-calling LLM and validate result with Pydantic."""
    tools = [pydantic_to_tool(model, tool_name, tool_description)]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    data = llm_tool_call(messages, tools, tool_name, temperature=temperature)
    if not data:
        return None
    try:
        return model.model_validate(data)
    except Exception as exc:
        logger.warning("Pydantic validation failed for %s: %s", tool_name, exc)
        return None
