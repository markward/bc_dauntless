"""Engine emitters for the Tier B/C gaps in docs/engine/event-emitter-gaps.md.

Companion to test_tier_a_event_emitters.py. Tier A was "the post is the only
missing piece"; these needed a piece of state or an accessor built first, or
-- for ET_SET_TARGET -- needed the SDK read that says do not emit at all.

Events are captured by spying on App.g_kEventManager.AddEvent rather than by
registering SDK handlers: the contract is "the engine posts exactly this
event, exactly this often", and the negative cases (no post per tick while
held, no post on a no-op, no post at all for ET_SET_TARGET) are the whole
risk. AddEvent dispatches synchronously, so there is no drain step.
"""
import App
import pytest


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


# ── ET_SET_TARGET — deliberately NOT emitted ─────────────────────────────────
# Gap #2. Every SDK registration of ET_SET_TARGET (ScienceMenuHandlers.py:134,
# HelmMenuHandlers.py:281) is paired with an ET_TARGET_WAS_CHANGED
# registration on the same object to the same handler function. Nothing
# listens to ET_SET_TARGET alone; five sites listen to ET_TARGET_WAS_CHANGED
# alone. So emitting it would add no reachable behaviour and would run
# TargetChanged twice per change on the Science and Helm menus.

def test_set_target_posts_only_target_was_changed(posted):
    """If you are here because you added an ET_SET_TARGET emitter: read the
    comment above. The SDK says the two events funnel to one handler, so a
    second post is a double-dispatch, not new behaviour."""
    from engine.appc.ships import ShipClass

    ship, target = ShipClass(), ShipClass()
    target.SetName("Target")
    ship.SetTarget(target)

    assert len(_of_type(posted, App.ET_TARGET_WAS_CHANGED)) == 1
    assert _of_type(posted, App.ET_SET_TARGET) == []


def test_the_two_target_events_are_distinct_constants():
    """The assertion above is only meaningful while the constants differ; if
    they ever collapsed to the same int it would pass vacuously."""
    assert App.ET_SET_TARGET != App.ET_TARGET_WAS_CHANGED


# ── ET_CANT_FIRE ─────────────────────────────────────────────────────────────
# Gap #1. TacticalMenuHandlers.py:1990 and TacticalCharacterHandlers.py:198
# both read ONLY GetSource() and re-derive the reason from the system's own
# state; both compute pPhasers/pTractors and then use neither. So the emitter
# is torpedo-scoped and carries no reason payload.

def _torpedo_system(available=0, unlimited=False):
    """A TorpedoSystem whose current ammo type has `available` rounds.

    The brief's original version called ``LoadAmmoType(0, available)``
    before any slot existed and then poked ``_unlimited`` onto whatever
    ``GetCurrentAmmoType()`` returned. ``LoadAmmoType`` is a no-op against
    an absent slot (``GetAmmoType`` returns ``None`` -- see its docstring
    on ``TorpedoSystem``), so ``_ammo_by_slot`` stayed empty,
    ``GetCurrentAmmoType()`` returned ``None``, and the attribute-set
    raised ``AttributeError``. ``tests/unit/test_app_torpedo_economy.py``
    shows the real construction path: build a ``TorpedoAmmoType`` with the
    desired ``max_torpedoes`` (``None`` = unlimited, matching
    ``TorpedoAmmoType.__init__``) and ``AddAmmoType`` it -- the type
    spawns fully loaded, so ``available`` IS ``max_torpedoes`` here."""
    from engine.appc.weapon_subsystems import TorpedoAmmoType, TorpedoSystem

    sys_ = TorpedoSystem("Torpedo System")
    ammo = TorpedoAmmoType("Photon", max_torpedoes=None if unlimited else available)
    sys_.AddAmmoType(ammo)
    return sys_


def test_firing_with_no_ammo_posts_cant_fire(posted):
    sys_ = _torpedo_system(available=0)
    sys_.StartFiring(target=None)

    evts = _of_type(posted, App.ET_CANT_FIRE)
    assert len(evts) == 1
    assert evts[0].GetSource() is sys_, (
        "both handlers cast GetSource() to TorpedoSystem to decide the line")


def test_cant_fire_is_addressed_to_the_ship(posted):
    """The Destination is what makes this reach BC at all, and it is the one
    part of the contract the other tests cannot see.

    Both handlers are registered as INSTANCE handlers on the player ship
    (`pPlayer.AddPythonFuncHandlerForInstance(App.ET_CANT_FIRE, ...)`), and
    `events.AddEvent` only calls `dest.ProcessEvent(event)` when the event's
    destination IS that object. So a missing or wrong destination would keep
    every other test in this section green while the feature stayed as dead
    in-game as it was before the emitter existed.
    """
    from engine.appc.ships import ShipClass

    ship = ShipClass()
    ship.SetName("Player")
    sys_ = _torpedo_system(available=0)
    ship.SetTorpedoSystem(sys_)
    assert sys_.GetParentShip() is ship, (
        "precondition: SetTorpedoSystem must route through _attach_subsystem")

    sys_.StartFiring(target=None)

    evts = _of_type(posted, App.ET_CANT_FIRE)
    assert len(evts) == 1
    assert evts[0].GetDestination() is ship


def test_firing_with_ammo_does_not_post(posted):
    sys_ = _torpedo_system(available=4)
    sys_.StartFiring(target=None)

    assert _of_type(posted, App.ET_CANT_FIRE) == []


