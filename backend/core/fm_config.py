"""Validated, XXE-safe, atomic Football Manager config.xml reader/writer."""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from xml.sax.saxutils import quoteattr

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


def detect_fm_graphics_collision(dir_a: Path | None, dir_b: Path | None) -> bool:
    """Return True if two distinct folders share a common Football Manager 'graphics' ancestor directory."""
    if dir_a is None or dir_b is None:
        return False
    ra, rb = dir_a.resolve(), dir_b.resolve()
    if ra == rb:
        return False
    ancestors_a = {ra, *ra.parents}
    shared = [p for p in (rb, *rb.parents) if p in ancestors_a]
    return any(p.name.lower() == "graphics" for p in shared)


def upsert_fm_config_xml(config_path: Path, uids: Iterable[str]) -> int:
    """Idempotently merge portrait mappings for uids into config.xml using atomic NTFS replace."""
    validated = list(dict.fromkeys(validate_fm_uid(u) for u in uids))
    records_by_to: dict[str, str] = {}
    preload_val = "false"
    amap_val = "false"

    if config_path.is_file():
        duplicate_to_found = False
        try:
            tree = SafeET.parse(config_path)
            root = tree.getroot()
            for btag in root.findall("./boolean"):
                bid = btag.attrib.get("id", "").strip()
                bval = btag.attrib.get("value", "").strip().lower()
                if bid == "preload" and bval in ("true", "false"):
                    preload_val = bval
                elif bid == "amap" and bval in ("true", "false"):
                    amap_val = bval
            for rec in root.findall(".//record"):
                frm = rec.attrib.get("from", "").strip()
                to = rec.attrib.get("to", "").strip()
                if not frm or not to:
                    continue
                if to in records_by_to and records_by_to[to] != frm:
                    duplicate_to_found = True
                records_by_to[to] = frm
        except Exception as exc:
            raise FMConfigError(f"No se pudo leer config.xml de forma segura: {exc}") from exc
        if (
            validated
            and not duplicate_to_found
            and all(records_by_to.get(f"graphics/pictures/person/{u}/portrait") == u for u in validated)
        ):
            return len(records_by_to)

    for uid in validated:
        records_by_to[f"graphics/pictures/person/{uid}/portrait"] = uid

    lines = [
        "<record>",
        f'\t<boolean id="preload" value={quoteattr(preload_val)}/>',
        f'\t<boolean id="amap" value={quoteattr(amap_val)}/>',
        '\t<list id="maps">',
    ]
    sorted_pairs = sorted(
        ((frm, to) for to, frm in records_by_to.items()),
        key=lambda item: (item[0].startswith("r-"), item[0], item[1]),
    )
    for frm, to in sorted_pairs:
        lines.append(f"\t\t<record from={quoteattr(frm)} to={quoteattr(to)}/>")
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
    return len(records_by_to)
