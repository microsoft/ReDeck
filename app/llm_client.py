"""LLM Client - Azure OpenAI wrapper with retry, JSON parsing, and logging."""

import base64
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Type, TypeVar

import httpx
import openai
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from openai import AzureOpenAI
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

AZURE_MI_CLIENT_ID = os.environ.get(
    "AZURE_MI_CLIENT_ID", os.environ.get("AZURE_CLIENT_ID", "")
)
AZURE_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"

# Azure OpenAI endpoint routing.
# Override via AZURE_OPENAI_ENDPOINT env var for custom deployments.
AZURE_CHAT_ROUTES: dict[str, tuple[str, str]] = {
    "gpt-5.5": (os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
    "gpt-5.4": (os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
    "gpt-5.4-nano": (os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
    "gpt-5.4-mini": (os.environ.get("AZURE_OPENAI_ENDPOINT_ALT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
    "gpt-4o": (os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
    "gpt-4o-mini": (os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/"), "2024-12-01-preview"),
}

# Optional model name mapping for custom OpenAI-compatible proxies.
# Only applied when OPENAI_BASE_URL contains "trapi".
TRAPI_MODEL_MAP: dict[str, str] = {}

AZURE_DEFAULT_ENDPOINT = os.environ.get(
    "AZURE_OPENAI_ENDPOINT", os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com/")
)
AZURE_DEFAULT_API_VERSION = "2024-12-01-preview"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except ValueError:
        logger.warning("Invalid %s=%r; using %d", name, os.environ.get(name), default)
        return default


class LLMError(Exception):
    """Raised when LLM call fails after retries."""

    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type


class LLMClient:
    """Wrapper around Azure OpenAI for structured LLM calls."""

    def __init__(
        self,
        azure_endpoint: str | None = None,
        api_key: str | None = None,
        api_version: str = AZURE_DEFAULT_API_VERSION,
        default_model: str = "gpt-5.5",
        log_path: str | Path | None = None,
    ):
        self.default_model = default_model
        self.log_path = Path(log_path) if log_path else None
        self._backend = "azure"
        self._azure_client_lock = threading.RLock()
        self._azure_clients: dict[tuple[str, str], AzureOpenAI] = {}
        self._azure_token_expires_at = 0
        self._azure_auth_kwargs: dict = {}
        self._using_managed_identity = False

        # Detect backend: if OPENAI_BASE_URL is set, use plain OpenAI client
        # (for localhost proxies, Claude/Gemini via OpenAI-compat API, etc.)
        openai_base_url = os.environ.get("OPENAI_BASE_URL")
        if openai_base_url:
            self._backend = "openai_compat"
            self.client = openai.OpenAI(
                base_url=openai_base_url,
                api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
                timeout=httpx.Timeout(300.0, connect=30.0),
                max_retries=0,
                http_client=httpx.Client(
                    limits=httpx.Limits(
                        max_connections=10,
                        max_keepalive_connections=5,
                        keepalive_expiry=30,
                    ),
                    timeout=httpx.Timeout(300.0, connect=30.0),
                ),
            )
            logger.info("Using OpenAI-compatible backend: %s", openai_base_url)
        else:
            endpoint_env = (
                os.environ.get("AZURE_ENDPOINT")
                or os.environ.get("AZURE_API_BASE")
                or os.environ.get("AZURE_OPENAI_ENDPOINT")
            )
            api_version_env = os.environ.get("AZURE_API_VERSION")
            self.azure_endpoint = azure_endpoint or endpoint_env
            self.api_version = api_version_env or api_version
            self._force_azure_route = bool(self.azure_endpoint)
            self.api_key = api_key or os.environ.get("AZURE_API_KEY", "")

            self._azure_auth_kwargs = self._build_azure_auth_kwargs(api_key=api_key)
            endpoint, version = self._resolve_azure_route(default_model)
            self.client = self._get_azure_client(endpoint, version)

    @staticmethod
    def _normalize_azure_endpoint(endpoint: str) -> str:
        endpoint = endpoint.strip()
        if endpoint and not endpoint.endswith("/"):
            endpoint += "/"
        return endpoint

    def _build_azure_auth_kwargs(self, api_key: str | None = None) -> dict:
        """Build Azure auth settings.

        Tries AzureCliCredential first, falls back to ManagedIdentityCredential.
        Set REDECK_AZURE_AUTH=api_key to use a static API key instead.
        """
        auth_mode = os.environ.get("REDECK_AZURE_AUTH", "").strip().lower()
        explicit_api_key = api_key is not None
        if explicit_api_key or auth_mode in {"api_key", "key"}:
            key = api_key or os.environ.get("AZURE_API_KEY", "")
            self._using_managed_identity = False
            logger.info("Using API key authentication for Azure OpenAI")
            return {"api_key": key}

        # Try AzureCliCredential first, fall back to ManagedIdentityCredential.
        try:
            credential = AzureCliCredential()
            token = credential.get_token(AZURE_TOKEN_SCOPE).token
            self._azure_token_expires_at = self._jwt_expires_at(token)
            self._using_managed_identity = True
            logger.info("Using AzureCliCredential authentication for Azure OpenAI")
            return {"azure_ad_token": token}
        except Exception as e:
            logger.warning("AzureCliCredential failed (%s), trying ManagedIdentityCredential", e)

        credential = ManagedIdentityCredential(client_id=AZURE_MI_CLIENT_ID)
        token = credential.get_token(AZURE_TOKEN_SCOPE).token
        self._azure_token_expires_at = self._jwt_expires_at(token)
        self._using_managed_identity = True
        logger.info("Using Managed Identity authentication for Azure OpenAI")
        return {"azure_ad_token": token}

    @staticmethod
    def _jwt_expires_at(token: str) -> int:
        try:
            payload_part = token.split(".")[1]
            payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            return int(payload.get("exp", 0))
        except Exception:
            return int(time.time()) + 3300

    def _refresh_azure_auth_if_needed(self, force: bool = False) -> None:
        if not self._using_managed_identity:
            return
        with self._azure_client_lock:
            if not force and time.time() < self._azure_token_expires_at - 300:
                return
            self._refresh_azure_clients()
            self._azure_auth_kwargs = self._build_azure_auth_kwargs()

    def _resolve_azure_route(self, model: str) -> tuple[str, str]:
        """Return the Azure endpoint/api-version pair for a deployment."""
        if self._force_azure_route:
            endpoint = self._normalize_azure_endpoint(self.azure_endpoint or AZURE_DEFAULT_ENDPOINT)
            return endpoint, self.api_version or AZURE_DEFAULT_API_VERSION
        endpoint, version = AZURE_CHAT_ROUTES.get(
            model,
            (AZURE_DEFAULT_ENDPOINT, AZURE_DEFAULT_API_VERSION),
        )
        return endpoint, version

    def _get_azure_client(self, endpoint: str, api_version: str) -> AzureOpenAI:
        with self._azure_client_lock:
            self._refresh_azure_auth_if_needed()
            endpoint = self._normalize_azure_endpoint(endpoint)
            key = (endpoint, api_version)
            cached = self._azure_clients.get(key)
            if cached is not None:
                return cached

            client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                timeout=httpx.Timeout(180.0, connect=30.0),
                max_retries=_env_int("REDECK_AZURE_MAX_RETRIES", 5),
                http_client=httpx.Client(
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=10,
                        keepalive_expiry=30,
                    ),
                    timeout=httpx.Timeout(180.0, connect=30.0),
                ),
                **self._azure_auth_kwargs,
            )
            self._azure_clients[key] = client
            logger.info("Using Azure OpenAI endpoint=%s api_version=%s", endpoint, api_version)
            return client

    def _refresh_azure_clients(self) -> None:
        with self._azure_client_lock:
            clients = list(self._azure_clients.values())
            self._azure_clients.clear()
            for client in clients:
                try:
                    client.close()
                except Exception:
                    pass

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
        _auth_retries: int = 0,
    ) -> dict:
        """Make a raw chat completion call with retry.

        Args:
            reasoning_effort: If set ("low", "medium", "high"), enables
                model-side chain-of-thought reasoning.  temperature is
                forced to 1 (the only value the API accepts in reasoning
                mode).
        """
        kwargs: dict = {
            "model": TRAPI_MODEL_MAP.get(model, model) if self._backend == "openai_compat" and "trapi" in (os.environ.get("OPENAI_BASE_URL") or "").lower() else model,
            "messages": messages,
        }
        token_parameter = (
            "max_completion_tokens"
            if self._backend != "openai_compat" or model.startswith("gpt-5")
            else "max_tokens"
        )
        kwargs[token_parameter] = max_tokens
        # Models that only support temperature=1 (reasoning models and gpt-5.5+)
        _temp1_only_models = {"o3", "o4-mini", "o3-mini", "gpt-5.5"}
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["temperature"] = 1  # required by reasoning mode
        elif model in _temp1_only_models:
            kwargs["temperature"] = 1  # these models only accept temperature=1
        else:
            kwargs["temperature"] = temperature

        try:
            client = self.client
            if self._backend == "azure":
                endpoint, api_version = self._resolve_azure_route(model)
                client = self._get_azure_client(endpoint, api_version)
                self.client = client
            response = client.chat.completions.create(**kwargs)
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
                                   _rate_limit_retries=_rate_limit_retries + 1,
                                   _auth_retries=_auth_retries)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            if self._backend == "azure" and self._using_managed_identity and _auth_retries < 2:
                logger.warning(
                    "Azure authentication failed; refreshing credentials and retrying (%d/2): %s",
                    _auth_retries + 1,
                    str(e)[:240],
                )
                self._refresh_azure_auth_if_needed(force=True)
                time.sleep(2)
                return self._call_chat(
                    model,
                    messages,
                    max_tokens,
                    temperature,
                    reasoning_effort=reasoning_effort,
                    _rate_limit_retries=_rate_limit_retries,
                    _auth_retries=_auth_retries + 1,
                )
            raise

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
            # Capture prompt caching stats (Azure auto-caches shared prefixes)
            if hasattr(response.usage, "prompt_tokens_details") and response.usage.prompt_tokens_details:
                ptd = response.usage.prompt_tokens_details
                if hasattr(ptd, "cached_tokens") and ptd.cached_tokens:
                    usage["cached_tokens"] = ptd.cached_tokens
                    logger.debug("Prompt cache hit: %d/%d tokens cached (%.0f%%)",
                                 ptd.cached_tokens, response.usage.prompt_tokens,
                                 100 * ptd.cached_tokens / max(response.usage.prompt_tokens, 1))

        return {"content": content, "usage": usage}

    def _call_chat_nonempty(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None = None,
    ) -> dict:
        """Retry one successful-but-empty completion with more output budget."""
        result = self._call_chat(
            model, messages, max_tokens, temperature,
            reasoning_effort=reasoning_effort,
        )
        if result["content"].strip():
            return result

        retry_tokens = min(max(max_tokens * 2, 8192), 16384)
        logger.warning(
            "LLM returned an empty response; retrying once with %d completion tokens",
            retry_tokens,
        )
        retry_messages = list(messages) + [{
            "role": "user",
            "content": (
                "The previous completion was empty. Return the requested result "
                "now, preserving the required output format."
            ),
        }]
        result = self._call_chat(
            model, retry_messages, retry_tokens, temperature,
            reasoning_effort=reasoning_effort,
        )
        if not result["content"].strip():
            raise LLMError(
                "Model returned empty content on both attempts",
                "empty_response",
            )
        return result

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
            result = self._call_chat_nonempty(
                model, messages, max_tokens, temperature,
                reasoning_effort=reasoning_effort,
            )
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
            result = self._call_chat_nonempty(
                model, messages, max_tokens, temperature,
                reasoning_effort=reasoning_effort,
            )
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
            result = self._call_chat_nonempty(
                model, messages, max_tokens, temperature,
                reasoning_effort=reasoning_effort,
            )
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
                if e.error_type not in {"schema_validation_error", "json_parse_error"}:
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
        parse_error = e
        for candidate in _json_repair_candidates(text):
            if candidate == text:
                continue
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        else:
            raise LLMError(
                f"Failed to parse LLM response as JSON: {parse_error}\nRaw: {text[:500]}",
                "json_parse_error",
            ) from parse_error

    try:
        return model_class.model_validate(data)
    except Exception as e:
        raise LLMError(
            f"JSON schema validation failed for {model_class.__name__}: {e}",
            "schema_validation_error",
        ) from e


def _json_repair_candidates(text: str) -> list[str]:
    """Return conservative candidates for common LLM JSON wrapper/truncation flaws."""
    bases: list[str] = []
    stripped = text.strip()
    if stripped:
        bases.append(stripped)

    object_pos = stripped.find("{")
    array_pos = stripped.find("[")
    starts = [pos for pos in (object_pos, array_pos) if pos >= 0]
    if starts:
        start = min(starts)
        if start > 0:
            bases.append(stripped[start:])

    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    for base in bases:
        add(base)
        stack, complete_at, in_string = _scan_json_balance(base)
        if complete_at is not None and complete_at + 1 < len(base):
            add(base[: complete_at + 1])
        if stack and not in_string:
            closers = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
            add(base + closers)
    return candidates


def _scan_json_balance(text: str) -> tuple[list[str], int | None, bool]:
    """Track JSON container balance while ignoring braces inside strings."""
    stack: list[str] = []
    in_string = False
    escape = False
    complete_at: int | None = None

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                continue
            opener = stack[-1]
            if (opener == "{" and ch == "}") or (opener == "[" and ch == "]"):
                stack.pop()
                if not stack:
                    complete_at = idx
            else:
                return stack, complete_at, in_string

    return stack, complete_at, in_string


def _classify_error(e: Exception) -> str:
    """Classify an exception into an error type string."""
    if isinstance(e, LLMError):
        return e.error_type
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
