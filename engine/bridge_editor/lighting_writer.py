"""Deterministic, atomic writer for the per-bridge lighting document (spec
2026-10-08-bridge-emitters §7): sorted keys, floats rounded to 6 dp, 2-space
indent, trailing newline; written to `<path>.tmp` then os.replace'd, so a
crash never leaves half a file. load -> save is byte-identical."""
import json
import os
from pathlib import Path
from typing import Optional

from engine.bridge_editor import lighting_doc as ld

_DP = 6


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        r = round(v, _DP)
        return int(r) if r.is_integer() else r
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return v


def dumps(doc) -> str:
    return json.dumps(_norm(doc), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def target_path(found: Optional[Path], content_hash) -> Path:
    """Save where the file was found; a bridge with no file saves to the
    project directory (the decals_writer target rule)."""
    return found if found is not None else ld.project_dir() / f"{content_hash}.json"


def save(doc, path) -> None:
    ld.validate(doc)
    path = Path(path)
    from engine import paths
    paths.refuse_repo_write_when_packaged(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(dumps(doc), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
