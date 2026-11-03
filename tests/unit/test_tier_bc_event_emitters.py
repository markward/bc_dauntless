"""Engine emitters for the Tier B/C gaps in docs/reference/engine/event-emitter-gaps.md.

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

from tests.helpers.native_on import native_combat_on  # noqa: F401  (fixture)


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
#
# Since fire control native only (M4, R8) the edge is the native K1 tractor
# walk's (and TractorBeamSystem.StopFiring's own), and both events are
# effect-queue entries: delivered at the next flush -- a StartFiring
# session's end, the tick scope's exit, effect_queue.boundary() -- so these
# run with native combat on, on a real ship, target and projector.

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
    # One set (direct attribute: no ET_ENTERED_SET into `posted`): the interim
    # cross-set weapon guard (system-frames Plan 2 Ruling 5) puts a setless
    # target out of tractor range.
    ship._containing_set = target._containing_set = App.SetClass_Create()
    return ship, sys_, emitter, target


def _tick(ship, target, dt=1.0 / 60.0):
    """One host tick of the weapons: the charging step (K0) and the
    held-weapon pump (K1's tractor walk), in the tick's effect scope."""
    from engine import host_loop
    from engine.appc import effect_queue
    from engine.core import step_memo
    with effect_queue.scope():
        host_loop._advance_weapons([ship, target], dt)
        with step_memo.combat_step():
            host_loop._pump_held_weapons([ship, target], dt)


def _engage(sys_, target):
    from unittest.mock import patch
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target, None)


def test_engaging_posts_started_once_with_the_ship_as_destination(
        posted, native_combat_on):
    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    assert emitter.IsFiring() == 1, "precondition: the real beam must grip"

    started = _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)
    assert len(started) == 1
    assert started[0].GetDestination() is ship, (
        "PowerDisplay.HandleTractor casts GetDestination() to ShipClass")
    assert started[0].GetSource() is sys_


def test_holding_the_beam_does_not_repost_every_tick(posted,
                                                     native_combat_on):
    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    for _ in range(10):
        _tick(ship, target)
    assert emitter.IsFiring() == 1
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1, (
        "the beam is sustained every tick while held; the event is not")


def test_releasing_posts_stopped_once(posted, native_combat_on):
    from engine.appc import effect_queue

    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    posted.clear()
    sys_.StopFiring()
    # Queued (ruling R8): delivered at the next flush, not at the call.
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING) == []
    effect_queue.boundary()

    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1
    assert stopped[0].GetDestination() is ship
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []


def test_stopping_a_beam_that_never_gripped_posts_nothing(posted,
                                                          native_combat_on):
    """The HUD toggle can be released without the beam ever having gripped
    (out of range the whole time). No transition, no event."""
    from engine.appc import effect_queue
    from engine.appc.math import TGPoint3

    ship, sys_, emitter, target = _real_tractor_rig()
    target.SetWorldLocation(TGPoint3(0, 500, 0))    # out of tractor range
    _engage(sys_, target)
    assert sys_.IsEngaged() and emitter.IsFiring() == 0
    sys_.StopFiring()
    effect_queue.boundary()

    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING) == []


def test_losing_the_grip_mid_hold_posts_stopped_then_started_on_reacquire(
        posted, native_combat_on):
    """A tractor stays ENGAGED while the beam drops in and out (target out of
    range, emitter out of arc). Each crossing is a transition PowerDisplay
    must repaint for."""
    from engine.appc.math import TGPoint3

    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    posted.clear()

    target.SetWorldLocation(TGPoint3(0, 500, 0))    # drifts out of range
    _tick(ship, target)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)) == 1
    assert sys_.IsEngaged()

    target.SetWorldLocation(TGPoint3(0, 50, 0))     # back in range
    _tick(ship, target)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1


def test_power_loss_stop_is_synced_on_the_very_next_update(posted,
                                                           native_combat_on):
    """The parent's TurnOff() silences the beam in the charging step (K0's
    holding branch, TractorBeam.UpdateCharge's parent-power gate), behind
    the tractor walk's back: the walk's `not IsOn()` branch must still sync
    the transition, or `_was_firing` stays stuck True -- the HUD latches
    "on" and the STARTED event that follows re-power is swallowed.
    """
    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1
    posted.clear()

    sys_.TurnOff()   # e.g. the power slider dragged to 0 (engineering_power_panel.py:47)
    _tick(ship, target)
    assert emitter.IsFiring() == 0, "precondition: the power gate stopped it"
    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1, (
        "the beam stopped behind the walk's back; the not-self.IsOn() "
        "branch must still sync the transition")
    assert stopped[0].GetDestination() is ship

    # Confirms the cache didn't just happen to still read correctly: restore
    # power, and the STARTED event must be reachable again (a stuck
    # _was_firing=True would swallow it).
    posted.clear()
    sys_.TurnOn()
    _tick(ship, target)
    assert emitter.IsFiring() == 1, "precondition: beam re-acquires once powered"
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1


def test_swinging_out_of_arc_stops_and_syncs_even_though_still_engageable(
        posted, native_combat_on):
    """The walk's per-emitter arc re-check, the only emitter stop that is
    NOT driven by the range gate: a real TractorBeam has a real default
    Direction (0,1,0) and no authored arc bounds, so it falls back to BC's
    bare 90-degree dot-product cone -- swinging the target behind the ship
    swings it out of that cone while still in range.
    """
    from engine.appc.math import TGPoint3

    ship, sys_, emitter, target = _real_tractor_rig()
    _engage(sys_, target)
    assert emitter.IsFiring() == 1
    posted.clear()

    target.SetWorldLocation(TGPoint3(0, -50, 0))   # swung dead astern: still
                                                    # in range, but behind
                                                    # the 90-degree cone
    _tick(ship, target)

    assert emitter.IsFiring() == 0, (
        "precondition: the arc re-check, not the range gate, must be what "
        "stopped this emitter")
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
    """Mid-warp the player sits in BC's "warp" set -- with no contacts
    unless a mission parked ships there -- so perceived_by returns (); every
    contact left the list."""
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


def test_clearing_the_list_lets_the_next_push_re_announce(posted):
    """ClearTargetList destroys the rows; `_listed` must not outlive them.

    Its only SDK caller (Multiplayer/MissionShared.py:353) deletes the ships
    straight afterwards, so this is unreachable in single-player today. It is
    pinned because it is the one method that can desynchronise `_listed` from
    what the list actually shows: without the reset, a ship still present on
    the next push is silently NOT re-added even though its row was rebuilt.
    """
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    menu.ClearTargetList()
    posted.clear()

    menu.set_contacts([_contact(a)])

    added = _of_type(posted, App.ET_TARGET_LIST_OBJECT_ADDED)
    assert [e.GetDestination() for e in added] == [a]


def test_membership_is_recorded_before_handlers_run(posted, monkeypatch):
    """A handler runs INSIDE the post loop (AddEvent dispatches synchronously
    and destination dispatch is deliberately unguarded). By the time it does,
    `_listed` must already describe the new membership, or a re-entrant
    handler would diff against a stale set and double-post."""
    menu, (a, _b) = _menu_and_ships()
    seen = []

    def spy(evt):
        seen.append(frozenset(menu._listed))

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    menu.set_contacts([_contact(a)])

    assert seen == [frozenset({a})], (
        "_listed must be updated before the events are posted, not after")
