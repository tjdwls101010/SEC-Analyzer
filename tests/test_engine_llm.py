from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIStatusError
from pydantic import BaseModel, Field

from sec_analyzer import engine
from sec_analyzer.presets import SupplyChain


class FakeFiling:
    def __init__(self, markdown: str = "filing markdown") -> None:
        self._markdown = markdown

    def markdown(self) -> str:
        return self._markdown


@pytest.fixture(autouse=True)
def clean_openrouter_env(monkeypatch):
    for name in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(engine, "_sleep_before_retry", lambda attempt: None)


def _patch_filing(
    monkeypatch,
    *,
    markdown: str = "filing markdown",
    company_name: str = "NVIDIA Corporation",
):
    metadata = {
        "form": "10-K",
        "filing_date": "2026-02-25",
        "accession_number": "0001045810-26-000021",
        "filing_url": "https://www.sec.gov/Archives/example",
    }
    get_filing = MagicMock(
        return_value=(FakeFiling(markdown), metadata, company_name)
    )
    monkeypatch.setattr(engine, "_get_filing", get_filing)
    return get_filing, metadata


def _llm_response(content: str | None, *, refusal: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, refusal=refusal)
            )
        ]
    )


def _patch_openai(monkeypatch, side_effects):
    create = MagicMock(side_effect=side_effects)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    constructor = MagicMock(return_value=client)

    import openai

    monkeypatch.setattr(openai, "OpenAI", constructor)
    return constructor, create


def _valid_supply_chain_json() -> str:
    return json.dumps(
        {
            "suppliers": [
                {
                    "entity": "Taiwan Semiconductor Manufacturing Company",
                    "relationship": "foundry supplier",
                    "context": "The filing names TSMC as a foundry supplier.",
                }
            ]
        }
    )


def _api_status_error(reason: str, status_code: int = 402) -> APIStatusError:
    request = httpx.Request(
        "POST", "https://openrouter.ai/api/v1/chat/completions"
    )
    response = httpx.Response(status_code, request=request)
    return APIStatusError(
        f"Error code: {status_code}",
        response=response,
        body={"error": {"message": reason}},
    )


def test_missing_openrouter_key_raises_before_provider_request(monkeypatch):
    import openai

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    constructor = MagicMock()
    monkeypatch.setattr(openai, "OpenAI", constructor)
    get_filing = MagicMock()
    monkeypatch.setattr(engine, "_get_filing", get_filing)

    with pytest.raises(ValueError) as exc_info:
        engine.extract("NVDA", SupplyChain)

    message = str(exc_info.value)
    assert "OPENROUTER_API_KEY" in message
    assert "GOOGLE_" not in message
    constructor.assert_not_called()
    get_filing.assert_not_called()


def test_provider_api_status_error_reason_is_surfaced(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch)
    reason = "OpenRouter credits are exhausted"
    _, create = _patch_openai(
        monkeypatch, [_api_status_error(reason) for _ in range(3)]
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine.extract("NVDA", SupplyChain)

    assert reason in str(exc_info.value)
    assert create.call_count == 3


def test_empty_content_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch)
    _, create = _patch_openai(
        monkeypatch,
        [_llm_response(None), _llm_response(_valid_supply_chain_json())],
    )

    result = engine.extract("NVDA", SupplyChain)

    assert result["data"]["suppliers"][0]["entity"] == (
        "Taiwan Semiconductor Manufacturing Company"
    )
    assert create.call_count == 2


