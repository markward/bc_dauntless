"""_build_tractor_beam_render_data — descriptors for the beam renderer.

A firing tractor emitter yields the outer-shell + inner-core descriptor pair
(shared with phasers via _beam_descriptor_pair) with the emitter's own blue
colour / TractorBeam texture geometry read off the Galaxy-style hardpoint.  A
non-firing tractor — and a ship with no tractor system — yields nothing.
"""
from unittest.mock import patch

import App  # noqa: F401
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TractorBeam, TractorBeamSystem
from engine.appc.properties import TractorBeamProperty, WeaponSystemProperty
from engine.host_loop import _build_tractor_beam_render_data


def _make_emitter(name):
    emitter = TractorBeam(name)
    prop = TractorBeamProperty(name)
    prop.SetMaxCharge(5.0)
    prop.SetMinFiringCharge(3.0)
    # Blue tractor visuals straight off the galaxy.py hardpoint.
    prop.SetNumSides(12)
    prop.SetMainRadius(0.075)
    prop.SetTextureName("data/Textures/Tactical/TractorBeam.tga")
    prop.SetTextureSpeed(0.2)
    blue = App.TGColorA(); blue.SetRGBA(0.4, 0.4, 1.0, 1.0)
    prop.SetOuterShellColor(blue)
    prop.SetInnerCoreColor(blue)
    emitter.SetProperty(prop)
    emitter._max_charge = 5.0
    emitter._min_firing_charge = 3.0
    emitter._normal_discharge_rate = 1.0
    emitter._recharge_rate = 0.5
    emitter._charge_level = 5.0
    emitter._armed = True
    return emitter


def _ship_with_tractor():
    ship = ShipClass_Create("Source")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    parent = TractorBeamSystem("Tractors")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Tractors"))
    parent.SetSingleFire(1)
    parent._parent_ship = ship
    ship._tractor_beam_system = parent
    parent.AddChildSubsystem(_make_emitter("Aft Tractor"))
    return ship, parent


def _target():
    t = ShipClass_Create("Target")
    t.SetWorldLocation(TGPoint3(0, 50, 0))
    return t


def test_firing_tractor_yields_beam_pair():
    ship, parent = _ship_with_tractor()
    target = _target()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, None)
    out = _build_tractor_beam_render_data([ship, target])
    # Outer-shell + inner-core layers.
    assert len(out) == 2
    outer = out[0]
    # Blue tint from the hardpoint, and the tractor geometry came through.
    assert outer["color"][2] > outer["color"][0]   # blue dominates red
    assert outer["num_sides"] == 12
    # Beam runs from the emitter mount toward the target.
    assert outer["emitter"] is not None
    assert outer["target"] is not None
    # Funnel: the target end flares to >1× the body radius (the shader widens the
    # target-end taper instead of pinching it).
    assert outer["end_width_scale"] > 1.0


def test_non_firing_tractor_yields_nothing():
    ship, parent = _ship_with_tractor()
    out = _build_tractor_beam_render_data([ship])
    assert out == []


def test_ship_without_tractor_yields_nothing():
    plain = ShipClass_Create("Plain")
    plain.SetWorldLocation(TGPoint3(0, 0, 0))
    out = _build_tractor_beam_render_data([plain])
    assert out == []
