# Neispravne postavke i jelovnik odbijaju se prije stvaranja mrežnog klijenta.

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import load_settings
from app.main import create_app
from app.menu import MENU_PATH, load_menu


def test_menu_path_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    menu = load_menu()
    assert len(menu.items) == 10
    assert "coca_cola" in menu.ids
    assert menu.meat_free_ids == [
        "margarita",
        "vegetariana",
        "quattro_formaggi",
        "mijesana_salata",
    ]


@pytest.mark.parametrize("menu_content", ["not JSON", "[]", "{}", '[{"id": "incomplete"}]'])
def test_invalid_menu_blocks_startup(tmp_path, settings, menu_content):
    path = tmp_path / "jelovnik.json"
    path.write_text(menu_content, encoding="utf-8")
    factory = Mock()
    with pytest.raises(ValueError, match="Jelovnik"):
        with TestClient(create_app(settings=settings, menu_path=path, client_factory=factory)):
            pass
    factory.assert_not_called()


def test_duplicate_menu_ids_are_rejected(tmp_path):
    items = json.loads(MENU_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "jelovnik.json"
    path.write_text(json.dumps([items[0], items[0]]), encoding="utf-8")
    with pytest.raises(ValueError, match="jedinstven ID"):
        load_menu(path)


def test_missing_menu_file_is_reported(tmp_path):
    with pytest.raises(ValueError, match="Jelovnik"):
        load_menu(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("field", "value"),
    [("bez_mesa", "false"), ("kategorija", "unknown"), ("cijena_eur", -1)],
)
def test_menu_attributes_are_validated(tmp_path, field, value):
    items = json.loads(MENU_PATH.read_text(encoding="utf-8"))
    items[0][field] = value
    path = tmp_path / "jelovnik.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="Jelovnik"):
        load_menu(path)


@pytest.fixture
def isolated_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    return tmp_path


def test_dotenv_settings_and_hidden_key_in_repr(isolated_configuration):
    (isolated_configuration / ".env").write_text(
        "GEMINI_API_KEY=dotenv-private-key\nGEMINI_MODEL=dotenv-model\n", encoding="utf-8"
    )
    settings = load_settings()
    assert settings.api_key == "dotenv-private-key"
    assert settings.model == "dotenv-model"
    assert "dotenv-private-key" not in repr(settings)


def test_environment_takes_precedence(isolated_configuration, monkeypatch):
    (isolated_configuration / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\nGEMINI_MODEL=dotenv-model\n", encoding="utf-8"
    )
    monkeypatch.setenv("GEMINI_API_KEY", "environment-key")
    monkeypatch.setenv("GEMINI_MODEL", "environment-model")
    settings = load_settings()
    assert settings.api_key == "environment-key"
    assert settings.model == "environment-model"


@pytest.mark.parametrize("key", [None, "", "   ", "your_api_key_here"])
def test_missing_or_placeholder_key_blocks_startup(isolated_configuration, monkeypatch, key):
    if key is not None:
        monkeypatch.setenv("GEMINI_API_KEY", key)
    factory = Mock()
    application = create_app(client_factory=factory)
    factory.assert_not_called()
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        with TestClient(application):
            pass
    factory.assert_not_called()


def test_explicit_empty_environment_key_does_not_use_dotenv(isolated_configuration, monkeypatch):
    (isolated_configuration / ".env").write_text("GEMINI_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_settings()