def test_unlimited_ammo_never_posts(posted):
    """An undeclared/unlimited ammo type never gates, so it can never be the
    'out of torpedoes' case the handlers speak to."""
    sys_ = _torpedo_system(available=0, unlimited=True)
    sys_.StartFiring(target=None)

    assert _of_type(posted, App.ET_CANT_FIRE) == []


def test_the_system_reports_its_own_ready_count():
    """Both handlers branch on pTorps.GetNumReady() where pTorps is the
    SYSTEM. GetNumReady was defined only on TorpedoTube, so on a system it
    resolved through TGObject.__getattr__ to a truthy _Stub and the handlers
    could not distinguish 'out of ammo' from 'not reloaded yet'."""
    from engine.appc.weapon_subsystems import TorpedoSystem

    sys_ = TorpedoSystem("Torpedo System")
    assert isinstance(sys_.GetNumReady(), int)
    assert sys_.GetNumReady() == 0, "no tubes -> nothing ready"


# ── ET_TRACTOR_BEAM_STARTED_FIRING / _STOPPED_FIRING ────────────────────────
# Gaps #8/#9. PowerDisplay.py:1010 casts GetDestination() to ShipClass and
# re-reads the system state; ConditionFiringTractorBeam.py:26-27 registers
# broadcast METHOD handlers filtered to the watched ship. Both need the SHIP
# as destination, and both need transitions, not per-tick pings.

class _FakeEmitter:
    """Minimal tractor projector: the system only asks IsFiring/CanFire/Fire.

    IsDisabled/IsDestroyed: once the fake is a real AddChildSubsystem() child
    (see _tractor_with), TractorBeamSystem.StartFiring's _is_offline() gate
    walks every child and calls both -- the brief's original docstring
    predates that walk being reachable (it required TurnOn() first, added
    below), and without these two the walk raises AttributeError instead of
    resolving through a stub.
    """

    def __init__(self):
        self._firing = False

    def IsFiring(self):
        return 1 if self._firing else 0

    def CanFire(self):
        return True

    def IsDisabled(self):
        return 0

    def IsDestroyed(self):
        return 0

    def Fire(self, target=None, offset=None):
        self._firing = True

    def StopFiring(self, *a):
        self._firing = False


def _tractor_with(emitter):
    """A TractorBeamSystem on a ship, holding one emitter, arc/range checks
    stubbed out so the test exercises the EDGE-DETECT, not the geometry.

    AddChildSubsystem / SetParentShip, NOT AddWeapon / _parent_ship=:
    GetWeapon(i) and GetNumWeapons() are thin aliases over the child-subsystem
    walk (weapon_subsystems.py:1065-1066), and there is no AddWeapon at all --
    calling one would resolve through TGObject.__getattr__ to a truthy _Stub,
    attach nothing, and leave every assertion below passing against an empty
    system.

    TurnOn(): PoweredSubsystem.__init__ defaults _is_on to False (weapons
    spawn cold, live-verified faithful -- see PhaserBank's
    `_init_energy_weapon_state`), and TractorBeamSystem.StartFiring's very
    first line is `if not self.IsOn() or target is None: return`. Without
    this the whole system is a no-op before the edge-detect is ever reached,
    which every positive assertion below would happily pass against.
    """
    from engine.appc.ships import ShipClass
    from engine.appc.weapon_subsystems import TractorBeamSystem

    ship = ShipClass()
    ship.SetName("Player")
    sys_ = TractorBeamSystem("Tractor Beam System")
    sys_.SetParentShip(ship)
    sys_.AddChildSubsystem(emitter)
    sys_.TurnOn()
    assert sys_.GetNumWeapons() == 1, "the emitter must really be attached"
    return ship, sys_


def test_engaging_posts_started_once_with_the_ship_as_destination(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)

    started = _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)
    assert len(started) == 1
    assert started[0].GetDestination() is ship, (
        "PowerDisplay.HandleTractor casts GetDestination() to ShipClass")


def test_holding_the_beam_does_not_repost_every_tick(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    for _ in range(10):
        sys_.update_weapons(1.0 / 60.0)

    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1, (
        "the beam is re-dispatched every tick while held; the event is not")


def test_releasing_posts_stopped_once(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    posted.clear()
    sys_.StopFiring()

    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1
    assert stopped[0].GetDestination() is ship
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []


def test_stopping_a_beam_that_never_gripped_posts_nothing(posted, monkeypatch):
    """The HUD toggle can be released without the beam ever having gripped
    (out of range the whole time). No transition, no event."""
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: False)

    sys_.StartFiring(target=ship)
    sys_.StopFiring()

    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING) == []


def test_losing_the_grip_mid_hold_posts_stopped_then_started_on_reacquire(
        posted, monkeypatch):
    """A tractor stays ENGAGED while the beam drops in and out (target out of
    range, shields up, emitter out of arc). Each crossing is a transition
    PowerDisplay must repaint for."""
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    engageable = {"v": True}
    monkeypatch.setattr(TractorBeamSystem, "_can_engage",
                        lambda *a: engageable["v"])
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    posted.clear()

    engageable["v"] = False               # drifts out of range
    sys_.update_weapons(1.0 / 60.0)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)) == 1

    engageable["v"] = True                # back in range
    sys_.update_weapons(1.0 / 60.0)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1
