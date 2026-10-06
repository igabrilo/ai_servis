# Sheme API zahtjeva, odgovora i podataka izdvojenih jezičnim modelom.

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Quantity = Annotated[int, Field(ge=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class OrderRequest(StrictModel):
    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2000),
    ] = Field(description="Narudžba ili upit na hrvatskom jeziku.")

    @field_validator("text")
    @classmethod
    def trim_text(cls, text: str) -> str:
        # Duljina se provjerava prije uklanjanja razmaka kako se limit ne bi zaobišao.
        text = text.strip()
        if not text:
            raise ValueError("Tekst narudžbe ne smije biti prazan.")
        return text


class OrderItem(StrictModel):
    id: NonEmptyText
    quantity: Quantity


class UnavailableItem(StrictModel):
    text: NonEmptyText
    quantity: Quantity


class ModelOrder(StrictModel):
    items: list[OrderItem]
    unavailable: list[UnavailableItem]
    wants_meat_free: bool
    clarification: NonEmptyText | None


class OrderResponse(StrictModel):
    items: list[OrderItem]
    unavailable: list[UnavailableItem]
    suggestions: list[NonEmptyText]
    clarification: NonEmptyText | None
