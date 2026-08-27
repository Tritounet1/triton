import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionToolParam,
)

# Load values from .env into environment variables
_ = load_dotenv()

# Access your variables
open_router_api_key = os.getenv("OPEN_ROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=open_router_api_key,
)

MODEL = "meta-llama/llama-3.1-8b-instruct"


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
