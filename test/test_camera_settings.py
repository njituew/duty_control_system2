"""Тесты сохранения/загрузки учётных данных камеры: core.camera_settings."""

import pytest

from core import camera_settings as cs


@pytest.fixture
def settings_path(monkeypatch, tmp_path):
    """Перенаправить файл настроек камеры во временный путь."""
    path = tmp_path / "camera_settings.json"
    monkeypatch.setattr(cs, "_get_config_path", lambda: str(path))
    return path


def test_save_load_roundtrip(settings_path) -> None:
    cs.save_settings("192.168.1.10", "admin", "12345678")

    assert cs.load_settings() == {
        "host": "192.168.1.10",
        "user": "admin",
        "password": "12345678",
    }


def test_load_missing_file_returns_empty(settings_path) -> None:
    assert cs.load_settings() == dict(cs.EMPTY_SETTINGS)


def test_load_corrupt_json_returns_empty(settings_path) -> None:
    settings_path.write_text("{broken", encoding="utf-8")

    assert cs.load_settings() == dict(cs.EMPTY_SETTINGS)


def test_load_non_dict_returns_empty(settings_path) -> None:
    settings_path.write_text("[1, 2, 3]", encoding="utf-8")

    assert cs.load_settings() == dict(cs.EMPTY_SETTINGS)


def test_load_partial_fields_filled_with_empty(settings_path) -> None:
    settings_path.write_text('{"host": "10.0.0.1"}', encoding="utf-8")

    data = cs.load_settings()
    assert data["host"] == "10.0.0.1"
    assert data["user"] == ""
    assert data["password"] == ""


def test_load_non_string_values_coerced(settings_path) -> None:
    settings_path.write_text(
        '{"host": 123, "user": null, "password": ["x"]}', encoding="utf-8"
    )

    assert cs.load_settings() == {"host": "123", "user": "None", "password": "['x']"}


def test_save_error_raises_runtime_error(monkeypatch, tmp_path) -> None:
    """Путь, указывающий на каталог, -> RuntimeError при сохранении."""
    target_dir = tmp_path / "not_a_file"
    target_dir.mkdir()
    monkeypatch.setattr(cs, "_get_config_path", lambda: str(target_dir))

    with pytest.raises(RuntimeError):
        cs.save_settings("10.0.0.1", "admin", "12345678")