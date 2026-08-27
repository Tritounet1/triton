import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

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
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def call_chat(messages: list[ChatCompletionMessageParam]) -> ChatResult:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=1024,
    )

    content = resp.choices[0].message.content
    if content is None:
        raise RuntimeError("Le modèle n'a pas renvoyé de texte (appel d'outil non géré pour l'instant).")

    usage = resp.usage
    return ChatResult(
        content=content,
        model=resp.model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )
