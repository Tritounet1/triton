import os
from collections.abc import Iterator
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionToolParam,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from triton.paths import ROOT_DIR
from triton.settings import load_model, load_openrouter_api_key

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
    )


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
    if tools:
        resp = _client().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=MAX_TOKENS,
        )
    else:
        resp = _client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=MAX_TOKENS,
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
) -> Iterator[str | ChatResult]:
    """Calls the model with streaming: yields each chunk of text as it
    arrives, then the full ChatResult once the response is complete (tool
    calls are never streamed chunk by chunk, just reconstructed silently,
    there's no point displaying them partially)."""
    model = get_model()
    if tools:
        stream = _client().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
        )
    else:
        stream = _client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
        )

    content_parts: list[str] = []
    tool_call_parts: dict[int, dict[str, str]] = {}
    model_name = model
    prompt_tokens = completion_tokens = total_tokens = 0
    finish_reason: str | None = None

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
            content_parts.append(delta.content)
            yield delta.content

        for tool_call_delta in delta.tool_calls or []:
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
