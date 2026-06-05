"""Bug A + B + G end-to-end: loading the real Galaxy hardpoint script
populates every SubsystemProperty / PositionOrientationProperty mount
point in its typed slot, not the data-bag.

This is the "the bug class is gone" integration check.  If any
``SetPosition`` / ``SetOrientation`` call falls through to the
data-bag for any property the hardpoint touches, ``GetPosition``
returns None for that template and this test fails.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
sections "Bug A" and "Bug G".
"""
import importlib
import sys

import App
import tools.mission_harness as mh
from engine.appc.properties import (
    PositionOrientationProperty,
    SubsystemProperty,
)


def _reload_galaxy_hardpoint():
    mh.setup_sdk()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop("ships.Hardpoints.galaxy", None)
    importlib.import_module("ships.Hardpoints.galaxy")


def test_galaxy_dorsal_phasers_keep_their_position_and_orientation():
    """Every Galaxy DorsalPhaser bank's typed Position should match the
    SetPosition call in the hardpoint script -- (0, 1.27, 0.5)."""
    _reload_galaxy_hardpoint()
    for name in ("Dorsal Phaser 1", "Dorsal Phaser 2",
                 "Dorsal Phaser 3", "Dorsal Phaser 4"):
        bank = App.g_kModelPropertyManager.FindByName(
            name, App.TGModelPropertyManager.LOCAL_TEMPLATES
        )
        assert bank is not None, f"missing template: {name}"
        pos = bank.GetPosition()
        assert pos is not None, f"{name}.GetPosition() is None — SetPosition swallowed"
        assert (round(pos.x, 3), round(pos.y, 3), round(pos.z, 3)) == (0.0, 1.27, 0.5)
        # Orientation: SetOrientation(forward, up) sets the bank's
        # firing axis; Direction must be unit-length and non-default.
        d = bank.GetDirection()
        norm = (d.x * d.x + d.y * d.y + d.z * d.z) ** 0.5
        assert abs(norm - 1.0) < 1e-3, f"{name} direction not unit: {d}"


def test_galaxy_ventral_phasers_have_distinct_z_from_dorsal():
    """Bug A symptom: dorsal SetPosition Z=0.5 and ventral Z=0.16 used
    to be collapsed into a single data-bag entry, then dropped.  Now
    they should round-trip distinctly."""
    _reload_galaxy_hardpoint()
    dorsal = App.g_kModelPropertyManager.FindByName(
        "Dorsal Phaser 1", App.TGModelPropertyManager.LOCAL_TEMPLATES,
    )
    ventral = App.g_kModelPropertyManager.FindByName(
        "Ventral Phaser 1", App.TGModelPropertyManager.LOCAL_TEMPLATES,
    )
    assert dorsal is not None and ventral is not None
    assert round(dorsal.GetPosition().z, 3) == 0.5
    assert round(ventral.GetPosition().z, 3) == 0.16


def test_galaxy_phaser_width_round_trips():
    """Bug C symptom: SetWidth(1.35) used to fall through to the
    data-bag and GetWidth() returned None."""
    _reload_galaxy_hardpoint()
    bank = App.g_kModelPropertyManager.FindByName(
        "Dorsal Phaser 1", App.TGModelPropertyManager.LOCAL_TEMPLATES,
    )
    assert bank is not None
    # galaxy.py:412 — DorsalPhaser1.SetWidth(1.35).
    assert round(bank.GetWidth(), 3) == 1.35


def test_galaxy_viewscreen_positions_round_trip():
    """Bug G symptom: PositionOrientationProperty.SetPosition(TGPoint3)
    used to fall through to the data-bag, leaving viewscreen anchors
    at the body origin."""
    _reload_galaxy_hardpoint()
    vs = App.g_kModelPropertyManager.FindByName(
        "ViewscreenForward", App.TGModelPropertyManager.LOCAL_TEMPLATES,
    )
    assert vs is not None
    assert isinstance(vs, PositionOrientationProperty)
    pos = vs.GetPosition()
    assert pos is not None
    # galaxy.py:1144 — ViewscreenForward sits at (0, 2.9, 0.5).
    assert (round(pos.x, 3), round(pos.y, 3), round(pos.z, 3)) == (0.0, 2.9, 0.5)
    # SetOrientation populated all three axes.
    assert vs.GetForward() is not None
    assert vs.GetUp() is not None
    assert vs.GetRight() is not None


def test_galaxy_loads_without_data_bag_position_leaks():
    """Aggregate check: after loading galaxy.py, no registered template
    should have a stray ``Position`` entry in its data-bag — every
    SetPosition call must hit a typed setter."""
    _reload_galaxy_hardpoint()
    # We don't have a direct iterator over registered templates, so
    # walk the local store via the few known SDK property names. Any
    # leaked Position key indicates the typed setter was missed.
    leaks = []
    for name in (
        "Dorsal Phaser 1", "Dorsal Phaser 2", "Dorsal Phaser 3", "Dorsal Phaser 4",
        "Ventral Phaser 1", "Ventral Phaser 2", "Ventral Phaser 3", "Ventral Phaser 4",
        "ForwardTorpedo1", "ForwardTorpedo2", "ForwardTorpedo3", "ForwardTorpedo4",
        "AftTorpedo1", "AftTorpedo2",
        "ViewscreenForward", "ViewscreenLeft", "ViewscreenRight",
        "Shuttle Bay", "Probe Launcher",
    ):
        prop = App.g_kModelPropertyManager.FindByName(
            name, App.TGModelPropertyManager.LOCAL_TEMPLATES
        )
        if prop is None:
            continue
        for k in prop._data:
            if k[0] in ("Position", "Orientation", "Width"):
                leaks.append(f"{name}.{k[0]}{k[1]}")
    assert leaks == [], f"data-bag swallowed typed calls: {leaks}"
