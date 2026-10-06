# Pokretanje: python -m evaluation.evaluate [--assignment-only].

# Ovaj alat stvarno zove Gemini i troši API kvotu. Nije dio pytest/CI provjera.


import argparse
import json
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_settings
from app.main import create_app
from app.models import OrderResponse

EVALUATION_DIR = Path(__file__).resolve().parent


def normalize_text(text: str) -> str:
    # Zanemari velika slova i razmake, ali sačuvaj identitet proizvoda.
    return " ".join(text.casefold().split())


def compare_response(expected: dict[str, Any], actual: Any) -> list[str]:
    # Usporedi ID-eve i količine; značenje slobodnog teksta pregledava se ručno.
    try:
        response = OrderResponse.model_validate(actual)
    except ValidationError:
        return ["Odgovor ne odgovara javnoj shemi API-ja."]

    differences: list[str] = []
    expected_items = sorted((item["id"], item["quantity"]) for item in expected["items"])
    actual_items = sorted((item.id, item.quantity) for item in response.items)
    if actual_items != expected_items:
        differences.append("ID-evi ili količine naručenih stavki nisu očekivani.")

    unmatched = list(response.unavailable)
    for item in expected["unavailable"]:
        aliases = {normalize_text(text) for text in item["text_any_of"]}
        match = next(
            (
                index
                for index, actual_item in enumerate(unmatched)
                if normalize_text(actual_item.text) in aliases
                and actual_item.quantity == item["quantity"]
            ),
            None,
        )
        if match is None:
            differences.append("Nedostaje očekivana nedostupna stavka ili njezina količina.")
        else:
            unmatched.pop(match)
    if unmatched:
        differences.append("Odgovor sadrži neočekivane nedostupne stavke ili njihov opis.")

    if sorted(response.suggestions) != sorted(expected["suggestions"]):
        differences.append("Prijedlozi se ne podudaraju s očekivanim ID-evima.")
    if (response.clarification is not None) != expected["clarification"]:
        differences.append("Prisutnost pitanja za pojašnjenje nije očekivana.")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stvarna provjera Gemini modela na hrvatskim narudžbama (troši kvotu)."
    )
    parser.add_argument(
        "--assignment-only",
        action="store_true",
        help="Pokreni samo pet točnih primjera iz zadatka.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EVALUATION_DIR / "results" / "latest.json",
        help="Putanja JSON izvještaja (zadano evaluation/results/latest.json).",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except RuntimeError, ValueError:
        print("Provjerite GEMINI_API_KEY u okolini ili .env datoteci prije evaluacije.")
        return 2

    cases = json.loads((EVALUATION_DIR / "cases.json").read_text(encoding="utf-8"))
    if args.assignment_only:
        cases = [case for case in cases if case["assignment"]]

    report: dict[str, Any] = {
        "evaluated_at": datetime.now(ZoneInfo("Europe/Zagreb")).isoformat(),
        "mode": "real_model",
        "model": settings.model,
        "google_genai_version": version("google-genai"),
        "python_version": platform.python_version(),
        "assignment_only": args.assignment_only,
        "manual_review": (
            "Ručno provjerite značenje opisa nedostupnih stavki i pitanja za pojašnjenje. "
            "Usporedba prihvaća samo izričito navedene jezične inačice; smislen drukčiji opis "
            "može biti označen kao pad. Prisutnost pitanja ne dokazuje da je ono ispravno."
        ),
        "results": [],
    }
    print(f"Stvarni model: {settings.model}; broj poziva: {len(cases)}.")
    with TestClient(create_app(settings=settings)) as client:
        for case in cases:
            started = perf_counter()
            response = client.post("/order", json={"text": case["text"]})
            actual = response.json()
            differences = (
                compare_response(case["expected"], actual)
                if response.status_code == 200
                else [f"API je vratio HTTP {response.status_code}."]
            )
            result = {
                **case,
                "status_code": response.status_code,
                "actual": actual,
                "passed": not differences,
                "differences": differences,
                "duration_seconds": round(perf_counter() - started, 3),
            }
            report["results"].append(result)
            print(f"{'PROLAZ' if result['passed'] else 'PAD'}: {case['id']}")

    passed = sum(result["passed"] for result in report["results"])
    report["summary"] = {"total": len(cases), "passed": passed, "failed": len(cases) - passed}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(report_text, encoding="utf-8")
    print(f"Prolaz: {passed}/{len(cases)}. Izvještaj: {args.output.resolve()}")
    print(report["manual_review"])
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
