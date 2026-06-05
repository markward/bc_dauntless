"""DamageDisplay atlas tracer + subsystem-class → enum mapping.

BC's damage display picks a glyph per-subsystem at instantiation
time based on the subsystem's C++ type — see the comment in
``sdk/Build/scripts/Icons/DamageIcons.py:17`` ("Icon numbers should
match up with DamageIcon::DamageIcons enum"). We mirror that with
an explicit Python class table.

Glyph sources live as standalone 16x16 TGAs under
``game/data/Icons/Damage/`` (Hull.tga, Impulse.tga, ...). Trace
pipeline is the shared ``engine.ui.icon_tracer`` flow used by
``engine.ui.weapon_icons``. Cache: ``cache/icons/damage/{num}.svg``.
Curated overrides: ``native/assets/ui-cef/icons/damage/{num}.svg``.
"""
from __future__ import annotations

import os

from engine.appc import subsystems as ss
from engine.ui.icon_tracer import IconSpec


_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_DAMAGE_DIR = os.path.join(_PROJECT_ROOT, "game", "data", "Icons", "Damage")
_CURATED_DIR = os.path.join(
    _PROJECT_ROOT, "native", "assets", "ui-cef", "icons", "damage",
)
_SVG_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "icons", "damage")


# Damage TGAs are 16x16 standalone files (not an atlas), so every
# IconSpec uses (0, 0, 16, 16) with no transform. Numbers mirror the
# DamageIcons enum at sdk/Build/scripts/Icons/DamageIcons.py:17-56.
ICON_REGISTRY: dict[int, IconSpec] = {
    0: IconSpec("Hull.tga",     0, 0, 16, 16),
    1: IconSpec("Impulse.tga",  0, 0, 16, 16),
    2: IconSpec("Phaser.tga",   0, 0, 16, 16),
    3: IconSpec("Power.tga",    0, 0, 16, 16),
    4: IconSpec("Sensor.tga",   0, 0, 16, 16),
    5: IconSpec("Shield.tga",   0, 0, 16, 16),
    6: IconSpec("System.tga",   0, 0, 16, 16),
    7: IconSpec("Torpedo.tga",  0, 0, 16, 16),
    8: IconSpec("Warp.tga",     0, 0, 16, 16),
    9: IconSpec("Disruptor.tga", 0, 0, 16, 16),
}


# Class → enum. First matching isinstance wins, so order subclasses
# before their superclasses if any are listed. The default fallback
# is 6 (System) per the SDK comment.
_CLASS_TABLE: tuple = (
    (ss.HullSubsystem,          0),
    (ss.ImpulseEngineSubsystem, 1),
    (ss.PhaserBank,             2),
    (ss.PowerSubsystem,         3),
    (ss.SensorSubsystem,        4),
    (ss.ShieldSubsystem,        5),
    (ss.TorpedoTube,            7),
    (ss.WarpEngineSubsystem,    8),
    (ss.PulseWeapon,            9),
)


def icon_num_for_subsystem(sub) -> int:
    """Returns the BC DamageIcons enum value for a ShipSubsystem.
    Unknown / None / non-subsystem inputs fall back to 6 (System)."""
    if sub is None:
        return 6
    for cls, num in _CLASS_TABLE:
        if isinstance(sub, cls):
            return num
    return 6