def test_refusal_is_non_retryable_and_reason_is_surfaced(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch)
    refusal = "I cannot extract this filing."
    _, create = _patch_openai(
        monkeypatch,
        [
            _llm_response(None, refusal=refusal),
            _llm_response(_valid_supply_chain_json()),
        ],
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine.extract("NVDA", SupplyChain)

    assert refusal in str(exc_info.value)
    assert create.call_count == 1


def test_all_empty_content_message_names_attempt_count_and_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch)
    _, create = _patch_openai(
        monkeypatch, [_llm_response(None) for _ in range(3)]
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine.extract("NVDA", SupplyChain, model="test/model")

    message = str(exc_info.value)
    assert "empty content on all 3 attempts" in message
    assert "test/model" in message
    assert create.call_count == 3


def test_validation_error_is_surfaced_after_retries(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch)
    invalid_json = json.dumps(
        {"market_risk_disclosures": [{"risk_type": "not-valid"}]}
    )
    _, create = _patch_openai(
        monkeypatch, [_llm_response(invalid_json) for _ in range(3)]
    )

    with pytest.raises(RuntimeError) as exc_info:
        engine.extract("NVDA", SupplyChain)

    message = str(exc_info.value)
    assert "market_risk_disclosures" in message
    assert "not-valid" in message
    assert create.call_count == 3


def test_request_shape_uses_raw_schema_and_argument_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")
    monkeypatch.setenv("OPENROUTER_MODEL", "ENV_MODEL")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "none")
    filing_text = "NVDA filing text"
    _patch_filing(monkeypatch, markdown=filing_text)
    constructor, create = _patch_openai(
        monkeypatch, [_llm_response(_valid_supply_chain_json())]
    )

    engine.extract(
        "NVDA",
        SupplyChain,
        api_key="ARG_KEY",
        model="ARG_MODEL",
    )

    assert constructor.call_args.kwargs["api_key"] == "ARG_KEY"
    assert constructor.call_args.kwargs["base_url"] == engine._OPENROUTER_BASE_URL
    assert constructor.call_args.kwargs["max_retries"] == 0

    request = create.call_args.kwargs
    assert request["model"] == "ARG_MODEL"
    assert request["temperature"] == 0
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": SupplyChain.__name__,
            "strict": True,
            "schema": SupplyChain.model_json_schema(),
        },
    }
    assert request["messages"] == [
        {
            "role": "user",
            "content": SupplyChain.__prompt__.format(
                company_name="NVIDIA Corporation",
                filing_text=filing_text,
            ),
        }
    ]
    assert "reasoning_effort" not in request
    assert "reasoning" not in request


def test_reasoning_effort_value_is_sent_as_top_level_kwarg(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "high")
    _patch_filing(monkeypatch)
    _, create = _patch_openai(
        monkeypatch, [_llm_response(_valid_supply_chain_json())]
    )

    engine.extract("NVDA", SupplyChain)

    request = create.call_args.kwargs
    assert request["reasoning_effort"] == "high"
    assert "reasoning" not in request


def test_supply_chain_prompt_is_byte_identical_to_old_format(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    filing_text = "Supply chain filing text"
    _patch_filing(
        monkeypatch,
        markdown=filing_text,
        company_name="NVIDIA Corporation",
    )
    _, create = _patch_openai(
        monkeypatch, [_llm_response(_valid_supply_chain_json())]
    )

    engine.extract("NVDA", SupplyChain)

    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert prompt == SupplyChain.__prompt__.format(
        company_name="NVIDIA Corporation",
        filing_text=filing_text,
    )


def test_custom_prompt_literal_braces_and_repeated_placeholders(monkeypatch):
    class CustomPromptPreset(BaseModel):
        __prompt__: ClassVar[str] = (
            'Return JSON like {"x": 1} for {company_name}. '
            "Repeat {company_name}; use text {filing_text}; "
            "repeat text {filing_text}; keep {ticker}; stray { and }."
        )

        items: list[str] = Field(default_factory=list)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    filing_text = "Filing passage with {filing_text} inside the value."
    _patch_filing(monkeypatch, markdown=filing_text, company_name="Acme Inc.")
    _, create = _patch_openai(monkeypatch, [_llm_response(json.dumps({}))])

    engine.extract("ACME", CustomPromptPreset)

    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert '{"x": 1}' in prompt
    assert prompt.count("Acme Inc.") == 2
    assert prompt.count(filing_text) == 2
    assert "{ticker}" in prompt
    assert "stray { and }" in prompt
    assert "inside the value." in prompt


def test_field_description_with_brace_does_not_crash(monkeypatch):
    class DefaultPromptPreset(BaseModel):
        amounts: list[str] = Field(
            default_factory=list,
            description="amounts as JSON {currency: USD}",
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_filing(monkeypatch, markdown="filing text", company_name="Acme Inc.")
    _, create = _patch_openai(monkeypatch, [_llm_response(json.dumps({}))])

    engine.extract("ACME", DefaultPromptPreset)

    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert "amounts as JSON {currency: USD}" in prompt
