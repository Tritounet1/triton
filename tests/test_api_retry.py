"""call_chat/stream_chat used to have no retry at all around the network
call: a transient failure (rate limit, a brief provider outage, a dropped
connection) failed the whole turn outright instead of trying again - see
PLAN.md's "Retry/backoff sur les appels LLM" entry. _with_retry is the
single place that now handles this, used by both. No real network call
here: httpx2.Request/Response (the openai SDK's own vendored httpx major
version - a separate package from the plain httpx used elsewhere in this
repo, e.g. by tavily-python) are only used to build the exception objects
the SDK itself requires, never actually sent anywhere."""

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)

from triton.llm import api

_REQUEST = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code=status_code, request=_REQUEST)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Every test below deliberately exhausts or nears MAX_RETRIES, which
    would otherwise really sleep for several seconds (1s + 2s + 4s) - not
    what's being tested here, just noise."""
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)


# --- is_transient_error ---


@pytest.mark.parametrize(
    "exc",
    [
        APIConnectionError(request=_REQUEST),
        APITimeoutError(request=_REQUEST),
        RateLimitError("rate limited", response=_response(429), body=None),
        InternalServerError("server error", response=_response(500), body=None),
        InternalServerError("bad gateway", response=_response(502), body=None),
    ],
)
def test_transient_errors_are_recognized(exc):
    assert api.is_transient_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        AuthenticationError("invalid api key", response=_response(401), body=None),
        ValueError("not even an API error"),
    ],
)
def test_non_transient_errors_are_not_retried(exc):
    assert api.is_transient_error(exc) is False


def test_a_bare_apierror_is_treated_as_transient():
    """Real, repeated case: message "The operation was aborted", no HTTP
    status at all. The SDK raises this exact class (not one of the
    subclasses above) only when it finds an inline {"error": ...} object
    embedded inside an otherwise-200 SSE stream - see
    openai._streaming.Stream.__stream__ - the provider aborting
    generation mid-response with nothing at the HTTP level to signal it.
    Missed by the original isinstance checks above (none of them match
    the bare base class), which is exactly why this kept surfacing
    unretried even after _with_retry/stream_chat's own retry loop existed."""
    exc = APIError("The operation was aborted", request=_REQUEST, body=None)
    assert type(exc) is APIError
    assert api.is_transient_error(exc) is True


def test_a_named_apierror_subclass_is_not_swallowed_by_the_bare_check():
    """type(exc) is APIError must stay an exact-type check, not
    isinstance - every named failure (bad request, auth, not found...)
    is itself a subclass of APIError, and none of those should suddenly
    become "transient" just because they inherit from it."""
    exc = AuthenticationError("invalid api key", response=_response(401), body=None)
    assert isinstance(exc, APIError)
    assert type(exc) is not APIError
    assert api.is_transient_error(exc) is False


# --- _with_retry ---


def test_with_retry_succeeds_on_the_first_try():
    calls = []

    def make_request():
        calls.append(1)
        return "ok"

    assert api._with_retry(make_request) == "ok"
    assert len(calls) == 1


def test_with_retry_retries_a_transient_error_then_succeeds():
    attempts = []

    def make_request():
        attempts.append(1)
        if len(attempts) < 3:
            raise RateLimitError("rate limited", response=_response(429), body=None)
        return "ok"

    assert api._with_retry(make_request) == "ok"
    assert len(attempts) == 3


def test_with_retry_gives_up_after_max_retries():
    attempts = []

    def make_request():
        attempts.append(1)
        raise InternalServerError("still down", response=_response(500), body=None)

    with pytest.raises(InternalServerError):
        api._with_retry(make_request)

    # the first attempt plus MAX_RETRIES retries, never more
    assert len(attempts) == api.MAX_RETRIES + 1


def test_with_retry_never_retries_a_non_transient_error():
    attempts = []

    def make_request():
        attempts.append(1)
        raise AuthenticationError("invalid api key", response=_response(401), body=None)

    with pytest.raises(AuthenticationError):
        api._with_retry(make_request)

    assert len(attempts) == 1


def test_with_retry_backs_off_exponentially(monkeypatch):
    delays = []
    monkeypatch.setattr(api.time, "sleep", lambda seconds: delays.append(seconds))

    attempts = []

    def make_request():
        attempts.append(1)
        if len(attempts) <= api.MAX_RETRIES:
            raise APIConnectionError(request=_REQUEST)
        return "ok"

    api._with_retry(make_request)

    assert delays == [api.RETRY_BASE_DELAY_SECONDS * 2**i for i in range(api.MAX_RETRIES)]


# --- call_chat/stream_chat actually go through _with_retry ---


def test_call_chat_retries_a_transient_failure(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(api, "get_model", lambda: "test-model")

    def _usage():
        return SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)

    def _response_obj():
        message = SimpleNamespace(content="ok", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=_usage(), model="test-model")

    calls = []

    def fake_create(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError("rate limited", response=_response(429), body=None)
        return _response_obj()

    monkeypatch.setattr(
        api,
        "_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )

    result = api.call_chat([{"role": "user", "content": "hi"}])

    assert len(calls) == 2
    assert result.content == "ok"
