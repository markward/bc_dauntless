"""Dialogue patches: insert lines after a scripted line, replace a line's
text and/or sound -- at runtime, without editing the SDK.

Spec: docs/superpowers/specs/2026-10-07-dialogue-patches-design.md.
Data: native/assets/dialogue/patches.json, keyed by the TGL a line is read
from (game-root-relative, matched case-insensitively, either slash):

    {"data/TGL/Maelstrom/Episode 1/E1M2.TGL": {
        "insert_after": {"<anchor key>": [{"speaker": "<set>/<object>",
                                           "key": "<line key>",
                                           "tgl": "<optional other TGL>"}]},
        "replace": {"<key>": {"text": "...", "sound": "sfx/..."}}}}

Resolved at use and re-read when the file changes. A missing or malformed
file means no patches: BC plays unchanged and the problem is dev-logged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import engine.dev_mode as dev_mode

_SPEAKER = re.compile(r"^[^/]+/[^/]+$")
_ENTRY_KEYS = {"insert_after", "replace"}
_INSERT_KEYS = {"speaker", "key", "tgl"}
_REPLACE_KEYS = {"text", "sound"}

_cache = None   # (path, mtime_ns, table)


def patches_path() -> Path:
    from engine import paths
    return paths.project_asset_root() / "dialogue" / "patches.json"


def norm_tgl(path) -> str:
    return str(path).replace("\\", "/").lower()


def reset_cache() -> None:
    global _cache
    _cache = None


def table() -> dict:
    global _cache
    path = patches_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache is not None and _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_shape(raw)
        if errors:
            raise ValueError("; ".join(errors))
        loaded = {norm_tgl(tgl): {"insert_after": entry.get("insert_after", {}),
                                  "replace": entry.get("replace", {})}
                  for tgl, entry in raw.items()}
    except Exception as exc:
        dev_mode.log_swallowed("dialogue patches load %s" % path, exc)
        loaded = {}
    _cache = (path, mtime, loaded)
    return loaded


def inserts_for(tgl, key) -> list:
    if not tgl or key is None:
        return []
    return table().get(norm_tgl(tgl), {}).get("insert_after", {}).get(str(key), [])


def replacements_for(tgl) -> dict:
    if not tgl:
        return {}
    return table().get(norm_tgl(tgl), {}).get("replace", {})


def validate_shape(raw) -> list:
    if not isinstance(raw, dict):
        return ["top level must be an object keyed by TGL path"]
    errors = []
    for tgl, entry in raw.items():
        if not isinstance(entry, dict) or set(entry) - _ENTRY_KEYS:
            errors.append("%s: only 'insert_after' and 'replace' are allowed" % tgl)
            continue
        inserts = entry.get("insert_after", {})
        if not isinstance(inserts, dict):
            errors.append("%s: insert_after must be an object" % tgl)
            inserts = {}
        for anchor, lines in inserts.items():
            if not isinstance(lines, list) or not lines:
                errors.append("%s: %s: inserts must be a non-empty list" % (tgl, anchor))
                continue
            for ins in lines:
                if (not isinstance(ins, dict) or set(ins) - _INSERT_KEYS
                        or not isinstance(ins.get("key"), str)
                        or not isinstance(ins.get("tgl", ""), str)):
                    errors.append("%s: %s: insert needs 'speaker' and 'key' (optional 'tgl'): %r"
                                  % (tgl, anchor, ins))
                elif not _SPEAKER.match(str(ins.get("speaker", ""))):
                    errors.append("%s: %s: speaker must be '<set>/<object>': %r"
                                  % (tgl, anchor, ins.get("speaker")))
        replaces = entry.get("replace", {})
        if not isinstance(replaces, dict):
            errors.append("%s: replace must be an object" % tgl)
            replaces = {}
        for key, rep in replaces.items():
            if (not isinstance(rep, dict) or not rep or set(rep) - _REPLACE_KEYS
                    or not all(isinstance(v, str) for v in rep.values())):
                errors.append("%s: replace %s needs 'text' and/or 'sound' strings" % (tgl, key))
    return errors


# ── Insertion (called from CharacterAction.Completed, engine/appc/ai.py) ────

def insert_actions(anchor) -> list:
    """AT_SAY_LINE CharacterActions for the lines patched in after `anchor`,
    in order. An insert whose speaker is absent or whose line is not in its
    database is skipped (dev-logged). [] when nothing applies."""
    db = getattr(anchor, "_database", None)
    getter = getattr(db, "GetSourceFilename", None)
    tgl = getter() if callable(getter) else ""
    out = []
    for ins in inserts_for(tgl, getattr(anchor, "_detail", None)):
        try:
            out.append(_build_insert(ins, db))
        except Exception as exc:
            dev_mode.log_swallowed("dialogue patch insert %s" % ins.get("key"), exc)
    return out


def _build_insert(ins, anchor_db):
    import App
    from engine.appc.ai import CharacterAction
    from engine.appc.characters import CharacterClass_GetObjectStrict
    set_name, obj_name = ins["speaker"].split("/", 1)
    speaker = CharacterClass_GetObjectStrict(App.g_kSetManager.GetSet(set_name), obj_name)
    if speaker is None:
        raise LookupError("speaker %s is not present" % ins["speaker"])
    db = App.g_kLocalizationManager.Load(ins["tgl"]) if ins.get("tgl") else anchor_db
    if db is None or not db.HasString(ins["key"]):
        raise LookupError("line %s is not in its database" % ins["key"])
    # BC's own forms: bridge crew address the captain and turn; a viewscreen
    # speaker (E1M2's Soams) does not.
    addressee, flag = ("Captain", 1) if set_name == "bridge" else (None, 0)
    return CharacterAction(speaker, CharacterAction.AT_SAY_LINE, ins["key"],
                           addressee, flag, db)


def play_then(actions, fn):
    """Play `actions` in order, then call fn(). Returns the sequence, so the
    caller can Abort() it (fn is then never called)."""
    from engine.appc.actions import TGAction, TGSequence_Create

    class _Then(TGAction):
        def _do_play(self):
            fn()

    seq = TGSequence_Create()
    for action in actions:
        seq.AppendAction(action)
    seq.AppendAction(_Then())
    seq.Play()
    return seq
