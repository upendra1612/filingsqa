"""Minimal client for OpenAI-compatible chat APIs (Groq by default, Gemini also works).

Configured by environment variables (put them in .env):
    LLM_API_KEY   or GROQ_API_KEY
    LLM_BASE_URL  default https://api.groq.com/openai/v1
    LLM_MODEL     default llama-3.3-70b-versatile
For Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model: str


class ChatClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        session: requests.Session | None = None,
        max_retries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise LLMError("Set GROQ_API_KEY (or LLM_API_KEY) in .env")
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self._sleep = sleep

    def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 400
    ) -> Completion:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self.max_retries + 1):
            started = time.time()
            try:
                resp = self.session.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=120
                )
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise LLMError(f"request failed: {exc}") from exc
                self._sleep(min(2.0**attempt, 60))
                continue
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage") or {}
                return Completion(
                    text=data["choices"][0]["message"]["content"] or "",
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    latency_ms=int((time.time() - started) * 1000),
                    model=data.get("model", self.model),
                )
            if resp.status_code in (429, 500, 502, 503) and attempt < self.max_retries:
                # free tiers rate-limit per minute; the server says how long to wait
                retry_after = resp.headers.get("retry-after", "")
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 2.0**attempt * 5
                self._sleep(min(max(wait, 1.0), 120))
                continue
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise LLMError("unreachable")
