"""Load runtime settings from env plus the gitignored `.config/libra.env` (env wins).

Secrets are expected to arrive as environment variables via `sops exec-env
.secret/secrets.json`. Tests may pass an explicit `env` mapping to `Settings.load`,
which then ignores the `.config/libra.env` file entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_OCR_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TZ = "America/Los_Angeles"
SECRET_KEYS: tuple[str, str] = ("GEMINI_API_KEY", "OPENROUTER_API_KEY")
SOPS_TIMEOUT_S: float = 30.0


def config_path(name: str) -> Path:
    return _REPO_ROOT / ".config" / name


def secrets_path() -> Path:
    return _REPO_ROOT / ".secret" / "secrets.json"


def _read_config_env() -> dict[str, str]:
    path = config_path("libra.env")
    try:
        text = path.read_text()
    except OSError:
        return {}

    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value.strip('"')
        result[key] = str(value)
    return result


def _read_sops_secrets(path: Path) -> dict[str, str]:
    """Decrypt `path` with sops; any failure (no file, no sops, bad output) yields {}."""
    try:
        sops = shutil.which("sops")
        if sops is None:
            return {}
        proc = subprocess.run(
            [sops, "-d", "--output-type", "json", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=SOPS_TIMEOUT_S,
        )
        data = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        key: str(data[key])
        for key in SECRET_KEYS
        if isinstance(data.get(key), str) and data[key]
    }


class SettingsError(ValueError):
    """Libra configuration is invalid."""


def default_state_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME", "")
    if xdg_state:
        return Path(xdg_state) / "libra"
    return Path.home() / ".local" / "state" / "libra"


@dataclass(frozen=True, slots=True)
class Settings:
    state_dir: Path = field(default_factory=default_state_dir)
    obsidian_academic_vault_dir: Path | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    ocr_model: str = DEFAULT_OCR_MODEL
    term: str | None = None
    tz: str = DEFAULT_TZ

    def __post_init__(self) -> None:
        state_dir = self.state_dir.expanduser()
        object.__setattr__(self, "state_dir", state_dir)
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SettingsError(
                f"state_dir {state_dir} is not creatable: {exc}"
            ) from exc

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = env if env is not None else {**_read_config_env(), **os.environ}

        def get(key: str) -> str | None:
            raw = e.get(key)
            if raw is None:
                return None
            value = raw.strip()
            return value or None

        state_dir = get("LIBRA_STATE_DIR")
        vault_dir = get("LIBRA_VAULT_DIR")
        gemini_api_key = get("GEMINI_API_KEY")
        openrouter_api_key = get("OPENROUTER_API_KEY")
        ocr_model = get("LIBRA_READ_MODEL") or DEFAULT_OCR_MODEL
        term = get("LIBRA_TERM")
        tz = get("LIBRA_TZ") or DEFAULT_TZ

        if term is not None:
            term = term.upper()
            if not re.fullmatch(r"[A-Z]{2}\d{2}", term):
                raise SettingsError(f"LIBRA_TERM must look like FA26, got {term!r}")

        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SettingsError(
                f"LIBRA_TZ is not a known time zone: {tz!r}"
            ) from exc

        return cls(
            state_dir=Path(state_dir) if state_dir is not None else default_state_dir(),
            obsidian_academic_vault_dir=(
                Path(vault_dir).expanduser().resolve() if vault_dir is not None else None
            ),
            gemini_api_key=gemini_api_key,
            openrouter_api_key=openrouter_api_key,
            ocr_model=ocr_model,
            term=term,
            tz=tz,
        )


def load_secrets(settings: Settings, *, path: Path | None = None) -> Settings:
    """Fill unset API keys from Libra's sops file; already-set keys are kept."""
    if settings.gemini_api_key and settings.openrouter_api_key:
        return settings
    found = _read_sops_secrets(path or secrets_path())
    return replace(
        settings,
        gemini_api_key=settings.gemini_api_key or found.get("GEMINI_API_KEY"),
        openrouter_api_key=settings.openrouter_api_key or found.get("OPENROUTER_API_KEY"),
    )
