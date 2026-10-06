# HTTP endpoint te pokretanje i gašenje aplikacije.

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from google import genai

from app.config import Settings, load_settings
from app.gemini import OrderService, ServiceError, create_client
from app.menu import MENU_PATH, load_menu
from app.models import OrderRequest, OrderResponse


def create_app(
    *,
    settings: Settings | None = None,
    menu_path: Path = MENU_PATH,
    client_factory: Callable[[Settings], genai.Client] = create_client,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = settings if settings is not None else load_settings()
        menu = load_menu(menu_path)
        client = client_factory(configuration)
        try:
            application.state.order_service = OrderService(client, menu, configuration.model)
            yield
        finally:
            try:
                await client.aio.aclose()
            finally:
                client.close()

    application = FastAPI(
        title="Tumačenje narudžbi restorana",
        description=(
            "Prepoznaje hrvatske narudžbe prema zadanom jelovniku. "
            "Ako clarification nije null, narudžba je nepotpuna; "
            "ponovno pošaljite cijelu pojašnjenu rečenicu. Svaki zahtjev je neovisan."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.post(
        "/order",
        response_model=OrderResponse,
        summary="Protumači narudžbu",
        responses={
            502: {"description": "AI servis je vratio nevaljan ili nepotpun rezultat."},
            503: {"description": "AI servis nije dostupan ili je potrošena kvota."},
            504: {"description": "Isteklo je vrijeme čekanja na AI servis."},
        },
    )
    async def order(payload: OrderRequest, request: Request) -> OrderResponse:
        service: OrderService = request.app.state.order_service
        try:
            return await service.interpret(payload.text)
        except ServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return application


app = create_app()
