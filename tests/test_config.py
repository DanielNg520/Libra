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
