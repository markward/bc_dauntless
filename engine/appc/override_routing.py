"""Route a ship's hardpoint override edits to the right destination.

A mod-supplied ships/Hardpoints/<leaf>.py owns its own ship's edits; every
other ship routes to the engine-owned aggregated file
engine/appc/hardpoint_overrides.py (spec 2026-09-26 section 3).
"""
from __future__ import annotations

import importlib
import os
import shutil

from engine import mods as _mods
from engine.appc import hardpoint_override_writer as _writer
from engine.appc import mod_hardpoint_writer as _mod_writer

_PATH = os.path.join(os.path.dirname(__file__), "hardpoint_overrides.py")


def hardpoint_leaf_for_ship(ship) -> "str | None":
    getter = getattr(ship, "GetScript", None)
    if getter is None:
        return None
    try:
        script_name = getter()
    except Exception:
        return None
    if not script_name:
        return None
    try:
        mod = importlib.import_module(script_name)
        leaf = mod.GetShipStats().get("HardpointFile")
    except Exception:
        return None
    return leaf or None


class HardpointOverridesFileTarget:
    def __init__(self, path: str = _PATH) -> None:
        self.path = path

    def write(self, leaf, edits) -> None:
        """edits: list of (subsystem, setter, args) 3-tuples, (name,
        "__part__", calls) 3-tuples, and/or (subsystem, "__region__", index,
        calls) / (subsystem, "__emitter__", index, calls) 4-tuples.
        Reload → apply → emit → atomic."""
        import types
        with open(self.path, "r", encoding="utf-8") as fh:
            src = fh.read()
        module = types.ModuleType("_ho_load")
        exec(compile(src, self.path, "exec"), module.__dict__)  # noqa: S102
        models = _writer.read_models(module)
        for edit in edits:
            _writer.apply_edit(models, leaf, edit)
        text = _writer.emit(models)          # raises on a bad emit
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path)

    def describe(self) -> str:
        return "hardpoint_overrides.py"


class ModHardpointFileTarget:
    """Writes SPV edits into a mod's own ships/Hardpoints/<leaf>.py
    (spec 2026-09-26). Encoding and line endings are preserved: the file is
    read as UTF-8, falling back to Latin-1 (which round-trips any byte), and
    written back in the same encoding with newline translation off."""

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def describe(self) -> str:
        return "mod file: " + self.path

    def write(self, leaf, edits) -> None:
        with open(self.path, "rb") as fh:
            raw = fh.read()
        try:
            text, enc = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, enc = raw.decode("latin-1"), "latin-1"
        new_text = _mod_writer.rewrite(text, leaf, edits)   # raises on any problem
        orig = self.path + ".orig"
        if not os.path.exists(orig):
            shutil.copy2(self.path, orig)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(new_text.encode(enc))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def resolve_override_target(ship):
    """A mod-supplied hardpoint file owns its ship's edits; stock ships go to
    hardpoint_overrides.py (spec 2026-09-26 section 3)."""
    leaf = hardpoint_leaf_for_ship(ship)
    if leaf:
        path = _mods.sdk_override("ships/Hardpoints/%s.py" % leaf)
        if path is not None:
            return ModHardpointFileTarget(str(path))
    return HardpointOverridesFileTarget()
