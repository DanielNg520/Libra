"""Tests for libra.config missing-config warning."""

from __future__ import annotations

from pathlib import Path

import pytest

import libra.config


def test_missing_config_warns_with_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config_file = tmp_path / "absent" / "libra.env"
    monkeypatch.setattr(libra.config, "config_path", lambda name: config_file)

    with caplog.at_level("WARNING", logger="libra.config"):
        result = libra.config._read_config_env()

    assert result == {}
    assert any(str(config_file) in record.message for record in caplog.records)


def test_present_config_parsed_without_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config_file = tmp_path / "libra.env"
    config_file.write_text("# comment\n\nLIBRA_TERM=FA26\n", encoding="utf-8")
    monkeypatch.setattr(libra.config, "config_path", lambda name: config_file)

    with caplog.at_level("WARNING", logger="libra.config"):
        result = libra.config._read_config_env()

    assert result == {"LIBRA_TERM": "FA26"}
    assert not caplog.records


def test_settings_repr_hides_secrets(tmp_path):
    settings = libra.config.Settings(
        state_dir=tmp_path,
        gemini_api_key="gemini-marker",
        openrouter_api_key="openrouter-marker",
        anki_hkey="anki-hkey-marker",
        anki_endpoint="anki-endpoint-marker",
    )
    repr_str = repr(settings)
    assert "gemini-marker" not in repr_str
    assert "openrouter-marker" not in repr_str
    assert "anki-hkey-marker" not in repr_str
    assert "anki-endpoint-marker" not in repr_str


def test_settings_load_reads_anki_keys(tmp_path):
    settings = libra.config.Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path),
            "LIBRA_ANKIWEB_HKEY": "hkey-from-env",
            "LIBRA_ANKIWEB_ENDPOINT": "endpoint-from-env",
        }
    )
    assert settings.anki_hkey == "hkey-from-env"
    assert settings.anki_endpoint == "endpoint-from-env"


def test_load_secrets_fills_anki_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(
        libra.config,
        "_read_sops_secrets",
        lambda *args, **kwargs: {
            "LIBRA_ANKIWEB_HKEY": "hkey-from-sops",
            "LIBRA_ANKIWEB_ENDPOINT": "endpoint-from-sops",
        },
    )
    settings = libra.config.Settings(
        state_dir=tmp_path,
        gemini_api_key="gemini",
        openrouter_api_key="openrouter",
        anki_hkey="preset-hkey",
    )
    result = libra.config.load_secrets(settings)
    assert result.anki_hkey == "preset-hkey"
    assert result.anki_endpoint == "endpoint-from-sops"


def test_load_secrets_skips_sops_when_all_set(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("sops should not be called")

    monkeypatch.setattr(libra.config, "_read_sops_secrets", boom)
    settings = libra.config.Settings(
        state_dir=tmp_path,
        gemini_api_key="gemini",
        openrouter_api_key="openrouter",
        anki_hkey="hkey",
        anki_endpoint="endpoint",
    )
    result = libra.config.load_secrets(settings)
    assert result is settings
