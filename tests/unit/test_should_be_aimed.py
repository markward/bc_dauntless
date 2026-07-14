"""WeaponSystem.ShouldBeAimed — the authored "aimed weapon" property flag.

Evidence (decompiled stbc.exe, /STBC-Reverse-Engineering-1/reference/decompiled):

  0x00584050  WeaponSystem::GetProperty     -> *(this + 0x18)
  0x00584070  WeaponSystem::ShouldBeAimed   -> *(byte *)(property + 0x51)
  0x0063b6f0  swig_WeaponSystemProperty_IsAimedWeapon  reads  property + 0x51
  0x0063b770  swig_WeaponSystemProperty_SetAimedWeapon writes property + 0x51

So ShouldBeAimed() on the system IS the property's IsAimedWeapon flag —
there is no separate storage and no per-class constant.

The default comes from the WeaponSystemProperty constructor:

  0x0069afe0  WeaponSystemProperty::WeaponSystemProperty
                *(undefined1 *)(this + 0x14 /* int* => byte 0x50 */) = 1;  // SingleFire
                *(undefined1 *)((int)this  + 0x51)                   = 0;  // AimedWeapon

  => default ShouldBeAimed == 0 (free-fire) for every weapon-system type.

The only SWIG subclass of WeaponSystemProperty is TorpedoSystemProperty
(ctor 0x00693f60), which sets only the weapon-system-type field
(this[0x13] = 2) and does NOT touch 0x50/0x51 — so it inherits the same
default.  Phaser / pulse / tractor systems all use plain
WeaponSystemProperty, so they inherit it too.

In practice every stock hardpoint authors the flag explicitly with
WeaponSystemProperty.SetAimedWeapon (52 x 0, 18 x 1 across
sdk/.../ships/Hardpoints); the 1s are Torpedoes (16) and DisruptorCannons (2).

Consumer: AI/Preprocessors.py:642-647 FireScript.CheckGoodShot takes a
free-fire fast path (`return 1`) when ShouldBeAimed() is false.
"""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.properties import (
    WeaponSystemProperty, TorpedoSystemProperty, PhaserProperty,
)
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    PhaserSystem, TorpedoSystem, PulseWeaponSystem, TractorBeamSystem,
    TorpedoTube, PhaserBank,
)
from engine.appc.weapon_subsystems import TorpedoAmmoType


# ── Property-level default + round-trip ────────────────────────────────

def test_weapon_system_property_defaults_to_not_aimed():
    """ctor 0x0069afe0 writes 0 to property+0x51."""
    assert WeaponSystemProperty("Phasers").IsAimedWeapon() == 0


def test_torpedo_system_property_inherits_the_not_aimed_default():
    """ctor 0x00693f60 never touches +0x51, so it inherits 0."""
    assert TorpedoSystemProperty("Torpedoes").IsAimedWeapon() == 0


def test_set_aimed_weapon_round_trips_on_the_property():
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetAimedWeapon(1)
    assert prop.IsAimedWeapon() == 1
    prop.SetAimedWeapon(0)
    assert prop.IsAimedWeapon() == 0


# ── System-level: ShouldBeAimed reads the property ─────────────────────

_SYSTEM_TYPES = [PhaserSystem, TorpedoSystem, PulseWeaponSystem,
                 TractorBeamSystem]


@pytest.mark.parametrize("cls", _SYSTEM_TYPES)
def test_should_be_aimed_defaults_to_zero_for_every_system_type(cls):
    """0x00584070 reads property+0x51, whose ctor default is 0 — for
    phaser, torpedo, pulse and tractor systems alike."""
    sys_ = cls("W")
    sys_.SetProperty(WeaponSystemProperty("W"))
    assert sys_.ShouldBeAimed() == 0


@pytest.mark.parametrize("cls", _SYSTEM_TYPES)
def test_should_be_aimed_reflects_the_authored_property_flag(cls):
    sys_ = cls("W")
    prop = WeaponSystemProperty("W")
    prop.SetAimedWeapon(1)
    sys_.SetProperty(prop)
    assert sys_.ShouldBeAimed() == 1


def test_should_be_aimed_is_zero_without_a_property():
    """No property attached => the ctor default, not a truthy stub."""
    assert PhaserSystem("Phasers").ShouldBeAimed() == 0


def test_should_be_aimed_is_zero_on_a_leaf_emitter():
    """Our PhaserBank inherits WeaponSystem but carries a PhaserProperty,
    which has no AimedWeapon byte at all. ShouldBeAimed must fall back to
    the ctor default rather than blowing up — the SDK only ever asks the
    aggregator (Preprocessors.py:644), so 0 here is inert."""
    bank = PhaserBank("Dorsal 1")
    bank.SetProperty(PhaserProperty("Dorsal 1"))
    assert bank.ShouldBeAimed() == 0


# ── Payoff: FireScript.CheckGoodShot free-fire fast path ───────────────

def _fire_script(ours):
    from AI.Preprocessors import FireScript
    inst = FireScript("Target")
    inst.pCodeAI = PreprocessingAI_Create(ours, "FirePP")
    return inst


@pytest.fixture()
def _set():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _astern_torpedo_shot(aimed):
    """Forward-firing torpedo system, target dead astern — the only
    variable is the authored AimedWeapon flag.

    Geometry is identical in both arms, so the flag is the sole cause of
    any difference in CheckGoodShot's verdict.
    """
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    target.SetTranslateY(-500.0)  # dead astern (ship-forward is +Y)

    torps = TorpedoSystem("Torpedoes")
    prop = TorpedoSystemProperty("Torpedoes")
    prop.SetAimedWeapon(aimed)
    torps.SetProperty(prop)
    torps.AddAmmoType(TorpedoAmmoType("Photon", launch_speed=10.0))
    tube = TorpedoTube("Fore")
    tube.SetDirection(App.TGPoint3(0.0, 1.0, 0.0))  # forward-firing
    torps.AddChildSubsystem(tube)

    return torps, _fire_script(ours).CheckGoodShot(torps, target, None)


def test_check_good_shot_free_fires_an_unaimed_weapon_system(_set):
    """Preprocessors.py:644 — `if not pWeaponSystem.ShouldBeAimed(): return 1`.

    With the stub, ShouldBeAimed() was truthy and this fast path was dead;
    the AI ran the full aim check on every weapon.  SetAimedWeapon(0) (the
    ctor default, and what 52 of 70 stock hardpoint call sites author) must
    free-fire even with a forward-only launcher and the target dead astern.
    """
    torps, verdict = _astern_torpedo_shot(0)
    assert torps.ShouldBeAimed() == 0
    assert verdict == 1


def test_check_good_shot_still_aims_an_aimed_weapon_system(_set):
    """The flag must not be a blanket free-fire: an authored aimed system
    (Torpedoes.SetAimedWeapon(1) on 16 stock hardpoints) still runs the
    directional check (GetWeaponInfo -> tube directions) and rejects the
    same shot."""
    torps, verdict = _astern_torpedo_shot(1)
    assert torps.ShouldBeAimed() == 1
    assert verdict == 0
