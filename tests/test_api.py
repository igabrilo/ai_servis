# Provjeri API i obradu pogrešaka pomoću unaprijed zadanih SDK odgovora.

import asyncio
import logging
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

from app import gemini
from app.main import create_app

from .conftest import model_payload, sdk_response


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": None},
        {"text": 123},
        {"text": True},
        {"text": []},
        {"text": ""},
        {"text": " \n\t "},
        {"text": "a" * 2001},
        {"text": " " * 2000 + "a"},
        {"text": "margarita", "unexpected": True},
        ["margarita"],
    ],
)
def test_invalid_input_is_rejected_before_model_call(client, sdk_client, body):
    response = client.post("/order", json=body)
    assert response.status_code == 422
    sdk_client.aio.models.generate_content.assert_not_awaited()


def test_malformed_json_is_rejected_before_model_call(client, sdk_client):
    response = client.post(
        "/order", content='{ "text":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    sdk_client.aio.models.generate_content.assert_not_awaited()


def test_input_length_boundary_and_whitespace(client, sdk_client):
    response = client.post("/order", json={"text": "a" * 2000})
    assert response.status_code == 200
    response = client.post("/order", json={"text": "   margarita   "})
    assert response.status_code == 200
    assert sdk_client.aio.models.generate_content.await_count == 2


def test_response_preserves_unavailable_product_identity(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(unavailable=[{"text": "Pepsi", "quantity": 2}])
    )
    response = client.post("/order", json={"text": "margaritu i dva Pepsija"})
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": "margarita", "quantity": 1}],
        "unavailable": [{"text": "Pepsi", "quantity": 2}],
        "suggestions": [],
        "clarification": None,
    }


def test_meat_free_suggestions_exclude_drinks(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(items=[], wants_meat_free=True)
    )
    response = client.post("/order", json={"text": "što imate bez mesa?"})
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "unavailable": [],
        "suggestions": ["margarita", "vegetariana", "quattro_formaggi", "mijesana_salata"],
        "clarification": None,
    }


def test_suggestions_can_accompany_an_explicit_order(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(items=[{"id": "pivo", "quantity": 1}], wants_meat_free=True)
    )
    response = client.post("/order", json={"text": "jedno pivo i što imate bez mesa?"})
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": "pivo", "quantity": 1}]
    assert "pivo" not in response.json()["suggestions"]
    assert len(response.json()["suggestions"]) == 4


def test_clarification_keeps_independently_understood_items(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(
            items=[{"id": "coca_cola", "quantity": 2}],
            clarification="Koju pizzu želite?",
        )
    )
    response = client.post("/order", json={"text": "dvije cole i jednu pizzu"})
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": "coca_cola", "quantity": 2}]
    assert response.json()["clarification"] == "Koju pizzu želite?"


def test_clarification_without_items_is_valid(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(items=[], clarification="Možete li jasnije navesti narudžbu?")
    )
    response = client.post("/order", json={"text": "asdf zxcv"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["clarification"]


def test_only_unavailable_items_are_preserved(client, sdk_client):
    sdk_client.aio.models.generate_content.return_value = sdk_response(
        model_payload(items=[], unavailable=[{"text": "kebab", "quantity": 2}])
    )
    response = client.post("/order", json={"text": "dva kebaba"})
    assert response.status_code == 200
    assert response.json()["unavailable"] == [{"text": "kebab", "quantity": 2}]


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, 2.0, "2", None])
@pytest.mark.parametrize("field", ["items", "unavailable"])
def test_invalid_model_quantities_are_rejected(client, sdk_client, quantity, field):
    item = {"id": "margarita"} if field == "items" else {"text": "hamburger"}
    payload = model_payload(**{field: [item | {"quantity": quantity}]})
    sdk_client.aio.models.generate_content.return_value = sdk_response(payload)
    assert client.post("/order", json={"text": "margaritu"}).status_code == 502
    sdk_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.parametrize("missing", ["items", "unavailable", "wants_meat_free", "clarification"])
