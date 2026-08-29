from concurrent.futures import ThreadPoolExecutor
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.llm_client import (
    AZURE_DEFAULT_API_VERSION,
    AZURE_DEFAULT_ENDPOINT,
    LLMClient,
    _parse_json_response,
)
from pydantic import BaseModel


class _TinyJsonModel(BaseModel):
    name: str
    value: int


def _fake_jwt() -> str:
    return "x.eyJleHAiOjk5OTk5OTk5OTl9.x"


def _clear_api_env(monkeypatch):
    for name in (
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "AZURE_ENDPOINT",
        "AZURE_API_BASE",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_API_VERSION",
        "AZURE_API_KEY",
        "REDECK_AZURE_AUTH",
    ):
        monkeypatch.delenv(name, raising=False)

    class FakeCredential:
        def get_token(self, scope):
            return SimpleNamespace(token=_fake_jwt())

    monkeypatch.setattr("app.llm_client.AzureCliCredential", FakeCredential)
    monkeypatch.setattr("app.llm_client.ManagedIdentityCredential", lambda client_id: FakeCredential())


def test_azure_model_routes_follow_available_api(monkeypatch):
    _clear_api_env(monkeypatch)
    client = LLMClient()

    assert client._resolve_azure_route("gpt-5.4") == (
        "https://your-resource.openai.azure.com/",
        "2024-12-01-preview",
    )
    assert client._resolve_azure_route("gpt-5.4-mini") == (
        "https://your-resource.openai.azure.com/",
        "2024-12-01-preview",
    )
    assert client._resolve_azure_route("unknown-deployment") == (
        AZURE_DEFAULT_ENDPOINT,
        AZURE_DEFAULT_API_VERSION,
    )


def test_explicit_azure_endpoint_overrides_model_route(monkeypatch):
    _clear_api_env(monkeypatch)
    monkeypatch.setenv("AZURE_API_BASE", "https://your-resource.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2025-03-01-preview")

    client = LLMClient()

    assert client._resolve_azure_route("gpt-5.4-mini") == (
        "https://your-resource.openai.azure.com/",
        "2025-03-01-preview",
    )


def test_managed_identity_is_default_even_if_azure_api_key_env_exists(monkeypatch):
    _clear_api_env(monkeypatch)
    monkeypatch.setenv("AZURE_API_KEY", "stale-or-litellm-token")

    client = LLMClient()

    assert client._using_managed_identity is True
    assert client._azure_auth_kwargs == {"azure_ad_token": _fake_jwt()}


def test_api_key_auth_can_be_requested_explicitly(monkeypatch):
    _clear_api_env(monkeypatch)
    monkeypatch.setenv("AZURE_API_KEY", "real-key")
    monkeypatch.setenv("REDECK_AZURE_AUTH", "api_key")

    client = LLMClient()

    assert client._using_managed_identity is False
    assert client._azure_auth_kwargs == {"api_key": "real-key"}


def test_azure_client_cache_is_thread_safe_during_token_refresh(monkeypatch):
    _clear_api_env(monkeypatch)
    created = []

    class FakeAzureClient:
        def __init__(self, **kwargs):
            time.sleep(0.01)
            self.kwargs = kwargs
            created.append(self)

        def close(self):
            pass

    monkeypatch.setattr("app.llm_client.AzureOpenAI", FakeAzureClient)
    client = LLMClient()
    client._azure_token_expires_at = 0

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(
            lambda _: client._get_azure_client(
                "https://second-endpoint.openai.azure.com/",
                "2024-12-01-preview",
            ),
            range(24),
        ))

    assert len({id(result) for result in results}) == 1
    assert len(created) == 2  # default route plus one cached second route
    assert results[0].kwargs["azure_ad_token"] == _fake_jwt()


def test_json_parser_repairs_missing_final_container():
    parsed = _parse_json_response('{"name": "planner", "value": 18', _TinyJsonModel)

    assert parsed.name == "planner"
    assert parsed.value == 18


def test_call_json_retries_after_parse_error(monkeypatch):
    _clear_api_env(monkeypatch)
    client = LLMClient()
    responses = iter([
        '{"name": "planner", "value": ',
        '{"name": "planner", "value": 18}',
    ])

    monkeypatch.setattr(client, "call_text", lambda **kwargs: next(responses))

    parsed = client.call_json(
        system_prompt="Return JSON.",
        user_content="{}",
        response_model=_TinyJsonModel,
        model="gpt-5.4",
    )

    assert parsed.value == 18


def test_text_call_retries_successful_empty_response(monkeypatch):
    _clear_api_env(monkeypatch)
    client = LLMClient()
    monkeypatch.setattr(
        client,
        "_call_chat",
        MagicMock(side_effect=[
            {"content": "", "usage": {}},
            {"content": '{"issues": []}', "usage": {}},
        ]),
    )

    result = client.call_text(
        system_prompt="Return JSON.",
        user_content="Check this.",
        max_tokens=4096,
    )

    assert result == '{"issues": []}'
    assert client._call_chat.call_count == 2
    assert client._call_chat.call_args_list[1].args[2] == 8192


def _fake_completion(content="OK"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )


def test_openai_compat_chat_uses_standard_max_tokens():
    client = object.__new__(LLMClient)
    client._backend = "openai_compat"
    client.client = MagicMock()
    client.client.chat.completions.create.return_value = _fake_completion()

    result = client._call_chat("gpt-5-mini", [{"role": "user", "content": "Hi"}], 1234)

    kwargs = client.client.chat.completions.create.call_args.kwargs
    assert result["content"] == "OK"
    assert kwargs["max_tokens"] == 1234
    assert "max_completion_tokens" not in kwargs


def test_azure_chat_keeps_max_completion_tokens():
    client = object.__new__(LLMClient)
    client._backend = "azure"
    client.client = MagicMock()
    azure_client = MagicMock()
    azure_client.chat.completions.create.return_value = _fake_completion()
    client._resolve_azure_route = MagicMock(
        return_value=(AZURE_DEFAULT_ENDPOINT, AZURE_DEFAULT_API_VERSION)
    )
    client._get_azure_client = MagicMock(return_value=azure_client)

    result = client._call_chat("gpt-5.5", [{"role": "user", "content": "Hi"}], 1234)

    kwargs = azure_client.chat.completions.create.call_args.kwargs
    assert result["content"] == "OK"
    assert kwargs["max_completion_tokens"] == 1234
    assert "max_tokens" not in kwargs
