"""Persistent galaxy data model + identity helpers.

Owns sector_model.json (galaxy systems/nebulae/starclouds + the baked
per-system warp_points catalog). The sky renderer (sky_projection.py) and the
Set Course popup both consume this; neither depends on the other.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).with_name("sector_model.json")

# Synthetic members folded under one star (mirrors the extractor).
_MEMBER_TO_PARENT = {"drydock": "tauceti", "starbase12": "tauceti"}

# SDK multiplayer menu labels "MRegion1"–"MRegion7" map to the model's
# "multi1"–"multi7" ids (the display name is "MRegion" + digit; stripping the
# digit would collapse them all to "mregion").
_MEMBER_TO_PARENT.update({
    "mregion1": "multi1", "mregion2": "multi2", "mregion3": "multi3",
    "mregion4": "multi4", "mregion5": "multi5", "mregion6": "multi6",
    "mregion7": "multi7",
    # Display names with spaces that the TGL localizer returns for these ids.
    "omega draconis": "omegadraconis",
    "xi entrades": "xientrades",
    "deep space": "deepspace",
    "tau ceti": "tauceti",
})

# Display-name overrides where title-casing the id is wrong.
_LABEL_OVERRIDES = {
    "xientrades": "Xi Entrades",
    "omegadraconis": "Omega Draconis",
    "tauceti": "Tau Ceti",
    "deepspace": "Deep Space",
}


@lru_cache(maxsize=1)
def load_sector_model():
    try:
        return json.loads(_MODEL_PATH.read_text())
    except (OSError, ValueError):
        return {"systems": [], "nebulae": [], "starclouds": []}


def system_id_for_set(set_name):
    name = str(set_name).lower()
    if name in _MEMBER_TO_PARENT:
        return _MEMBER_TO_PARENT[name]
    base = re.sub(r"\d+$", "", name)        # "vesuvi6" -> "vesuvi"
    return _MEMBER_TO_PARENT.get(base, base)


def vantage_for_set(pSet, model=None):
    if pSet is None:
        return None
    model = model or load_sector_model()
    sysid = system_id_for_set(pSet.GetName())
    for s in model.get("systems", []):
        if s["id"] == sysid:
            return s["position"]
    return None


@lru_cache(maxsize=1)
def _systems_tgl_labels():
    """Case-insensitive {galaxy_id: display_name} index from Systems.TGL
    (e.g. 'omegadraconis' -> 'Omega Draconis'), or {} if unavailable.
    Description entries are skipped; keys are lowercased to match galaxy ids."""
    try:
        from engine.appc.sets import _systems_tgl
        db = _systems_tgl()
        strings = getattr(db, "_strings", None) or getattr(db, "strings", None)
        if not strings:
            return {}
        return {k.lower(): v for k, v in strings.items()
                if not k.endswith(" Description")}
    except Exception:
        return {}


def display_label(system_id):
    sid = str(system_id)
    # Authentic system names come from Systems.TGL (e.g. 'omegadraconis' ->
    # 'Omega Draconis'); fall back to the override map, then to title-case,
    # so the label still resolves when game/ (and its TGL) is absent.
    tgl = _systems_tgl_labels().get(sid)
    if tgl:
        return tgl
    if sid in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[sid]
    return sid.replace("_", " ").title()


def is_real_system(system_id):
    """multi* ids are map scaffolding, not user-facing destinations."""
    return not str(system_id).startswith("multi")


def warp_points_for(system_id, model=None):
    model = model or load_sector_model()
    for s in model.get("systems", []):
        if s["id"] == system_id:
            return list(s.get("warp_points", []))
    return []


def system_module(system_id):
    """Set-module name for a system's own set, or None if it has none."""
    for s in load_sector_model().get("systems", []):
        if s.get("id") == system_id:
            return s.get("module")
    return None
