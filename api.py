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

_ = load_dotenv()

open_router_api_key = os.getenv("OPEN_ROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=open_router_api_key,
)

MODEL = "anthropic/claude-haiku-4.5"


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ChatCompletionMessageToolCallUnion]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def call_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
) -> ChatResult:
    if tools:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            max_tokens=1024,
        )
    else:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1024,
        )

    message = resp.choices[0].message
    usage = resp.usage
    return ChatResult(
        content=message.content,
        tool_calls=list(message.tool_calls or []),
        model=resp.model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )


def stream_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
) -> Iterator[str | ChatResult]:
    """Calls the model with streaming: yields each chunk of text as it
    arrives, then the full ChatResult once the response is complete (tool
    calls are never streamed chunk by chunk, just reconstructed silently,
    there's no point displaying them partially)."""
    if tools:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            max_tokens=1024,
            stream=True,
            stream_options={"include_usage": True},
        )
    else:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1024,
            stream=True,
            stream_options={"include_usage": True},
        )

    content_parts: list[str] = []
    tool_call_parts: dict[int, dict[str, str]] = {}
    model_name = MODEL
    prompt_tokens = completion_tokens = total_tokens = 0

    for chunk in stream:
        model_name = chunk.model
        if chunk.usage:
            prompt_tokens = chunk.usage.prompt_tokens
            completion_tokens = chunk.usage.completion_tokens
            total_tokens = chunk.usage.total_tokens

        if not chunk.choices:
            continue

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
    )
