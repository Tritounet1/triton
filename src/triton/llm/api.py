import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import cast

import requests
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionToolParam,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from triton.paths import ROOT_DIR
from triton.storage.settings import load_image_model, load_model, load_openrouter_api_key

# explicit path rather than load_dotenv()'s default CWD-upward search: once
# frozen (PyInstaller), the process's CWD has nothing to do with ROOT_DIR
# (see paths.py), so the default search would silently find nothing.
_ = load_dotenv(ROOT_DIR / ".env")


def _effective_api_key() -> str | None:
    """The Settings UI's value (settings.json) takes priority when set, so
    entering a key there takes effect immediately, no restart needed -
    falls back to the OPEN_ROUTER_API_KEY env var (.env) for the existing
    dev/CLI setup."""
    return load_openrouter_api_key() or os.getenv("OPEN_ROUTER_API_KEY")


def is_api_key_configured() -> bool:
    return _effective_api_key() is not None


def _client() -> OpenAI:
    # built fresh on every call (like get_model()) rather than once at
    # import time, so a key entered through the Settings UI takes effect
    # on the very next call. The OpenAI SDK raises at construction time if
    # api_key is None - the placeholder defers that failure to the actual
    # request instead, which already surfaces as a normal error through
    # the existing chat error handling (is_api_key_configured() is what
    # run_chat_stream checks upfront to show a clearer message before ever
    # getting here).
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_effective_api_key() or "not-configured",
        # the SDK's own default (2, silent, not logged) is disabled in
        # favor of the single explicit retry layer below (_with_retry) -
        # two uncoordinated retry loops stacked on top of each other would
        # make the real number of attempts, and the total wait time before
        # a failure actually surfaces, unpredictable.
        max_retries=0,
        # Without an explicit SDK timeout, an unresponsive upstream could
        # keep an SSE/chat request (or a scheduled task draining it) stuck
        # for the HTTP client's much longer default. `_with_retry` handles
        # the resulting APITimeoutError with the one retry policy below.
        timeout=OPENROUTER_REQUEST_TIMEOUT_SECONDS,
    )


# how many times a call gets retried after a manifestly transient failure
# (network error, rate limit, 5xx) before giving up and letting it raise -
# see call_chat (below MAX_TOKENS) - both a bit deep to read at a glance
# here, but immediately obvious once TOKENS or RETRIES is the search term.
MAX_RETRIES = 3
# doubles each attempt: 1s, 2s, 4s - generous enough to ride out a brief
# rate-limit window without the client feeling stuck for tens of seconds.
RETRY_BASE_DELAY_SECONDS = 1.0
# Bounded per attempt, including stream establishment and an idle response
# read. A provider that continues to stream tokens is not interrupted; a
# completely stalled connection is retried then surfaced as an error.
OPENROUTER_REQUEST_TIMEOUT_SECONDS = 60.0


def is_transient_error(exc: Exception) -> bool:
    """A connection failure, timeout, or rate limit is always worth
    retrying; a 5xx from the provider usually is too (its own problem, not
    this request's). Anything else - a bad request, an unknown model, an
    invalid API key - retrying would just get the exact same rejection
    again, so it's left to raise immediately instead of wasting the retry
    budget and the wait. Not private (no leading underscore): reused by
    stream_chat's own retry-if-nothing-produced-yet loop below, and by
    server.py's run_chat_stream to decide whether an error that reached it
    uncaught was even worth retrying in the first place, for its own
    diagnostics.

    A bare APIError (exact type, not one of the subclasses checked below)
    is also treated as transient: found via a real, repeated case -
    message "The operation was aborted", no HTTP status at all. The SDK
    raises this exact class (openai._streaming.Stream.__stream__) only
    when it finds an inline {"error": ...} object embedded inside an
    otherwise-200 SSE stream - the provider aborting generation
    mid-response with no HTTP-level status to signal it, distinct from
    every named failure mode (bad request, auth, not found...), which all
    arrive as a more specific subclass via the normal HTTP-status path
    instead and are correctly left alone below."""
    if isinstance(exc, APIConnectionError | APITimeoutError | RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return type(exc) is APIError


def _with_retry[T](make_request: Callable[[], T]) -> T:
    """Calls make_request(), retrying with exponential backoff on a
    manifestly transient error - see is_transient_error. Used for both
    call_chat and the call that establishes stream_chat's stream: in both
    cases nothing has reached the caller yet at the point this runs, so a
    retry from scratch is always safe. NOT used directly once a streamed
    response has actually started yielding content - see stream_chat's own
    retry loop below for that finer-grained case."""
    attempt = 0
    while True:
        try:
            return make_request()
        except Exception as exc:
            attempt += 1
            if attempt > MAX_RETRIES or not is_transient_error(exc):
                raise
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))


