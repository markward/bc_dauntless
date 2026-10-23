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
    # A stock ship's lights other than the ones this file creates are
    # templates from the game's own hardpoint file, keyed by name: only a
    # created light may be renamed (writer.rename_running_light).
    renames_any_light = False

    def __init__(self, path: str = _PATH, live_module=None) -> None:
        self.path = path
        self._live_module = live_module

    def write(self, leaf, edits) -> None:
        """edits: list of (subsystem, setter, args) 3-tuples, (name,
        "__part__", calls) 3-tuples, and/or (subsystem, "__region__", index,
        calls) / (subsystem, "__emitter__", index, calls) 4-tuples.
        Reload → apply → emit → atomic."""
        import types
        from engine import paths
        paths.refuse_repo_write_when_packaged(self.path)
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
        self._refresh_live(text)

    def _refresh_live(self, text: str) -> None:
        """Make the saved edit take effect on the next CreateShip: swap the
        live module's OVERRIDES for the freshly executed one. Only the real
        file refreshes by default; the live module is untouched on failure."""
        live = self._live_module
        if live is None:
            if self.path != _PATH:
                return
            from engine.appc import hardpoint_overrides as live
        try:
            ns: dict = {}
            exec(compile(text, self.path, "exec"), ns)  # noqa: S102
            new_overrides = ns["OVERRIDES"]
        except Exception as exc:
            raise RuntimeError("saved, but reload failed: %s" % (exc,)) from exc
        live.OVERRIDES = new_overrides

    def describe(self) -> str:
        return "hardpoint_overrides.py"


class ModHardpointFileTarget:
    """Writes SPV edits into a mod's own ships/Hardpoints/<leaf>.py
    (spec 2026-09-26). Encoding and line endings are preserved: the file is
    read as UTF-8, falling back to Latin-1 (which round-trips any byte), and
    written back in the same encoding with newline translation off."""

    # The mod file is fully rewritable: any light in it may be renamed.
    renames_any_light = True

    def __init__(self, path: str) -> None:
        # Resolve symlinks so .orig/.tmp/os.replace all act on the real file:
        # os.replace onto a link would swap the link for a regular file.
        self.path = os.path.realpath(str(path))

    def describe(self) -> str:
        return "mod file: " + self.path

    def write(self, leaf, edits) -> None:
        # Known limitation: the SDK loader decodes mod files as UTF-8 with
        # errors="replace", so a subsystem name containing non-UTF-8 (e.g.
        # Latin-1) bytes reaches the SPV as U+FFFD and cannot be matched in
        # the file. Such a save fails safely -- encoding U+FFFD back to
        # Latin-1 raises, which the SPV reports as a "Save failed" toast.
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
