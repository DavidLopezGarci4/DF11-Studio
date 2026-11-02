"""Validated, XXE-safe, atomic Football Manager config.xml reader/writer."""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from defusedxml import ElementTree as SafeET

VALID_FM_UID_RE = re.compile(r"^(?:r-)?[0-9]{1,12}$")


class FMConfigError(ValueError):
    """Raised on invalid Football Manager UID or unsafe config.xml content."""


def validate_fm_uid(uid: str) -> str:
    """Validate classic numeric (<ID>) or FM24/26/27 regen (r-<ID>) identifier."""
    cleaned = uid.strip() if isinstance(uid, str) else ""
    if not VALID_FM_UID_RE.fullmatch(cleaned):
        raise FMConfigError(f"ID de Football Manager inválido: {uid!r} (usa dígitos o r-<dígitos>).")
    return cleaned


def safe_ntfs_replace(src: Path, dst: Path, retries: int = 5) -> None:
    """Atomically replace dst with src, retrying transient OneDrive/Defender file locks."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(0.02 * (2**attempt))


def upsert_fm_config_xml(config_path: Path, uids: Iterable[str]) -> int:
    """Idempotently merge portrait mappings for uids into config.xml using atomic NTFS replace."""
    validated = [validate_fm_uid(u) for u in uids]
    records: dict[str, str] = {}

    if config_path.is_file():
        try:
            tree = SafeET.parse(config_path)
            for rec in tree.getroot().findall(".//record"):
                frm = rec.attrib.get("from", "").strip()
                to = rec.attrib.get("to", "").strip()
                if frm and to:
                    records[frm] = to
        except Exception as exc:
            raise FMConfigError(f"No se pudo leer config.xml de forma segura: {exc}") from exc

    for uid in validated:
        records[uid] = f"graphics/pictures/person/{uid}/portrait"

    lines = [
        "<record>",
        '\t<boolean id="preload" value="false"/>',
        '\t<boolean id="amap" value="false"/>',
        '\t<list id="maps">',
    ]
    for frm in sorted(records.keys(), key=lambda k: (k.startswith("r-"), k)):
        lines.append(f'\t\t<record from="{frm}" to="{records[frm]}"/>')
    lines.extend(["\t</list>", "</record>", ""])
    payload = "\n".join(lines).encode("utf-8")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cfg_", suffix=".tmp", dir=str(config_path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        safe_ntfs_replace(tmp_path, config_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return len(records)
