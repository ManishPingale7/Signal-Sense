"""Multi-provider LLM routing with per-provider pacing and automatic fallback."""
from __future__ import annotations

import json
import os
import time
from typing import Callable
import threading

_REQUEST_TIMES = {}
_COOLDOWNS = {}
_PACING_LOCK = threading.Lock()
MAX_ATTEMPTS = 24

class ProviderUnavailable(RuntimeError):
    """Safe error that never contains a remote response or credential."""

def failure_kind(exc):
    code = str(getattr(exc, "status_code", getattr(exc, "code", "")))
    message = str(exc).lower()
    if code == "429" or "429" in message or "rate limit" in message or "quota" in message:
        return "rate limit"
    if code in ("401", "403"):
        return "credentials rejected"
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return "request timed out"
    return "request unavailable or invalid response"

from pydantic import BaseModel


def _clean_json_text(text: str) -> str:
    """Strip markdown code fence blocks if an LLM wraps JSON in them."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class Provider:
    """Base class for an LLM provider with independent request pacing."""

    def __init__(self, name: str, model: str, min_delay: float = 10):
        self.name = name
        self.model = model
        self.min_delay = min_delay

    def pace(self, log: Callable):
        """Enforce minimum delay between requests to this specific provider."""
        with _PACING_LOCK:
            delay = max(0, _REQUEST_TIMES.get(self.name, 0) + self.min_delay - time.monotonic())
        if delay:
            log("wait", f"Pacing {self.name} requests", f"Waiting {int(delay) + 1}s.")
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
            log("checkpoint", "", "")
        with _PACING_LOCK:
            _REQUEST_TIMES[self.name] = time.monotonic()

    def call(self, prompt: str, schema: type[BaseModel], log: Callable) -> BaseModel:
        raise NotImplementedError

    def close(self):
        """Release any resources held by the provider."""
        close = getattr(getattr(self, "client", None), "close", None)
        if close:
            close()


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

class GeminiProvider(Provider):
    """Google Gemini via the google-genai SDK."""

    def __init__(self):
        from google import genai
        from google.genai import types

        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        super().__init__("Gemini", model, min_delay=13)
        self.client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(
                timeout=45_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def call(self, prompt, schema, log):
        self.pace(log)
        log("decide", f"Calling {self.name}", self.model)
        result = self.client.interactions.create(
            model=self.model, input=prompt,
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": schema.model_json_schema()},
        )
        if not result.output_text:
            raise ValueError("Empty Gemini response")
        return schema.model_validate_json(_clean_json_text(result.output_text))

    def close(self):
        self.client.close()


class GroqProvider(Provider):
    """Groq cloud inference — blazing fast, generous free tier."""

    def __init__(self):
        from groq import Groq

        model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        super().__init__("Groq", model, min_delay=5)
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=45, max_retries=0)

    def call(self, prompt, schema, log):
        self.pace(log)
        log("decide", f"Calling {self.name}", self.model)
        system_content = (
            "You are a precise JSON generator. Respond ONLY with valid JSON "
            "matching the requested schema. No markdown, no backticks, no explanatory text.\n\n"
            f"Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        result = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=6000,
            temperature=0.2,
        )
        text = result.choices[0].message.content
        if not text:
            raise ValueError("Empty Groq response")
        return schema.model_validate_json(_clean_json_text(text))


class MistralProvider(Provider):
    """Mistral AI with native structured output."""

    def __init__(self):
        try:
            from mistralai import Mistral
        except (ImportError, AttributeError):
            from mistralai.client import Mistral

        model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
        super().__init__("Mistral", model, min_delay=5)
        self.client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"), timeout_ms=45_000, retry_config=None)

    def call(self, prompt, schema, log):
        self.pace(log)
        log("decide", f"Calling {self.name}", self.model)
        system_content = (
            "You are a precise JSON generator. Respond ONLY with valid JSON "
            "matching the requested schema. No markdown, no backticks, no explanatory text.\n\n"
            f"Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        result = self.client.chat.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=6000,
            temperature=0.2,
        )
        text = result.choices[0].message.content
        if not text:
            raise ValueError("Empty Mistral response")
        return schema.model_validate_json(_clean_json_text(text))


class OpenRouterProvider(Provider):
    """OpenRouter — aggregated access to many models via OpenAI-compatible API."""

    def __init__(self):
        from openai import OpenAI

        model = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b:free")
        super().__init__("OpenRouter", model, min_delay=8)
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"), timeout=45, max_retries=0,
        )

    def call(self, prompt, schema, log):
        self.pace(log)
        log("decide", f"Calling {self.name}", self.model)
        system_content = (
            "You are a precise JSON generator. Respond ONLY with valid JSON "
            "matching the requested schema. No markdown, no backticks, no explanatory text.\n\n"
            f"Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        result = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=6000,
            temperature=0.2,
        )
        text = result.choices[0].message.content
        if not text:
            raise ValueError("Empty OpenRouter response")
        return schema.model_validate_json(_clean_json_text(text))


# ---------------------------------------------------------------------------
# Provider Router — task-based assignment with automatic fallback
# ---------------------------------------------------------------------------

_PROVIDER_KEYS: dict[str, tuple[str, type[Provider]]] = {
    "gemini":      ("GEMINI_API_KEY",      GeminiProvider),
    "groq":        ("GROQ_API_KEY",        GroqProvider),
    "mistral":     ("MISTRAL_API_KEY",     MistralProvider),
    "openrouter":  ("OPENROUTER_API_KEY",  OpenRouterProvider),
}

# Task-based routing: ordered preference per task type.
#   "review"  — fast inference preferred (ranking 60 candidates quickly)
#   "write"   — high quality preferred (newsletter prose)
ROUTES: dict[str, list[str]] = {
    "review": ["groq", "gemini", "mistral", "openrouter"],
    "write":  ["gemini", "groq", "mistral", "openrouter"],
}


class ProviderRouter:
    """Routes LLM calls across multiple providers with fallback on failure.

    * Initialises only providers whose API keys are present in the environment.
    * Uses task-based routing (``ROUTES``) to pick the primary provider.
    * Falls back through the chain on ANY provider failure (rate limit, timeout, error).
    * Each provider tracks its own pacing independently — no wasted delay
      when switching providers.
    """

    def __init__(self, log: Callable):
        self.log = log
        self.providers: dict[str, Provider] = {}
        self.disabled: set[str] = set()
        self.models_used: list[str] = []
        self.attempts = 0

        for key, (env_var, cls) in _PROVIDER_KEYS.items():
            if os.getenv(env_var):
                try:
                    self.providers[key] = cls()
                    log("collect", f"{cls.__name__[:-8]} provider ready",
                        f"Model: {self.providers[key].model}")
                except Exception:
                    log("warning", f"{cls.__name__[:-8]} init failed",
                        "Provider could not be initialised; check configuration. Skipping it.")

        if not self.providers:
            raise RuntimeError(
                "No LLM provider configured. "
                "Set at least one API key (GEMINI / GROQ / MISTRAL / OPENROUTER) in .env."
            )

        configured = ", ".join(p.name for p in self.providers.values())
        log("collect", f"{len(self.providers)} providers configured", configured)

    def ask(self, prompt: str, schema: type[BaseModel], task: str = "write") -> BaseModel:
        """Call the best available provider for *task*, falling back on errors."""
        route = ROUTES.get(task, ROUTES["write"])
        # Only include providers that are actually configured and not disabled.
        chain = [r for r in route if r in self.providers and r not in self.disabled]
        chain = [key for key in chain if _COOLDOWNS.get(key, 0) <= time.monotonic()]
        if not chain:
            raise ProviderUnavailable("All configured providers are unavailable. Open the saved demo or try again later.")
        for provider_key in chain:
            if self.attempts >= MAX_ATTEMPTS:
                raise ProviderUnavailable("The request budget was reached. Your saved briefing remains available.")
            provider = self.providers[provider_key]
            self.log("checkpoint", "", "")
            self.attempts += 1
            try:
                result = provider.call(prompt, schema, self.log)
                if provider.name not in self.models_used:
                    self.models_used.append(provider.name)
                return result
            except InterruptedError:
                raise
            except Exception as exc:
                kind = failure_kind(exc)
                self.disabled.add(provider_key)
                # Persist a cooldown across runs; never retry an exhausted provider in this run.
                _COOLDOWNS[provider_key] = time.monotonic() + (300 if kind == "rate limit" else 60)
                self.log("warning", f"{provider.name}: {kind}",
                         "Trying another configured provider. Saved briefings remain available.")
        raise ProviderUnavailable("Live providers are unavailable. Your saved briefing is preserved; open the saved demo.")

    def close(self):
        """Release resources for all initialised providers."""
        for provider in self.providers.values():
            try:
                provider.close()
            except Exception:
                pass

