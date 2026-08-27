import os
from openai import OpenAI
from dotenv import load_dotenv

# Load values from .env into environment variables
_ = load_dotenv()

# Access your variables
open_router_api_key = os.getenv("OPEN_ROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=open_router_api_key,
)

MODEL = "meta-llama/llama-3.1-8b-instruct"

def call_chat(message: str):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise and clear assistant."},
            {"role": "user", "content": message},
        ],
        max_tokens=1024,
    )

    print("resp : ", resp)
    return resp.choices[0].message.content
