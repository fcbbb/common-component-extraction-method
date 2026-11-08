"""Exercise bounded single-response calls with an injected SDK-compatible fake."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from component_method.model_runtime import (
    ModelClient,
    ModelValidationError,
    validate_leakage_decision,
)


def _usage(prompt=11, completion=4):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _response(content, *, usage=None, index=1):
    return SimpleNamespace(
        id=f"chatcmpl-{index}",
        model="deepseek-v4.1-flash-1017",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=usage,
    )


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class _FakeOpenAI:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self):
        self.closed = True


def _client(responses):
    fake = _FakeOpenAI(responses)
    client = ModelClient(
        api_key="fixture-key",
        base_url="https://example.invalid/v1",
        model="openai/deepseek-v4.1-flash-1017",
        timeout_seconds=10,
        transport_retries=0,
        max_output_tokens=512,
        client=fake,
    )
    return client, fake


def test_model_client_records_validated_json_usage_and_identity():
    client, fake = _client(
        [_response('{"decision":"pass","reasons":[]}', usage=_usage())]
    )
    result = client.complete_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Audit fixture."},
        ],
        validator=validate_leakage_decision,
    )

    assert result.value == {"decision": "pass", "reasons": []}
    assert result.model_calls == 1
    assert result.input_tokens == 11
    assert result.output_tokens == 4
    assert result.total_tokens == 15
    assert result.reported_cost_usd is None
    assert result.runtime_identity["request_model"] == "deepseek-v4.1-flash-1017"
    assert "example.invalid" not in result.runtime_identity["base_url_sha256"]
    assert "fixture-key" not in str(result.runtime_identity)
    request = fake.completions.requests[0]
    assert request["model"] == "deepseek-v4.1-flash-1017"
    assert request["max_tokens"] == 512


def test_invalid_json_is_repaired_within_bounded_validation_attempts():
    client, fake = _client(
        [
            _response("not-json", usage=_usage(5, 2), index=1),
            _response(
                'prefix {"decision":"reject","reasons":["task quote"]}',
                usage=_usage(8, 3),
                index=2,
            ),
        ]
    )
    result = client.complete_json(
        [{"role": "user", "content": "Audit fixture."}],
        validator=validate_leakage_decision,
        max_validation_attempts=2,
    )

    assert result.value["decision"] == "reject"
    assert result.model_calls == 2
    assert result.input_tokens == 13
    assert result.output_tokens == 5
    assert result.total_tokens == 18
    assert result.attempts[0]["validation_error"] == "model response contains no JSON object"
    assert result.attempts[1]["validation_error"] is None
    assert len(fake.completions.requests) == 2
    assert "failed JSON validation" in fake.completions.requests[1]["messages"][-1]["content"]


def test_validation_retry_limit_is_enforced_and_usage_is_retained():
    client, fake = _client(
        [
            _response('{"decision":"maybe","reasons":[]}', usage=_usage(3, 1), index=1),
            _response('{"decision":"pass"}', usage=_usage(4, 2), index=2),
        ]
    )
    with pytest.raises(ModelValidationError) as raised:
        client.complete_json(
            [{"role": "user", "content": "Audit fixture."}],
            validator=validate_leakage_decision,
            max_validation_attempts=2,
        )

    assert len(fake.completions.requests) == 2
    assert len(raised.value.attempts) == 2
    assert raised.value.input_tokens == 7
    assert raised.value.output_tokens == 3
    assert raised.value.total_tokens == 10


def test_missing_provider_usage_remains_unknown():
    client, _ = _client([_response('{"decision":"pass","reasons":[]}')])
    result = client.complete_json(
        [{"role": "user", "content": "Audit fixture."}],
        validator=validate_leakage_decision,
    )

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.total_tokens is None


def test_injected_client_is_not_closed_by_model_client():
    client, fake = _client([_response('{"decision":"pass","reasons":[]}')])
    client.close()
    assert fake.closed is False


def test_leakage_validator_rejects_unstructured_or_incomplete_decisions():
    with pytest.raises(ValueError, match="exactly"):
        validate_leakage_decision({"decision": "pass", "reasons": [], "extra": True})
    with pytest.raises(ValueError, match="at least one"):
        validate_leakage_decision({"decision": "reject", "reasons": []})
