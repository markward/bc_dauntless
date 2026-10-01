"""Write the Mods screen's answers into a mod (spec 2026-10-01 mod ships §3).

One zz_Dauntless_<shipFile>.py per ship, beside the mod's own Custom/Ships
scripts (so the Foundation loader's filename order runs it LAST), guarded and
Python 1.5-safe so the same mod still loads in the original BC. After the
atomic write the file is added to the mod index and run in-process under
plugin_origin, so no reboot is needed.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

_KEY_ORDER = ("title", "species", "era", "role", "playable", "variant_of", "class_default")


class GateWriteError(Exception):
    """A write that could not complete; the message names the file."""


def _lit(s) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _value(key, v) -> str:
    if key == "era":
        return _lit("all") if tuple(v) == ("all",) else "(%s, %s)" % (_lit(v[0]), _lit(v[1]))
    if key in ("playable", "class_default"):
        return "1" if v else "0"
    return _lit(v)


def render(attr: str, answers: dict) -> str:
    items = []
    for key in _KEY_ORDER:
        if key not in answers or answers[key] is None:
            continue
        if key == "class_default" and not answers[key]:
            continue
        items.append("        %s: %s," % (_lit(key), _value(key, answers[key])))
    return ("# Written by Dauntless's Mod Ships screen. Safe to delete: the\n"
            "# screen will ask again.\n"
            "import Foundation\n"
            "if hasattr(Foundation.ShipDef, %s):\n"
            "    d = Foundation.ShipDef.%s\n"
            "    if not hasattr(d, 'dauntless'):\n"
            "        d.dauntless = {}\n"
            "    d.dauntless.update({\n%s\n    })\n") % (_lit(attr), attr, "\n".join(items))


def ships_dir(mod_name: str):
    """(absolute Custom/Ships dir, raw-rel prefix) for `mod_name`, in the
    mod's own spelling when it already has a Custom/Ships script."""
    from engine import mods
    for key, mf in sorted(mods.current().files.items()):
        if (mf.mod_name == mod_name and mf.target == "sdk"  # paths-guard: kind label
                and key.startswith("custom/ships/") and key.endswith(".py")):
            prefix = mf.raw_rel.rsplit("/", 1)[0]
            return mf.abs_path.parent, prefix
    for status in mods.current().mods:
        if status.name == mod_name and status.content_root is not None:
            return status.content_root / "scripts" / "Custom" / "Ships", "Custom/Ships"  # paths-guard: mod content layout
    raise GateWriteError("mod %r has no content root to write into" % mod_name)


def write_answers(mod_name: str, ship_id: str, attr, answers: dict) -> Path:
    from engine import mods
    from engine.foundation.shipdef import plugin_origin
    if not attr:
        raise GateWriteError("%s has no Foundation.ShipDef name to write against" % ship_id)
    directory, prefix = ships_dir(mod_name)
    name = "zz_Dauntless_%s.py" % ship_id
    path = directory / name
    tmp = directory / (name + ".tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp.write_text(render(attr, answers), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise GateWriteError("%s: %s" % (path, exc)) from exc
    raw_rel = "%s/%s" % (prefix, name)
    mods.register_sdk_file(raw_rel, path, mod_name)
    with plugin_origin(mod_name, mods.fold(raw_rel)):
        runpy.run_path(str(path), run_name="__foundation__")
    return path
