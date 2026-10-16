"""Glow-map switches (spec 2026-10-16 §6.2, §6.3).

Two stock Appc surfaces:
- DamageableObject.DisableGlowAlphaMaps(): one object's self-illumination
  (hull emissive + glow map) and running lights go dark. Stock BC has no
  Enable counterpart; enable_object() is Dauntless-internal (the legacy FX
  API's flicker uses it).
- g_kLODModelManager.Set/AreGlowMapsEnabled, Set/AreSpecularMapsEnabled:
  global flags. Glow off darkens every object.

ASSUMPTION (spec §6.3, not recovered from the binary): turning global glow
back ON clears every per-object disable -- NanoFX's TurnOnLights toggles glow
off/on precisely to relight ships. Implemented with an epoch: a disable
records the current epoch; an off->on transition bumps it, so every older
disable lapses without a registry of objects.
"""
from __future__ import annotations

_glow_enabled = True
_specular_enabled = True
_epoch = 0
_ATTR = "_glow_disabled_epoch"


def disable_object(obj) -> None:
    obj.__dict__[_ATTR] = _epoch


def enable_object(obj) -> None:
    obj.__dict__.pop(_ATTR, None)


def is_dark(obj) -> bool:
    if not _glow_enabled:
        return True
    # __dict__, never getattr: TGObject.__getattr__ hands back a truthy stub
    # for a missing attribute.
    return getattr(obj, "__dict__", {}).get(_ATTR) == _epoch


def set_glow_enabled(on) -> None:
    global _glow_enabled, _epoch
    on = bool(on)
    if on and not _glow_enabled:
        _epoch += 1
    _glow_enabled = on


def glow_enabled() -> bool:
    return _glow_enabled


def set_specular_enabled(on) -> None:
    global _specular_enabled
    _specular_enabled = bool(on)


def specular_enabled() -> bool:
    return _specular_enabled


def reset() -> None:
    global _glow_enabled, _specular_enabled, _epoch
    _glow_enabled = True
    _specular_enabled = True
    _epoch += 1
