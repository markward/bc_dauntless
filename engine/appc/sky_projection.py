"""Project the sector model into camera-anchored backdrop descriptors.

The in-game sky is a view of the persistent galaxy model from the current
system's position. See docs/superpowers/specs/2026-06-20-map-driven-starsphere-design.md.
"""
import json
import math
import re
import zlib
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).with_name("sector_model.json")

# Synthetic members folded under one star (mirrors the extractor's SYNTHETIC_SYSTEMS).
_MEMBER_TO_PARENT = {"drydock": "tauceti", "starbase12": "tauceti"}


@lru_cache(maxsize=1)
def load_sector_model():
    try:
        return json.loads(_MODEL_PATH.read_text())
    except (OSError, ValueError):
        return {"systems": [], "nebulae": [], "starclouds": []}


def system_id_for_set(set_name):
    name = set_name.lower()
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
