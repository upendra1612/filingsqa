"""Minimal client for OpenAI-compatible chat APIs (Groq by default, Gemini also works).

Configured by environment variables (put them in .env):
    LLM_API_KEY   or GROQ_API_KEY
    LLM_BASE_URL  default https://api.groq.com/openai/v1
    LLM_MODEL     default openai/gpt-oss-120b
For Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai

Groq retired Llama 3.3 70B for free accounts on 2026-08-16 and recommends
openai/gpt-oss-120b. Free models change often, so check_model() confirms the model
exists before a long run starts.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Reasoning models think before answering. For short cited answers we keep that
# cheap and leave it out of the reply (Groq docs: "Reasoning" page).
REASONING_PARAMS = {
    "openai/gpt-oss": {"reasoning_effort": "low", "include_reasoning": False},
    "qwen/qwen3": {"reasoning_effort": "none"},
}


def extra_params(model: str) -> dict:
    for prefix, params in REASONING_PARAMS.items():
        if model.startswith(prefix):
            return dict(params)
    return {}


class LLMError(RuntimeError):
    pass


class DailyLimitError(LLMError):
    """The provider's daily token or request quota is used up; try again later."""


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model: str
    finish_reason: str = ""


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

    def check_model(self) -> None:
        """Fail fast, with the alternatives, if the configured model is not offered."""
        resp = self.session.get(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        if resp.status_code == 401:
            raise LLMError("API key rejected (HTTP 401): check GROQ_API_KEY in .env")
        if resp.status_code != 200:
            raise LLMError(f"could not list models: HTTP {resp.status_code}: {resp.text[:200]}")
        ids = sorted(m["id"] for m in resp.json().get("data", []))
        if self.model not in ids:
            raise LLMError(
                f"model '{self.model}' is not available on this account. "
                f"Set LLM_MODEL in .env to one of: {', '.join(ids)}"
            )

    def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1500
    ) -> Completion:
        # max_tokens leaves room for a reasoning model's hidden thinking
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            **extra_params(self.model),
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
                    finish_reason=data["choices"][0].get("finish_reason") or "",
                )
            if resp.status_code in (429, 500, 502, 503) and attempt < self.max_retries:
                # free tiers rate-limit per minute; the server says how long to wait
                retry_after = resp.headers.get("retry-after", "")
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 2.0**attempt * 5
                daily = "per day" in resp.text.lower() or "(tpd)" in resp.text.lower()
                if resp.status_code == 429 and (daily or wait > 300):
                    raise DailyLimitError(
                        f"daily limit reached for {self.model} (retry after ~{wait / 3600:.1f} h)"
                    )
                self._sleep(min(max(wait, 1.0), 120))
                continue
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise LLMError("unreachable")
