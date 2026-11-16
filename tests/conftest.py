"""Prevent tests from touching Libra's real secrets or environment files."""

from __future__ import annotations

import pytest

import libra.config


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    def _empty(*args: object, **kwargs: object) -> dict[str, str]:
        return {}

    monkeypatch.setattr(libra.config, "_read_sops_secrets", _empty)

    if not request.module.__name__.endswith("test_config"):
        monkeypatch.setattr(libra.config, "_read_config_env", _empty)
