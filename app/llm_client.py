"""OpenAI-compatible LLM client with retry, JSON parsing, and logging."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Type, TypeVar

import httpx
import openai
from openai import OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .schemas.module_log import ModuleCallLog
from .utils.hashing import hash_packet
from .utils.io_utils import append_jsonl
from .utils.json_utils import strip_code_fences

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when LLM call fails after retries."""

    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type


class LLMClient:
    """Wrapper around an OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        log_path: str | Path | None = None,
    ):
        self.default_model = default_model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        self.log_path = Path(log_path) if log_path else None

        resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_api_key:
            raise ValueError("Set OPENAI_API_KEY before using LLMClient.")

        resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        client_kwargs: dict[str, Any] = {
            "api_key": resolved_api_key,
            "timeout": httpx.Timeout(300.0, connect=30.0),
            "max_retries": 0,
            "http_client": httpx.Client(
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30,
                ),
                timeout=httpx.Timeout(300.0, connect=30.0),
            ),
        }
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url

        self.client = OpenAI(**client_kwargs)
        logger.info(
            "Using OpenAI-compatible backend: %s",
            resolved_base_url or "OpenAI default endpoint",
        )

    def _log_call(self, log: ModuleCallLog) -> None:
        """Persist a module call log entry."""
        if self.log_path:
            append_jsonl(log, self.log_path)
        logger.info(
            "LLM call: module=%s model=%s status=%s time=%.2fs",
            log.module, log.model, log.status, log.timing_sec,
        )

    @staticmethod
    def _redact_image_data(messages: list[dict]) -> list[dict]:
        """Redact base64 image data from messages to keep logs small.

        Replaces 'data:image/...' URLs with a placeholder while keeping
        http(s) URLs intact so file paths are still visible.
        """
        import copy
        redacted = copy.deepcopy(messages)
        for msg in redacted:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            part["image_url"]["url"] = f"[base64 image, {len(url)} chars]"
        return redacted

    @retry(
        retry=retry_if_exception_type((TimeoutError, ConnectionError, openai.APIConnectionError, openai.APITimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
    )
    def _call_chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
        reasoning_effort: str | None = None,
        _rate_limit_retries: int = 0,
    ) -> dict:
        """Make a raw chat completion call with retry.

        Args:
            reasoning_effort: If set ("low", "medium", "high"), enables
                model-side chain-of-thought reasoning.  temperature is
                forced to 1 (the only value the API accepts in reasoning
                mode).
        """
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["temperature"] = 1  # required by reasoning mode
        else:
            kwargs["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**kwargs)
        except openai.RateLimitError as e:
            # Handle 429 with smart wait based on retry-after header
            if _rate_limit_retries >= 5:
                raise  # give up after 5 rate-limit retries
            retry_after = 60  # default wait
            if hasattr(e, 'response') and e.response is not None:
                ra = e.response.headers.get('retry-after')
                if ra:
                    try:
                        retry_after = min(int(ra), 120)
                    except ValueError:
                        pass
                # Also check reset-tokens header
                reset_tokens = e.response.headers.get('x-ratelimit-reset-tokens')
                if reset_tokens:
                    try:
                        retry_after = max(retry_after, min(int(reset_tokens), 120))
                    except ValueError:
                        pass
            logger.info("Rate limited (429), waiting %ds before retry (%d/5)...",
                       retry_after, _rate_limit_retries + 1)
            time.sleep(retry_after)
            return self._call_chat(model, messages, max_tokens, temperature,
                                   reasoning_effort=reasoning_effort,
                                   _rate_limit_retries=_rate_limit_retries + 1)

        choice = response.choices[0]
        content = choice.message.content or ""

        usage: dict = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Capture reasoning tokens when available
            if hasattr(response.usage, "completion_tokens_details") and response.usage.completion_tokens_details:
                details = response.usage.completion_tokens_details
                if hasattr(details, "reasoning_tokens") and details.reasoning_tokens:
                    usage["reasoning_tokens"] = details.reasoning_tokens
            # Capture prompt caching stats when the provider reports them
            if hasattr(response.usage, "prompt_tokens_details") and response.usage.prompt_tokens_details:
                ptd = response.usage.prompt_tokens_details
                if hasattr(ptd, "cached_tokens") and ptd.cached_tokens:
                    usage["cached_tokens"] = ptd.cached_tokens
                    logger.debug("Prompt cache hit: %d/%d tokens cached (%.0f%%)",
                                 ptd.cached_tokens, response.usage.prompt_tokens,
                                 100 * ptd.cached_tokens / max(response.usage.prompt_tokens, 1))

        return {"content": content, "usage": usage}

    def call_text(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        module_name: str = "unknown",
        prompt_version: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        input_packet: Any = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """Make a text-only LLM call. Returns raw string content."""
        model = model or self.default_model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        start = time.time()
        try:
            result = self._call_chat(model, messages, max_tokens, temperature,
                                     reasoning_effort=reasoning_effort)
            elapsed = time.time() - start
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash=hash_packet(input_packet) if input_packet else "",
                status="ok",
                timing_sec=elapsed,
                token_usage=result["usage"],
                messages=messages,
                response_text=result["content"],
            ))
            return result["content"]
        except Exception as e:
            elapsed = time.time() - start
            error_type = _classify_error(e)
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash=hash_packet(input_packet) if input_packet else "",
                status="error",
                error_type=error_type,
                error_message=str(e),
                timing_sec=elapsed,
                messages=messages,
                response_text="",
            ))
            raise LLMError(str(e), error_type) from e

    def call_vision(
        self,
        system_prompt: str,
        text_content: str,
        image_urls: list[str],
        model: str | None = None,
        module_name: str = "unknown",
        prompt_version: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        input_packet: Any = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """Make a vision LLM call with text + images. Returns raw string content."""
        model = model or self.default_model

        user_content: list[dict] = [{"type": "text", "text": text_content}]
        for url in image_urls:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        start = time.time()
        try:
            result = self._call_chat(model, messages, max_tokens, temperature,
                                     reasoning_effort=reasoning_effort)
            elapsed = time.time() - start
            # For vision calls, redact base64 image data to keep log size manageable
            log_messages = self._redact_image_data(messages)
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash=hash_packet(input_packet) if input_packet else "",
                status="ok",
                timing_sec=elapsed,
                token_usage=result["usage"],
                messages=log_messages,
                response_text=result["content"],
            ))
            return result["content"]
        except Exception as e:
            elapsed = time.time() - start
            error_type = _classify_error(e)
            log_messages = self._redact_image_data(messages)
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash=hash_packet(input_packet) if input_packet else "",
                status="error",
                error_type=error_type,
                error_message=str(e),
                timing_sec=elapsed,
                messages=log_messages,
                response_text="",
            ))
            raise LLMError(str(e), error_type) from e

    def call_multiturn(
        self,
        messages: list[dict],
        model: str | None = None,
        module_name: str = "unknown",
        prompt_version: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        reasoning_effort: str | None = None,
    ) -> str:
        """Make a multi-turn chat call with pre-built message list.

        Unlike call_text() which only takes system+user, this accepts an
        arbitrary messages list (system, user, assistant, user, ...) for
        multi-turn conversations like agent loops.
        """
        model = model or self.default_model
        start = time.time()
        try:
            result = self._call_chat(model, messages, max_tokens, temperature,
                                     reasoning_effort=reasoning_effort)
            elapsed = time.time() - start
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash="",
                status="ok",
                timing_sec=elapsed,
                token_usage=result["usage"],
                messages=self._redact_image_data(messages),
                response_text=result["content"],
            ))
            return result["content"]
        except Exception as e:
            elapsed = time.time() - start
            error_type = _classify_error(e)
            self._log_call(ModuleCallLog(
                module=module_name,
                prompt_version=prompt_version,
                model=model,
                input_packet_hash="",
                status="error",
                error_type=error_type,
                error_message=str(e),
                timing_sec=elapsed,
                messages=self._redact_image_data(messages),
                response_text="",
            ))
            raise LLMError(str(e), error_type) from e

    def call_json(
        self,
        system_prompt: str,
        user_content: str,
        response_model: Type[T],
        model: str | None = None,
        module_name: str = "unknown",
        prompt_version: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        input_packet: Any = None,
        reasoning_effort: str | None = None,
    ) -> T:
        """Make a text LLM call and parse response as a Pydantic model."""
        last_err: Exception | None = None
        for attempt in range(3):
            raw = self.call_text(
                system_prompt=system_prompt,
                user_content=user_content if attempt == 0 else (
                    user_content
                    + f"\n\n[RETRY {attempt}: previous response failed schema validation: "
                    + str(last_err)[:300]
                    + f". Return STRICT JSON matching {response_model.__name__} with ALL required fields.]"
                ),
                model=model,
                module_name=module_name,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
                temperature=temperature,
                input_packet=input_packet,
                reasoning_effort=reasoning_effort,
            )
            try:
                return _parse_json_response(raw, response_model)
            except LLMError as e:
                if e.error_type != "schema_validation_error":
                    raise
                last_err = e
        assert last_err is not None
        raise last_err

    def call_vision_json(
        self,
        system_prompt: str,
        text_content: str,
        image_urls: list[str],
        response_model: Type[T],
        model: str | None = None,
        module_name: str = "unknown",
        prompt_version: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        input_packet: Any = None,
        reasoning_effort: str | None = None,
    ) -> T:
        """Make a vision LLM call and parse response as a Pydantic model."""
        raw = self.call_vision(
            system_prompt=system_prompt,
            text_content=text_content,
            image_urls=image_urls,
            model=model,
            module_name=module_name,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            temperature=temperature,
            input_packet=input_packet,
            reasoning_effort=reasoning_effort,
        )
        return _parse_json_response(raw, response_model)


def _parse_json_response(raw: str, model_class: Type[T]) -> T:
    """Parse LLM response as JSON and validate against Pydantic model."""
    # Strip markdown code fences if present
    text = strip_code_fences(raw)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(
            f"Failed to parse LLM response as JSON: {e}\nRaw: {text[:500]}",
            "json_parse_error",
        ) from e

    try:
        return model_class.model_validate(data)
    except Exception as e:
        raise LLMError(
            f"JSON schema validation failed for {model_class.__name__}: {e}",
            "schema_validation_error",
        ) from e


def _classify_error(e: Exception) -> str:
    """Classify an exception into an error type string."""
    error_str = str(e).lower()
    if "timeout" in error_str or "408" in error_str:
        return "model_timeout"
    if "429" in error_str or "rate" in error_str:
        return "model_overload"
    if "413" in error_str or "too large" in error_str:
        return "packet_too_large"
    if "401" in error_str or "403" in error_str or "auth" in error_str:
        return "auth_error"
    if "connection" in error_str:
        return "connection_error"
    return "unknown"
