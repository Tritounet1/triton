import server
from triton.llm.api import ChatResult


def test_compare_models_returns_response_metrics(monkeypatch):
    monkeypatch.setattr(
        server,
        "call_chat",
        lambda messages, model: ChatResult(
            content=f"answer from {model}",
            tool_calls=[],
            model=model,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
    )
    monkeypatch.setattr(server, "estimate_cost", lambda *_: 0.001)

    result = server.compare_models(
        server.ModelComparisonRequest(prompt="Compare", models=["one", "two", "one"])
    )

    assert [entry["model"] for entry in result] == ["one", "two"]
    assert result[0]["content"] == "answer from one"
    assert result[0]["cost_usd"] == 0.001
    assert result[0]["tool_calls"] == 0
