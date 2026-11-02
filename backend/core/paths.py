"""Isolated D-drive and workspace path resolution with zero C:/OneDrive pollution."""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = WORKSPACE_ROOT / "assets"


def get_studio_root() -> Path:
    """Return isolated runtime root (defaults to D:/DF11Studio)."""
    override = os.environ.get("DF11_STUDIO_ROOT")
    return Path(override) if override else Path("D:/DF11Studio")


def get_models_dir() -> Path:
    return get_studio_root() / "models"


def get_state_db_path() -> Path:
    return get_studio_root() / "state.sqlite3"


def get_webview_profile_dir() -> Path:
    return get_studio_root() / "webview_profile"


def get_default_vault_dir() -> Path:
    return get_studio_root() / "NG_Regens_Vault"
