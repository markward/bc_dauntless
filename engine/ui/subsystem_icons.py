"""Subsystem -> icon key and SVG text for the target panel."""
import os
from typing import Optional

from engine.appc import subsystems as ss
from engine.appc import weapon_subsystems as ws

FALLBACK_KEY = "boxes-linked"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_ICON_DIR = os.path.join(
    _PROJECT_ROOT, "native", "assets", "ui-cef", "icons", "subsystems",
)

ICON_KEYS = frozenset({
    "radar", "chevrons-up", "margin-horizontal", "warp-pod", "test-tubes",
    "laser", "loader", "wand-sparkles", "eye-off", "shield-plus", "zap",
    "boxes-linked", "hull",
})

_TABLE = (
    (ss.HullSubsystem, "hull"),
    (ss.SensorSubsystem, "radar"),
    (ss.ImpulseEngineSubsystem, "chevrons-up"),
    (ss.WarpEngineSubsystem, "margin-horizontal"),
    (ss.ShieldSubsystem, "shield-plus"),
    (ss.PowerSubsystem, "zap"),
    (ss.CloakingSubsystem, "eye-off"),
    (ws.TorpedoSystem, "test-tubes"),
    (ws.TorpedoTube, "test-tubes"),
    (ws.PulseWeaponSystem, "loader"),
    (ws.PulseWeapon, "loader"),
    (ws.TractorBeamSystem, "wand-sparkles"),
    (ws.TractorBeam, "wand-sparkles"),
    (ws.PhaserSystem, "laser"),
    (ws.PhaserBank, "laser"),
)

_cache = {}


def icon_key_for(sub) -> str:
    if sub is None:
        return FALLBACK_KEY
    for cls, key in _TABLE:
        if isinstance(sub, cls):
            return key
    parent = sub.GetParentSubsystem()
    if isinstance(parent, ss.ImpulseEngineSubsystem):
        return "chevrons-up"
    if isinstance(parent, ss.WarpEngineSubsystem):
        return "warp-pod"
    return FALLBACK_KEY


def svg_for_key(key: str) -> Optional[str]:
    if key not in ICON_KEYS:
        return None
    if key not in _cache:
        with open(os.path.join(_ICON_DIR, key + ".svg"), encoding="utf-8") as f:
            _cache[key] = f.read()
    return _cache[key]
