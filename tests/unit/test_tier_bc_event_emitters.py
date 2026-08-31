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


# ── Fix round 1, finding 1: power-loss stop bypasses update_weapons ─────────
# _FakeEmitter above can't reach this bug: it is not a TractorBeam, so
# TractorBeam.UpdateCharge's parent-power gate (weapon_subsystems.py
# :2278-2284, "power loss stops the beam") never runs against it. host_loop's
# per-frame emitter pump calls UpdateCharge on every REAL TractorBeam every
# tick regardless of the parent system's power state, so a real emitter can
# stop itself between one update_weapons() call and the next. This exercises
# that with the real TractorBeam + TractorBeamSystem pair (same construction
# shape as test_tractor_beam_render_data.py's _ship_with_tractor).

def _real_tractor_rig():
    """A ship with a real TractorBeamSystem holding one real, fully-charged
    TractorBeam emitter, plus an in-range, shield-free target — the geometry
    needed for StartFiring to actually engage (not stubbed out)."""
    from engine.appc.math import TGPoint3
    from engine.appc.ships import ShipClass_Create
    from engine.appc.weapon_subsystems import TractorBeam, TractorBeamSystem

    ship = ShipClass_Create("Source")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    emitter = TractorBeam("Aft Tractor")
    emitter._max_charge = 5.0
    emitter._min_firing_charge = 3.0
    emitter._normal_discharge_rate = 1.0
    emitter._recharge_rate = 0.5
    emitter._charge_level = 5.0

    sys_ = TractorBeamSystem("Tractors")
    sys_.AddChildSubsystem(emitter)
    ship.SetTractorBeamSystem(sys_)   # attaches + TurnOn()s (ships.py:981-988)

    target = ShipClass_Create("Target")
    target.SetWorldLocation(TGPoint3(0, 50, 0))   # dead ahead, in range, no shields
    return ship, sys_, emitter, target


def test_power_loss_stop_is_synced_on_the_very_next_update(posted):
    """Before the fix: update_weapons's `if not self.IsOn(): return False`
    bails without calling _sync_firing_event, so a beam the parent's own
    TurnOff() has already silenced (via TractorBeam.UpdateCharge's
    parent-power gate) leaves `_was_firing` stuck True forever -- the HUD
    latches "on" and the STARTED event that follows re-power is swallowed
    because the cache never saw the drop.
    """
    from unittest.mock import patch

    ship, sys_, emitter, target = _real_tractor_rig()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target, None)
    assert emitter.IsFiring() == 1, "precondition: the real beam must actually grip"
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1
    posted.clear()

    sys_.TurnOff()   # e.g. the power slider dragged to 0 (engineering_power_panel.py:47)
    emitter.UpdateCharge(1.0 / 60.0)   # host_loop's per-frame emitter pump
    assert emitter.IsFiring() == 0, "precondition: UpdateCharge's power gate stopped it"

    sys_.update_weapons(1.0 / 60.0)

    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1, (
        "the beam already stopped behind update_weapons's back; the "
        "not-self.IsOn() bail must still sync the transition")
    assert stopped[0].GetDestination() is ship

    # Confirms the cache didn't just happen to still read correctly: restore
    # power and re-engage, and the STARTED event must be reachable again
    # (a stuck _was_firing=True would swallow it).
    posted.clear()
    sys_.TurnOn()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.update_weapons(1.0 / 60.0)
    assert emitter.IsFiring() == 1, "precondition: beam re-acquires once powered"
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1


def test_swinging_out_of_arc_stops_and_syncs_even_though_still_engageable(posted):
    """update_weapons's per-emitter arc re-check (:1959-1961, the only emitter
    stop in this method that is NOT driven by the `engageable` range/shield
    flag) is otherwise untested by every _FakeEmitter-based case above: the
    fake has no GetDirection, so _emitter_in_arc short-circuits True for it
    unconditionally (finding 2b). A real TractorBeam has a real default
    Direction (0,1,0) and no authored arc bounds, so it falls back to BC's
    bare 90-degree dot-product cone -- swinging the target behind the ship
    swings it out of that cone while range and shields are untouched.
    """
    from unittest.mock import patch

    from engine.appc.math import TGPoint3

    ship, sys_, emitter, target = _real_tractor_rig()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target, None)
    assert emitter.IsFiring() == 1
    posted.clear()

    target.SetWorldLocation(TGPoint3(0, -50, 0))   # swung dead astern: still
                                                    # in range, still no shields,
                                                    # but behind the 90-degree cone

    sys_.update_weapons(1.0 / 60.0)

    assert emitter.IsFiring() == 0, (
        "precondition: the arc re-check, not the engageable gate, must be "
        "what stopped this emitter")
    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1
    assert stopped[0].GetDestination() is ship


