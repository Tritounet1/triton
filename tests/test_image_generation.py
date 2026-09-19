"""Image generation is a session event, not an untracked browser-only blob."""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import sessions


@pytest.fixture(autouse=True)
def _isolated_sessions_dir(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)


@pytest.fixture
def client():
    return TestClient(server.app)


@dataclass
class _ImageResult:
    images: list[str]
    model: str


def test_generated_image_is_saved_with_its_model_and_reloadable(client, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    monkeypatch.setattr(
        server,
        "generate_image",
        lambda prompt, model, references: _ImageResult(
            images=["data:image/png;base64,aGVsbG8="], model=model or "openai/gpt-image-1"
        ),
    )

    response = client.post(
        "/images/generate",
        json={"prompt": "un chat astronaute", "model": "openai/gpt-image-1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "openai/gpt-image-1"
    assert data["images"] == ["data:image/png;base64,aGVsbG8="]
    assert data["title"] == "un chat astronaute"

    history = client.get(f"/sessions/{data['session_id']}")
    assert history.status_code == 200
    messages = history.json()
    assert messages[-1] == {
        "role": "assistant",
        "content": "",
        "model": "openai/gpt-image-1",
        "generated_images": ["data:image/png;base64,aGVsbG8="],
    }


def test_image_generation_rejects_empty_prompt(client, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    response = client.post("/images/generate", json={"prompt": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "image prompt must not be empty"


def test_image_generation_sends_screenshot_as_a_reference_and_persists_it(client, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    captured: dict[str, object] = {}

    def fake_generate(prompt, model, references):
        captured["references"] = references
        return _ImageResult(images=["data:image/png;base64,cmVzdWx0"], model="test/image")

    monkeypatch.setattr(server, "generate_image", fake_generate)
    screenshot = "data:image/png;base64,c2NyZWVuc2hvdA=="
    response = client.post(
        "/images/generate",
        json={
            "prompt": "transforme cette capture",
            "attachments": [{"name": "capture.png", "data_url": screenshot}],
        },
    )

    assert response.status_code == 200
    assert captured["references"] == [screenshot]
    history = client.get(f"/sessions/{response.json()['session_id']}").json()
    assert history[-2]["content"] == [
        {"type": "text", "text": "transforme cette capture"},
        {"type": "image_url", "image_url": {"url": screenshot}},
    ]


def test_image_generation_rejects_a_pdf_reference(client, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    response = client.post(
        "/images/generate",
        json={
            "prompt": "transforme ce document",
            "attachments": [
                {"name": "document.pdf", "data_url": "data:application/pdf;base64,cGRm"}
            ],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "image generation references must be images"


def test_chat_model_override_is_forwarded_without_persisting_a_session_override(
    client, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_run_chat_stream(session_path, messages, first_message=None, model_override=None):
        captured["model"] = model_override
        yield "event: session\ndata: {}\n\n"

    monkeypatch.setattr(server, "run_chat_stream", fake_run_chat_stream)
    response = client.post("/chat", json={"message": "bonjour", "model": "openai/gpt-5"})

    assert response.status_code == 200
    assert captured["model"] == "openai/gpt-5"
