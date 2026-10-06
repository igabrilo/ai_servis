# Učitaj jelovnik i odredi dopuštene ID-eve te prijedloge hrane bez mesa.

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from app.config import PROJECT_ROOT
from app.models import NonEmptyText, StrictModel

MENU_PATH = PROJECT_ROOT / "data" / "jelovnik.json"


class MenuItem(StrictModel):
    id: NonEmptyText
    naziv: NonEmptyText
    kategorija: Literal["pizza", "salata", "piće"]
    cijena_eur: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    bez_mesa: bool


@dataclass(frozen=True)
class Menu:
    items: list[MenuItem]

    @property
    def ids(self) -> set[str]:
        return {item.id for item in self.items}

    @property
    def meat_free_ids(self) -> list[str]:
        return [item.id for item in self.items if item.bez_mesa and item.kategorija != "piće"]


def load_menu(path: Path = MENU_PATH) -> Menu:
    try:
        items = TypeAdapter(list[MenuItem]).validate_json(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, ValidationError:
        raise ValueError(
            "Jelovnik nije moguće učitati: provjerite JSON i obavezna polja."
        ) from None
    if not items:
        raise ValueError("Jelovnik ne smije biti prazan.")
    if len({item.id for item in items}) != len(items):
        raise ValueError("Svaka stavka jelovnika mora imati jedinstven ID.")
    return Menu(items=items)