# 1024 was too low for tool calls carrying a full file as their "content"
# argument (e.g. write_file on an HTML page with inline CSS): the completion
# got truncated mid-JSON, the tool call became unparseable, and the model
# burned iterations retrying increasingly convoluted workarounds instead.
# 8192 later proved too low too, for a different reason: reasoning models
# (e.g. gemini-3.7-flash) count hidden "reasoning" tokens against the same
# budget, and can burn through all of it before producing any visible
# content or tool call at all (see run_chat_stream's handling of
# finish_reason == "length" for what happens when that still occurs).
MAX_TOKENS = 16384


def get_model() -> str:
    """Reads the currently selected model fresh from settings.json on every
    call (like mcp_client.load_configs(), projects.load_projects()...), so
    a change made in the desktop app's Settings takes effect immediately,
    no restart needed."""
    return load_model()


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ChatCompletionMessageToolCallUnion]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # "length" means max_tokens was hit before the model produced any
    # content or tool call - distinguishing this from a genuinely empty
    # response matters because it's recoverable (see run_chat_stream):
    # reasoning models can burn their entire budget on hidden reasoning
    # tokens with nothing left over for visible output.
    finish_reason: str | None = None


@dataclass
class ImageGenerationResult:
    """A generated image encoded as a data URL, ready for the desktop UI.

    The history deliberately stores a data URL instead of a transient
    provider URL: it keeps an image visible after restart and avoids making
    old conversations depend on an expiring OpenRouter asset.
    """

    images: list[str]
    model: str


def _provider_messages(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    """Drops Triton's display-only metadata before calling OpenRouter.

    Session history records the producing model and generated images so the
    UI can show the right avatar. Those are not OpenAI chat message fields;
    forwarding them would make a later text turn depend on the provider
    tolerating unknown keys.
    """
    return [
        cast(
            ChatCompletionMessageParam,
            {
                key: value
                for key, value in message.items()
                if key not in {"model", "generated_images"}
            },
        )
        for message in messages
    ]


def generate_image(
    prompt: str,
    model: str | None = None,
    input_references: list[str] | None = None,
) -> ImageGenerationResult:
    """Uses OpenRouter's dedicated Images API, not a chat completion.

    This gives image models their own explicit picker and keeps generation
    from entering the tool-call loop used for a normal conversation turn.
    """
    selected_model = model or load_image_model()
    api_key = _effective_api_key()
    if not api_key:
        raise ValueError("Aucune clé API OpenRouter configurée.")

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/images",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": selected_model,
                "prompt": prompt,
                **(
                    {
                        "input_references": [
                            {"type": "image_url", "image_url": {"url": reference}}
                            for reference in input_references
                        ]
                    }
                    if input_references
                    else {}
                ),
            },
            timeout=120,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenRouter image generation failed: {exc}") from exc

    try:
        data = response.json().get("data", [])
    except ValueError as exc:
        raise RuntimeError("OpenRouter returned an invalid image response.") from exc

    images: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        encoded = item.get("b64_json")
        if isinstance(encoded, str) and encoded:
            media_type = item.get("media_type")
            if not isinstance(media_type, str) or not media_type.startswith("image/"):
                media_type = "image/png"
            images.append(f"data:{media_type};base64,{encoded}")
        elif isinstance(item.get("url"), str):
            # Kept for providers returning a URL despite the documented
            # b64_json shape. The UI can still render it, while the normal
            # OpenRouter path remains self-contained in the session JSON.
            images.append(item["url"])

    if not images:
        raise RuntimeError("OpenRouter did not return an image.")
    return ImageGenerationResult(images=images, model=selected_model)


