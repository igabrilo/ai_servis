# Provjeri pravi SDK preko zamjenskog HTTP transporta, bez mrežnih poziva.

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import gemini
from app.main import create_app

from .conftest import model_payload


def install_transport(monkeypatch, handler):
    real_client = gemini.genai.Client

    def client_with_transport(**kwargs):
        kwargs["http_options"].async_client_args = {"transport": httpx.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(gemini.genai, "Client", client_with_transport)


def successful_http_response():
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": json.dumps(model_payload())}],
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    )


def test_sdk_accepts_schema_and_keeps_customer_text_separate(monkeypatch, settings):
    requests = []

    def handler(request):
        requests.append(request)
        return successful_http_response()

    install_transport(monkeypatch, handler)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/order", json={"text": "moja jedinstvena narudžba"})
    assert response.status_code == 200
    assert len(requests) == 1
    assert requests[0].extensions["timeout"]["read"] == 15
    body = json.loads(requests[0].content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": "moja jedinstvena narudžba"}]}]
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert "moja jedinstvena narudžba" not in prompt
    assert "quattro_formaggi" in prompt
    assert "coca_cola" in prompt
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    schema = body["generationConfig"]["responseJsonSchema"]
    assert set(schema["required"]) == {"items", "unavailable", "wants_meat_free", "clarification"}
    assert schema["$defs"]["OrderItem"]["properties"]["quantity"]["minimum"] == 1
    assert schema["additionalProperties"] is False
    assert "responseSchema" not in body["generationConfig"]


def test_malformed_provider_json_returns_sanitized_error(monkeypatch, settings, caplog):
    marker = "osjetljivi-detalji-iz-neispravnog-odgovora"

    def handler(request):
        return httpx.Response(200, content=marker, headers={"Content-Type": "application/json"})

    install_transport(monkeypatch, handler)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/order", json={"text": "margaritu"})
    assert response.status_code == 502
    assert marker not in response.text
    assert marker not in caplog.text


@pytest.mark.parametrize(("upstream_status", "expected_attempts"), [(429, 2), (503, 2), (403, 1)])
def test_sdk_retries_only_once_for_transient_http_failures(
    monkeypatch, settings, upstream_status, expected_attempts
):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            upstream_status,
            json={"error": {"code": upstream_status, "message": "Controlled offline failure"}},
        )

    install_transport(monkeypatch, handler)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/order", json={"text": "margaritu"})
    assert response.status_code == 503
    assert attempts == expected_attempts