# ── ET_TARGET_LIST_OBJECT_ADDED / _REMOVED ──────────────────────────────────
# Gaps #4/#5. ScienceMenuHandlers.ShipIdentified (:244) and ExitedSet (:205)
# both read pEvent.GetDestination(); E3M2.py:906 registers ADDED as an
# INSTANCE handler on the ship itself, so the ship must be the destination or
# that mission beat never fires. Membership is the targetable subset -- that
# is what _rows() lists.

def _contact(ship, targetable=True):
    from engine.appc.perception import Contact

    return Contact(ship=ship, surface_gu=1.0, perceivable=True,
                   targetable=targetable, subsystems_targetable=True)


def _menu_and_ships(n=2):
    from engine.appc.ships import ShipClass
    from engine.appc.target_menu import STTargetMenu

    menu = STTargetMenu("Targets")
    ships = []
    for i in range(n):
        s = ShipClass()
        s.SetName("Ship%d" % i)
        ships.append(s)
    return menu, ships


def test_a_new_contact_posts_added_with_the_ship_as_destination(posted):
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])

    added = _of_type(posted, App.ET_TARGET_LIST_OBJECT_ADDED)
    assert len(added) == 1
    assert added[0].GetDestination() is a, (
        "E3M2 registers ADDED as an instance handler ON the ship")


def test_a_contact_that_persists_does_not_repost(posted):
    """set_contacts runs every frame. Only crossings are events."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    posted.clear()

    for _ in range(5):
        menu.set_contacts([_contact(a)])

    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_ADDED) == []
    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED) == []


def test_a_contact_that_drops_posts_removed(posted):
    menu, (a, b) = _menu_and_ships()
    menu.set_contacts([_contact(a), _contact(b)])
    posted.clear()

    menu.set_contacts([_contact(a)])

    removed = _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)
    assert len(removed) == 1
    assert removed[0].GetDestination() is b


def test_losing_targetability_counts_as_removal(posted):
    """A contact that is still perceivable but no longer targetable is not on
    the list -- _rows() filters on targetable -- so it left it."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    posted.clear()

    menu.set_contacts([_contact(a, targetable=False)])

    removed = _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)
    assert len(removed) == 1
    assert removed[0].GetDestination() is a


def test_an_empty_push_removes_everything(posted):
    """Mid-warp the player sits alone in _WarpTransit and perceived_by returns
    (); every contact left the list."""
    menu, (a, b) = _menu_and_ships()
    menu.set_contacts([_contact(a), _contact(b)])
    posted.clear()

    menu.set_contacts([])

    assert len(_of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)) == 2


def test_the_row_cache_is_not_evicted_on_removal(posted):
    """Deliberate scope limit: this task posts events, it does not change row
    lifetime. Rows are reused for the life of the menu (see set_contacts'
    docstring on state normalisation); evicting them is a separate change."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    menu.set_contacts([])

    assert a in menu._row_cache


def test_a_swap_starts_from_empty_membership(posted):
    """No explicit reset exists because none is needed: host_loop.py:3586
    drops the singleton on swap and host_loop.py:6198 builds a fresh menu, so
    _listed starts empty by construction. If the menu ever becomes reused
    across swaps, this test goes red and _listed needs clearing wherever
    _row_cache is."""
    import App
    from engine.appc.ships import ShipClass

    old = ShipClass()
    old.SetName("OldSystemShip")
    menu = App.STTargetMenu_CreateW("Targets")
    menu.set_contacts([_contact(old)])
    posted.clear()

    App._reset_target_menu_singleton()
    fresh = App.STTargetMenu_CreateW("Targets")
    fresh.set_contacts([])

    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED) == [], (
        "the new system's first push must not report the old system's ships "
        "as having left")