def test_missing_model_fields_are_rejected(client, sdk_client, missing):
    payload = model_payload()
    del payload[missing]
    sdk_client.aio.models.generate_content.return_value = sdk_response(payload)
    assert client.post("/order", json={"text": "margaritu"}).status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        model_payload(items=[{"id": "invented_pizza", "quantity": 1}]),
        model_payload(items=[{"id": "margarita"}]),
        model_payload(unavailable=[{"text": "", "quantity": 1}]),
        model_payload(clarification="   "),
        model_payload(wants_meat_free="false"),
        model_payload(suggestions=["pivo"]),
        model_payload(items=[]),
        [],
    ],
)
def test_invalid_model_payload_never_becomes_success(client, sdk_client, payload):
    sdk_client.aio.models.generate_content.return_value = sdk_response(payload)
    assert client.post("/order", json={"text": "margaritu"}).status_code == 502


@pytest.mark.parametrize("text", ["", " ", "not JSON", '{"items":', "null"])
def test_invalid_or_empty_json_is_rejected(client, sdk_client, text):
    sdk_client.aio.models.generate_content.return_value = sdk_response(text=text)
    assert client.post("/order", json={"text": "margaritu"}).status_code == 502
    sdk_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.parametrize(
    "sdk_result",
    [
        types.GenerateContentResponse(),
        types.GenerateContentResponse(candidates=[]),
        types.GenerateContentResponse(candidates=[types.Candidate(finish_reason="STOP")]),
        sdk_response(finish_reason="MAX_TOKENS"),
        sdk_response(finish_reason="SAFETY"),
        sdk_response(finish_reason=None),
        sdk_response(blocked=True),
    ],
)
def test_blocked_truncated_or_missing_content_is_rejected(client, sdk_client, sdk_result):
    sdk_client.aio.models.generate_content.return_value = sdk_result
    assert client.post("/order", json={"text": "margaritu"}).status_code == 502


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (errors.ClientError(429, {"error": {"message": "Quota exhausted"}}), 503),
        (errors.ClientError(403, {"error": {"message": "Invalid credentials"}}), 503),
        (errors.ServerError(503, {"error": {"message": "Provider unavailable"}}), 503),
        (httpx.ConnectError("Connection failed"), 503),
        (httpx.ReadTimeout("Read timeout"), 504),
    ],
)
def test_provider_failures_have_documented_http_status(
    client, sdk_client, exception, expected_status
):
    sdk_client.aio.models.generate_content.side_effect = exception
    response = client.post("/order", json={"text": "margaritu"})
    assert response.status_code == expected_status
    assert isinstance(response.json()["detail"], str)
    sdk_client.aio.models.generate_content.assert_awaited_once()


def test_overall_deadline_cancels_slow_provider(client, sdk_client, monkeypatch):
    completed = False

    async def slow_response(**kwargs):
        nonlocal completed
        await asyncio.sleep(1)
        completed = True
        return sdk_response()

    monkeypatch.setattr(gemini, "REQUEST_TIMEOUT_SECONDS", 0.01)
    sdk_client.aio.models.generate_content.side_effect = slow_response
    response = client.post("/order", json={"text": "margaritu"})
    assert response.status_code == 504
    assert not completed


def test_errors_do_not_leak_provider_text_key_or_customer_text(client, sdk_client, caplog):
    customer_text = "private customer marker margaritu"
    secret = "offline-test-secret"
    provider_message = f"private provider marker key={secret} request={customer_text}"
    sdk_client.aio.models.generate_content.side_effect = errors.ClientError(
        429, {"error": {"message": provider_message}}
    )
    with caplog.at_level(logging.WARNING):
        response = client.post("/order", json={"text": customer_text})
    assert response.status_code == 503
    for private_value in (secret, customer_text, "private provider marker"):
        assert private_value not in response.text
        assert private_value not in caplog.text
    assert "429" in caplog.text


def test_client_is_created_once_and_closed_after_lifespan(sdk_client, settings):
    factory = Mock(return_value=sdk_client)
    application = create_app(settings=settings, client_factory=factory)
    factory.assert_not_called()
    with TestClient(application) as test_client:
        assert test_client.get("/docs").status_code == 200
        assert test_client.get("/openapi.json").json()["paths"].keys() == {"/order"}
        assert test_client.post("/order", json={"text": "margaritu"}).status_code == 200
        assert test_client.post("/order", json={"text": "margaritu"}).status_code == 200
        factory.assert_called_once_with(settings)
        sdk_client.aio.aclose.assert_not_awaited()
    sdk_client.aio.aclose.assert_awaited_once()
    sdk_client.close.assert_called_once()
