# Pozovi Gemini i provjeri podatke prije sastavljanja odgovora API-ja.

import asyncio
import json
import logging
from time import perf_counter

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import Settings
from app.menu import Menu
from app.models import ModelOrder, OrderItem, OrderResponse
from app.prompts import build_system_prompt

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 30


class ServiceError(Exception):
    # Pogreška s javnom porukom koja ne otkriva osjetljive detalje.

    def __init__(
        self,
        status_code: int,
        detail: str,
        category: str,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.category = category
        self.upstream_status = upstream_status


def create_client(settings: Settings) -> genai.Client:
    # SDK može zapisati detalje mrežnih pogrešaka na INFO razini.
    # Aplikacija zapisuje samo kategoriju, status i trajanje zahtjeva.
    logging.getLogger("google.genai._api_client").setLevel(logging.WARNING)
    return genai.Client(
        api_key=settings.api_key,
        http_options=types.HttpOptions(
            timeout=15_000,
            retry_options=types.HttpRetryOptions(
                attempts=2,  # Početni poziv i najviše jedan ponovni pokušaj.
                initial_delay=1,
                max_delay=2,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        ),
    )


def invalid_output() -> ServiceError:
    return ServiceError(
        502,
        "AI servis nije vratio valjanu narudžbu. Pokušajte ponovno.",
        "invalid_output",
    )


class OrderService:
    def __init__(self, client: genai.Client, menu: Menu, model: str) -> None:
        self.client = client
        self.menu = menu
        self.model = model
        self.system_prompt = build_system_prompt(menu)
        # Jedna shema služi i Geminiju i strogoj lokalnoj validaciji.
        self.response_schema = ModelOrder.model_json_schema()

    async def interpret(self, text: str) -> OrderResponse:
        started = perf_counter()
        try:
            result = await self._generate(text)
        except ServiceError as exc:
            logger.warning(
                "order_failed category=%s upstream_status=%s duration_ms=%.0f",
                exc.category,
                exc.upstream_status,
                (perf_counter() - started) * 1000,
            )
            raise
        logger.info("order_completed duration_ms=%.0f", (perf_counter() - started) * 1000)
        return result

    async def _generate(self, text: str) -> OrderResponse:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        response_mime_type="application/json",
                        response_json_schema=self.response_schema,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        max_output_tokens=4096,
                    ),
                )
        except TimeoutError, httpx.TimeoutException:
            raise ServiceError(
                504, "AI servis nije odgovorio na vrijeme. Pokušajte ponovno.", "timeout"
            ) from None
        except errors.APIError as exc:
            if exc.code in (408, 504):
                raise ServiceError(
                    504,
                    "AI servis nije odgovorio na vrijeme. Pokušajte ponovno.",
                    "timeout",
                    exc.code,
                ) from None
            raise ServiceError(
                503,
                "AI servis trenutačno nije dostupan. Pokušajte ponovno kasnije.",
                "upstream_error",
                exc.code,
            ) from None
        except httpx.RequestError, OSError:
            raise ServiceError(
                503,
                "AI servis trenutačno nije dostupan. Pokušajte ponovno kasnije.",
                "connection_error",
            ) from None
        except ValidationError, json.JSONDecodeError:
            raise invalid_output() from None
        return self._parse_response(response)

    def _parse_response(self, response: types.GenerateContentResponse) -> OrderResponse:
        feedback = response.prompt_feedback
        if feedback and feedback.block_reason not in (
            None,
            types.BlockedReason.BLOCKED_REASON_UNSPECIFIED,
        ):
            raise invalid_output()
        if not response.candidates or len(response.candidates) != 1:
            raise invalid_output()
        candidate = response.candidates[0]
        if candidate.finish_reason != types.FinishReason.STOP:
            raise invalid_output()
        if not candidate.content or not candidate.content.parts:
            raise invalid_output()
        # Provjeravamo izvorni JSON jer SDK-ov .parsed može biti prazan.
        raw = "".join(
            part.text
            for part in candidate.content.parts
            if part.text is not None and not part.thought
        )
        try:
            extracted = ModelOrder.model_validate_json(raw)
        except ValidationError:
            raise invalid_output() from None
        allowed_ids = self.menu.ids
        if any(item.id not in allowed_ids for item in extracted.items):
            raise invalid_output()
        if not (
            extracted.items
            or extracted.unavailable
            or extracted.wants_meat_free
            or extracted.clarification
        ):
            raise invalid_output()

        # Model rješava ispravke; ovdje zbrajamo izdvojene konačne količine.
        quantities: dict[str, int] = {}
        for item in extracted.items:
            quantities[item.id] = quantities.get(item.id, 0) + item.quantity
        return OrderResponse(
            items=[OrderItem(id=item_id, quantity=count) for item_id, count in quantities.items()],
            unavailable=extracted.unavailable,
            suggestions=self.menu.meat_free_ids if extracted.wants_meat_free else [],
            clarification=extracted.clarification,
        )