def call_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
    model: str | None = None,
) -> ChatResult:
    """`model` overrides the currently selected model (settings.json) for
    this call only - used by orchestrator.py, where each role runs a
    specific model regardless of what's selected for the main conversation.
    Omit it (the default) to keep using get_model(), as every other caller
    does."""
    model = model or get_model()
    provider_messages = _provider_messages(messages)
    if tools:
        resp = _with_retry(
            lambda: _client().chat.completions.create(
                model=model,
                messages=provider_messages,
                tools=tools,
                max_tokens=MAX_TOKENS,
            )
        )
    else:
        resp = _with_retry(
            lambda: _client().chat.completions.create(
                model=model,
                messages=provider_messages,
                max_tokens=MAX_TOKENS,
            )
        )

    choice = resp.choices[0]
    usage = resp.usage
    return ChatResult(
        content=choice.message.content,
        tool_calls=list(choice.message.tool_calls or []),
        model=resp.model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
        finish_reason=choice.finish_reason,
    )


def stream_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
    model: str | None = None,
) -> Iterator[str | ChatResult]:
    """Calls the model with streaming: yields each chunk of text as it
    arrives, then the full ChatResult once the response is complete (tool
    calls are never streamed chunk by chunk, just reconstructed silently,
    there's no point displaying them partially). `model` overrides the
    currently selected model for this call only - same convention as
    call_chat, used by server.py for a conversation with a per-session
    override set via the /model command.

    Found via a real conversation: a stream can die (observed message:
    "The operation was aborted") right after opening, before a single
    chunk carrying real content/tool-call data ever arrives - past
    _with_retry's scope (that only covers the .create() call that opens
    the stream, not reading its body) and past the point call sites like
    run_chat_stream could safely retry themselves, since by their level
    tokens may already be relayed to the client as SSE. Handled here
    instead: retried from scratch, same as _with_retry, but the boundary
    is "has this attempt produced any real output yet" rather than "has
    the request been sent yet" - once true, a failure is left to raise
    as-is, same reasoning _with_retry documents for why it stops there."""
    model = model or get_model()
    provider_messages = _provider_messages(messages)

    def _open_stream():
        if tools:
            return _client().chat.completions.create(
                model=model,
                messages=provider_messages,
                tools=tools,
                max_tokens=MAX_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
            )
        return _client().chat.completions.create(
            model=model,
            messages=provider_messages,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
        )

    attempt = 0
    content_parts: list[str] = []
    tool_call_parts: dict[int, dict[str, str]] = {}
    model_name = model
    prompt_tokens = completion_tokens = total_tokens = 0
    finish_reason: str | None = None

    while True:
        stream = _with_retry(_open_stream)
        content_parts = []
        tool_call_parts = {}
        produced_output = False

        try:
            for chunk in stream:
                model_name = chunk.model
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                    total_tokens = chunk.usage.total_tokens

                if not chunk.choices:
                    continue

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

                delta = chunk.choices[0].delta

                if delta.content:
                    produced_output = True
                    content_parts.append(delta.content)
                    yield delta.content

                for tool_call_delta in delta.tool_calls or []:
                    produced_output = True
                    entry = tool_call_parts.setdefault(
                        tool_call_delta.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tool_call_delta.id:
                        entry["id"] = tool_call_delta.id
                    if tool_call_delta.function:
                        if tool_call_delta.function.name:
                            entry["name"] += tool_call_delta.function.name
                        if tool_call_delta.function.arguments:
                            entry["arguments"] += tool_call_delta.function.arguments
        except Exception as exc:
            attempt += 1
            if produced_output or attempt > MAX_RETRIES or not is_transient_error(exc):
                raise
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
            continue

        break

    tool_calls: list[ChatCompletionMessageToolCallUnion] = [
        ChatCompletionMessageFunctionToolCall(
            id=entry["id"],
            type="function",
            function=Function(name=entry["name"], arguments=entry["arguments"]),
        )
        for entry in tool_call_parts.values()
    ]

    yield ChatResult(
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        model=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
    )
