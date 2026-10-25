"""LLM 客户端封装：chat / chat_json / embed，兼容任意 OpenAI 兼容接口。"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .config import settings

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.api_key:
            raise RuntimeError("未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填写。")
        _client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
    return _client


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.3,
         max_tokens: int = 4096) -> str:
    kwargs: dict = {"extra_body": settings.extra_body} if settings.extra_body else {}
    resp = client().chat.completions.create(
        model=model or settings.model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


JSON_RETRY_PROMPT = "上面的输出不是合法 JSON。请只输出 JSON 本身，不要任何解释或代码块围栏。"


def chat_json(messages: list[dict], model: str | None = None, temperature: float = 0.2,
              max_tokens: int = 8192, retries: int = 2) -> Any:
    """要求模型返回 JSON；自动剥离代码块围栏，解析失败时带错误反馈重试。"""
    msgs = list(messages)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        text = chat(msgs, model=model, temperature=temperature if attempt == 0 else 0.0,
                    max_tokens=max_tokens)
        try:
            return extract_json(text)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            msgs = [*msgs,
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": JSON_RETRY_PROMPT}]
    raise RuntimeError(f"模型输出无法解析为 JSON: {last_exc}")


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lo = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        hi = max(text.rfind("}"), text.rfind("]"))
        if lo == -1 or hi <= lo:
            raise ValueError(f"找不到 JSON 边界: {text[:120]!r}")
        return json.loads(text[lo:hi + 1])


def embed(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client().embeddings.create(model=settings.embedding_model, input=batch)
        out.extend(d.embedding for d in resp.data)
    return out
