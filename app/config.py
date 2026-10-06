# Učitaj postavke pri pokretanju bez zapisivanja API ključa u logove.

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.1-flash-lite"


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL

    def __post_init__(self) -> None:
        if not self.api_key.strip() or self.api_key.strip() == "your_api_key_here":
            raise ValueError("Postavite GEMINI_API_KEY u .env datoteci ili varijablama okruženja.")
        if not self.model.strip():
            raise ValueError("GEMINI_MODEL ne smije biti prazan.")


def load_settings() -> Settings:
    # Varijable okruženja imaju prednost pred lokalnom datotekom .env.
    local = dotenv_values(PROJECT_ROOT / ".env", interpolate=False)
    api_key = os.environ.get("GEMINI_API_KEY", local.get("GEMINI_API_KEY")) or ""
    model = os.environ.get("GEMINI_MODEL", local.get("GEMINI_MODEL", DEFAULT_MODEL)) or ""
    return Settings(api_key=api_key.strip(), model=model.strip())
