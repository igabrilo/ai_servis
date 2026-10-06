# Zamjenski SDK odgovori za testove koji ne trebaju mrežu ni API ključ.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.config import Settings
from app.main import create_app


def model_payload(**overrides):
    payload = {
        "items": [{"id": "margarita", "quantity": 1}],
        "unavailable": [],
        "wants_meat_free": False,
        "clarification": None,
    }
    return payload | overrides


def sdk_response(payload=None, *, text=None, finish_reason="STOP", blocked=False):
    if text is None:
        text = json.dumps(model_payload() if payload is None else payload)
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=finish_reason,
                content=types.Content(role="model", parts=[types.Part(text=text)]),
            )
        ],
        prompt_feedback=(
            types.GenerateContentResponsePromptFeedback(block_reason="SAFETY") if blocked else None
        ),
    )


@pytest.fixture
def sdk_client():
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=sdk_response())),
            aclose=AsyncMock(),
        ),
        close=Mock(),
    )


@pytest.fixture
def settings():
    return Settings(api_key="offline-test-secret", model="offline-model")


@pytest.fixture
def client(sdk_client, settings):
    application = create_app(settings=settings, client_factory=lambda _: sdk_client)
    with TestClient(application) as test_client:
        yield test_client
