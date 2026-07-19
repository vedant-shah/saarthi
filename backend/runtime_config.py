"""Runtime-editable settings stored on disk, outside the .env.

Currently just the Claude API key: saved via the Settings panel so the app can
be pointed at a key without editing environment files or restarting. The file is
gitignored (it holds a secret) and read fresh on each provider build."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

_STORE: Path = settings.project_root / "settings.local.json"


def _read() -> dict:
    if not _STORE.exists():
        return {}
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        logger.warning("runtime_config: could not read %s; treating as empty", _STORE)
        return {}


def load_api_key() -> str | None:
    """Return the saved Anthropic key, or None if unset/blank."""
    key = _read().get("anthropic_api_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def save_api_key(key: str) -> None:
    """Persist the Anthropic key (merged into any existing settings)."""
    data = _read()
    data["anthropic_api_key"] = key.strip()
    _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
