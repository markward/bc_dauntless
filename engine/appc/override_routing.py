"""Route a ship's hardpoint override edits to the right destination.

Today every (game) ship routes to the engine-owned aggregated file
engine/appc/hardpoint_overrides.py. The seam exists so modded ships can later
route to their own files without the SPV/UI changing.
"""
from __future__ import annotations

import importlib
import os

from engine.appc import hardpoint_override_writer as _writer

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
        """edits: list of (subsystem, setter, args). Reload → apply → emit → atomic."""
        import types
        with open(self.path, "r", encoding="utf-8") as fh:
            src = fh.read()
        module = types.ModuleType("_ho_load")
        exec(compile(src, self.path, "exec"), module.__dict__)  # noqa: S102
        models = _writer.read_models(module)
        for subsystem, setter, args in edits:
            _writer.set_setter(models, leaf, subsystem, setter, args)
        text = _writer.emit(models)          # raises on a bad emit
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path)


def resolve_override_target(ship) -> HardpointOverridesFileTarget:
    # future: modded ships → a target writing into the mod's files.
    return HardpointOverridesFileTarget()
