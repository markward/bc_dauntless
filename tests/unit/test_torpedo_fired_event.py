"""ET_TORPEDO_FIRED, and the real BC event IDs — all measured, not inferred.

Ground truth is probe q12, run against the ORIGINAL GAME:
tools/probes/results/q12_torpedo_events.txt (96 captured events).

    ET_TORPEDO_FIRED  = 8388710 (0x00800066)
    ET_TORPEDO_RELOAD = 8388709 (0x00800065)

    e001 = ET_TORPEDO_FIRED  | SRC Torpedo(parent=13323 target=15013)
                             | DST TorpedoTube(name='Forward Torpedo 1')
    e035 = ET_TORPEDO_RELOAD | SRC None
                             | DST TorpedoTube(name='Forward Torpedo 1' ready=1)

Three things that were GUESSES before the probe and are now FACTS:
  * Source of ET_TORPEDO_FIRED is the TORPEDO PROJECTILE (not the tube, not the ship).
  * Destination is the TUBE. This is load-bearing and dangerous: Episode7.py:88-115
    destroys pEvent.GetDestination() on a 10% roll (the E7M1 phased-plasma beat).
    A wrong destination destroys the WRONG subsystem.
  * ET_TORPEDO_RELOAD has NO SOURCE. We had chosen the parent TorpedoSystem and
    labelled it "a CHOICE, not a finding" — the probe says BC posts SRC None.

And it fires for ORDINARY PHOTONS (`ammo=Photon` on every captured event), so the
Phased-Plasma filter lives in Episode7's HANDLER, not in the engine. The engine
must post it for every torpedo, unconditionally.
"""
import pytest

import App  # noqa: F401  (SDK shim import order)
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import PulseWeapon, TorpedoSystem, TorpedoTube


@pytest.fixture(autouse=True)
def clear_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0
    yield lambda t: setattr(App.g_kTimerManager, "_time", float(t))
    App.g_kTimerManager._time = 0.0


@pytest.fixture
def captured():
    """Collect every torpedo event the engine posts, in arrival order."""
    seen = []
    globals()["_collect"] = lambda _obj, evt: seen.append(evt)
    for name in ("ET_TORPEDO_FIRED", "ET_TORPEDO_RELOAD"):
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            getattr(App, name), object(), __name__ + "._collect")
    yield seen
    for name in ("ET_TORPEDO_FIRED", "ET_TORPEDO_RELOAD"):
        App.g_kEventManager._broadcast_handlers.pop(getattr(App, name), None)


def _armed_tube() -> TorpedoTube:
    """A ready tube on a real ship, with the PhotonTorpedo script bound so
    Fire() actually spawns a projectile (same shape as test_torpedo_spread_volley)."""
    from engine.appc.ships import ShipClass_Create

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship._target = None
    ship._target_subsystem = None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    system.SetProperty(prop)
    system._parent_ship = ship
    ship._torpedo_system = system

    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


# ── The real BC event IDs (q12) ────────────────────────────────────────────
# We had invented 0x1322 for the reload event because we could not measure the
# real one. Now we can, so use BC's own numbering.

def test_event_ids_match_the_real_game():
    assert App.ET_TORPEDO_RELOAD == 0x00800065
    assert App.ET_TORPEDO_FIRED == 0x00800066


def test_event_ids_are_real_ints_not_stubs():
    """An undefined App.ET_* silently becomes a _NamedStub whose hash is fresh on
    every access, so a handler registered under it can never fire."""
    assert isinstance(App.ET_TORPEDO_FIRED, int)
    assert isinstance(App.ET_TORPEDO_RELOAD, int)


# ── ET_TORPEDO_FIRED ───────────────────────────────────────────────────────

def test_firing_posts_torpedo_fired_with_projectile_source_and_tube_destination(
        clock, captured):
    tube = _armed_tube()
    clock(100.0)
    tube.Fire()

    fired = [e for e in captured if e.GetEventType() == App.ET_TORPEDO_FIRED]
    assert len(fired) == 1, "exactly one ET_TORPEDO_FIRED per torpedo"

    # SRC is the PROJECTILE (q12 e001), not the tube and not the ship.
    assert isinstance(fired[0].GetSource(), Torpedo)
    # DST is the TUBE. Episode7 DESTROYS this object on a 10% roll — if this
    # assertion ever changes, E7M1 starts destroying the wrong subsystem.
    assert fired[0].GetDestination() is tube


def test_torpedo_fired_is_ammo_agnostic(clock, captured):
    """q12 captured ammo=Photon on every ET_TORPEDO_FIRED, so the engine posts it
    for ORDINARY torpedoes. Episode7's Phased-Plasma check is in the HANDLER."""
    tube = _armed_tube()
    clock(100.0)
    tube.Fire()
    assert any(e.GetEventType() == App.ET_TORPEDO_FIRED for e in captured)


def test_a_tube_that_cannot_fire_posts_nothing(clock, captured):
    tube = _armed_tube()
    tube.SetNumReady(0)
    captured.clear()
    clock(100.0)
    tube.Fire()
    assert [e for e in captured if e.GetEventType() == App.ET_TORPEDO_FIRED] == []


def test_pulse_weapons_do_not_post_torpedo_fired(clock, captured):
    """_spawn_projectile is SHARED by torpedo tubes and pulse cannons. q12 shows
    ET_TORPEDO_FIRED's destination is ALWAYS a TorpedoTube, so a pulse cannon
    firing must not post it — otherwise Episode7 would try to destroy a pulse
    cannon as if it were a torpedo tube."""
    from engine.appc.subsystems import PulseWeaponSystem
    from engine.appc.ships import ShipClass_Create

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship._target = None
    ship._target_subsystem = None

    system = PulseWeaponSystem("Pulse")
    system.TurnOn()
    prop = WeaponSystemProperty("Pulse")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    system.SetProperty(prop)
    system._parent_ship = ship

    cannon = PulseWeapon("Pulse Cannon 1")
    cannon._max_charge = 100.0
    cannon._charge_level = 100.0
    cannon._min_firing_charge = 0.0
    system.AddChildSubsystem(cannon)

    captured.clear()
    clock(100.0)
    cannon.Fire()

    assert [e for e in captured if e.GetEventType() == App.ET_TORPEDO_FIRED] == [], \
        "a pulse cannon must not post a TORPEDO event"


# ── ET_TORPEDO_RELOAD source correction ────────────────────────────────────

def test_reload_event_has_no_source(clock, captured):
    """q12 e035: `SRC None`. We had set it to the parent TorpedoSystem — that was
    a documented GUESS, and it was wrong."""
    tube = _armed_tube()
    clock(100.0)
    tube.Fire()
    captured.clear()

    clock(140.0)
    tube.UpdateReload(0.0)

    reloads = [e for e in captured if e.GetEventType() == App.ET_TORPEDO_RELOAD]
    assert len(reloads) == 1
    assert reloads[0].GetSource() is None
    assert reloads[0].GetDestination() is tube
