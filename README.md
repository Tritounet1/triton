# Triton

A small AI agent harness built from scratch in Python, as a learning project to understand how tools like Claude Code work under the hood: the loop that turns a plain LLM into an agent capable of using tools, keeping memory, and acting safely.

## Features

- Multi-turn chat with streaming responses
- Tool calling in a ReAct-style loop: read files, list directories, write files, run shell commands
- Permission prompt before any action that modifies something (writing a file, running a command)
- Automatic context compression once the conversation history grows too large
- Persistent sessions: conversations are saved to disk and resumed automatically on the next run
- Structured JSONL logs, plus a small script to summarize them

## Stack

- Python 3.13, managed with [uv](https://docs.astral.sh/uv/)
- OpenAI-compatible SDK, calling models through [OpenRouter](https://openrouter.ai)
- [rich](https://github.com/Textualize/rich) for the terminal UI, [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) for input

## Running it

```
uv sync
cp .env.template .env   # fill in your OpenRouter API key
uv run main.py
```

To inspect the logs afterward:

```
uv run logs_summary.py
```
