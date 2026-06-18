"""Regression: docking against Starbase 12 must resolve the named
``PositionOrientationProperty`` mounts on the starbase hull.

E1M1 logs ``swallowed exception [character SendActivationEvent]:
AttributeError('Object (Starbase 12) has no position/orientation property
(Docking Entry Start)')`` because ``MissionLib.GetPositionOrientationFromProperty``
returned ``(None, None, None)`` even though the fedstarbase hardpoint
defines a "Docking Entry Start" property and ``LoadPropertySet`` adds it
to the ship's property set.

Two root causes, both exercised here:

1. ``App.PositionOrientationProperty_Cast`` was undefined, so the SDK's
   ``pProperty = App.PositionOrientationProperty_Cast(...)`` fell through
   to a ``_NamedStub`` (truthy) instead of the real property.
2. ``TGModelProperty.GetName()`` returned a plain ``str``, which has no
   ``CompareC`` — the SDK matches names via
   ``pProperty.GetName().CompareC(name, 1)``.

See ``sdk/Build/scripts/AI/Compound/DockWithStarbase.py:308`` (the call
site) and ``sdk/Build/scripts/MissionLib.py:1807`` (the lookup).
"""
import importlib
import sys

import App
import tools.mission_harness as mh
from engine.appc.properties import PositionOrientationProperty


def _make_starbase_with_hardpoint():
    """Mirror loadspacehelper.CreateShip property loading for the starbase."""
    mh.setup_sdk()
    pShip = App.ShipClass_Create("Starbase 12")
    pPropertySet = pShip.GetPropertySet()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop("ships.Hardpoints.fedstarbase", None)
    mod = importlib.import_module("ships.Hardpoints.fedstarbase")
    mod.LoadPropertySet(pPropertySet)
    return pShip


def test_position_orientation_property_cast_returns_real_property():
    """Root cause 1: the cast must return the property, not a stub."""
    prop = PositionOrientationProperty("Docking Entry Start")
    assert App.PositionOrientationProperty_Cast(prop) is prop


def test_position_orientation_property_cast_rejects_wrong_type():
    assert App.PositionOrientationProperty_Cast(object()) is None
    assert App.PositionOrientationProperty_Cast(None) is None


def test_property_name_supports_caseinsensitive_comparec():
    """Root cause 2: GetName() must expose the SDK TGString CompareC, with
    C strcmp semantics (0 == equal). The SDK passes flag 1 for
    case-insensitive matching."""
    prop = PositionOrientationProperty("Docking Entry Start")
    name = prop.GetName()
    assert name.CompareC("Docking Entry Start", 1) == 0
    assert name.CompareC("docking entry start", 1) == 0   # case-insensitive
    assert name.CompareC("Docking Entry End", 1) != 0


def test_get_position_orientation_from_property_resolves_docking_mount():
    """End-to-end: the exact lookup DockWithStarbase performs must return
    real (position, forward, up) vectors for "Docking Entry Start"."""
    import MissionLib
    pShip = _make_starbase_with_hardpoint()
    vPos, vFwd, vUp = MissionLib.GetPositionOrientationFromProperty(
        pShip, "Docking Entry Start"
    )
    assert vPos is not None
    assert vFwd is not None
    assert vUp is not None
    # fedstarbase.py:666 — DockingEntryStart position.
    assert (round(vPos.x, 3), round(vPos.y, 3), round(vPos.z, 3)) == (
        -72.433, -77.782, 19.030,
    )
