"""Persistent target restore — emitter gap #10, the last of the twelve.

BC remembers the player's target (and its targeted SUBSYSTEM), and re-selects
both when the object becomes available again, announcing it with
ET_RESTORE_PERSISTENT_TARGET so the re-selection does not count as the player
manually retargeting — `Bridge/TacticalMenuHandlers.py:958`
`PersistentTargetRestored` increments a counter so `TargetChanged` does not
clear Felix's "Target At Will".

The mechanism is RECOVERED, not inferred. The clean-room RE project
reconstructed the restore routine after the reference server could not reach
it (no object model for STTargetMenu, no body for ClearPersistentTarget). What
they established, and what each of these tests pins:

  * The restore is driven from the target menu's PERIODIC REFRESH, not from an
    object-entered-set event. Our earlier SDK-derived guess was an event hook,
    which would have restored and cleared at the wrong moments.
  * The engine clears the memory in exactly ONE circumstance: the remembered
    object no longer resolves, or resolves to something dead. A merely
    not-currently-targetable object does NOT clear it -- it skips the tick.
  * Nothing clears the memory after a SUCCESSFUL restore; it persists.
  * ET_RESTORE_PERSISTENT_TARGET is posted BEFORE the target changes, so the
    SDK counter is incremented before the target-changed handler consumes it.
  * The restore re-targets the object AND its subsystem. In the original this
    is the second argument to SetTargetHandle -- documented in the reference
    corpus as an int flag, which the RE project corrected: it is a
    ShipSubsystem*, and the restore path is the ONLY one of eight call sites
    that passes it non-null.

Deliberately NOT carrying an integer parameter on either event. Of the six
engine subscribers to the target-changed event, five read only the ship and
none reads the second field; the multiplayer serializer reads it behind a null
guard. Omitting it is safe; an integer there is the one unsafe choice.

Two behaviours are OUR defaults, not recovered -- flagged here and in the
register: restoring only when the player has no current target, and resolving
only within the player's current set.
"""
import App
import pytest

from engine.appc import target_menu
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ShipSubsystem


@pytest.fixture
def scene():
    """Player and a target ship in one set, with the menu wired as the SDK
    reaches it (STTargetMenu_GetTargetMenu is a module singleton)."""
    kset = SetClass()
    kset.SetName("TestSystem")
    App.g_kSetManager._sets["TestSystem"] = kset

    player = ShipClass()
    kset.AddObjectToSet(player, "Player")
    quarry = ShipClass()
    kset.AddObjectToSet(quarry, "Quarry")

    menu = App.STTargetMenu_CreateW("Targets")
    yield menu, player, quarry
    App.g_kSetManager._sets.pop("TestSystem", None)
    App._reset_target_menu_singleton()


@pytest.fixture
def posted(monkeypatch):
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


def _see(menu, *ships, targetable=True):
    """Push a target-list refresh containing `ships`."""
    from engine.appc.perception import Contact
    menu.set_contacts([Contact(ship=s, surface_gu=1.0, perceivable=True,
                               targetable=targetable,
                               subsystems_targetable=True) for s in ships])


def _remember(menu, player, quarry, subsystem=None):
    """Put the player on `quarry` and let the recorder capture it."""
    player.SetTarget(quarry)
    if subsystem is not None:
        player.SetTargetSubsystem(subsystem)
    target_menu.remember_player_target(player)


# ── remembering ─────────────────────────────────────────────────────────────

def test_the_players_target_and_subsystem_are_remembered(scene):
    menu, player, quarry = scene
    sub = ShipSubsystem("Warp Engines")
    _remember(menu, player, quarry, sub)

    assert menu._persistent_target_name == quarry.GetName()
    assert menu._persistent_target_subsystem is sub


def test_nothing_is_remembered_when_the_player_has_no_target(scene):
    menu, player, _quarry = scene
    player.SetTarget(None)
    target_menu.remember_player_target(player)

    assert menu._persistent_target_name is None


def test_losing_the_target_does_not_erase_the_memory(scene):
    """The memory has to outlive the target being dropped -- that IS the
    feature. Engine-side clears (a target leaving sensor range) must not take
    the memory with them."""
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    target_menu.remember_player_target(player)

    assert menu._persistent_target_name == quarry.GetName()


# ── the restore ─────────────────────────────────────────────────────────────

def test_restoring_re_selects_the_object_and_its_subsystem(scene, posted):
    menu, player, quarry = scene
    sub = ShipSubsystem("Warp Engines")
    _remember(menu, player, quarry, sub)
    player.SetTarget(None)
    player.SetTargetSubsystem(None)
    _see(menu, quarry)
    posted.clear()

    target_menu.attempt_persistent_restore(player)

    assert player.GetTarget() is quarry
    assert player.GetTargetSubsystem() is sub, (
        "the restore carries the SUBSYSTEM too -- that is what the original's "
        "second SetTargetHandle argument is")


def test_the_restore_event_precedes_the_target_change(scene, posted):
    """Load-bearing ordering. PersistentTargetRestored increments a counter
    that TargetChanged then consumes; posted the other way round, the counter
    arrives too late and Felix's Target At Will is cleared by a re-selection
    the player never made."""
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    _see(menu, quarry)
    posted.clear()

    target_menu.attempt_persistent_restore(player)

    kinds = [e.GetEventType() for e in posted]
    assert App.ET_RESTORE_PERSISTENT_TARGET in kinds
    assert App.ET_TARGET_WAS_CHANGED in kinds
    assert kinds.index(App.ET_RESTORE_PERSISTENT_TARGET) < \
        kinds.index(App.ET_TARGET_WAS_CHANGED)


def test_the_memory_survives_a_successful_restore(scene, posted):
    """"Nothing clears it after a successful restore; the memory persists."
    So a target that leaves and returns twice restores twice."""
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    _see(menu, quarry)
    target_menu.attempt_persistent_restore(player)

    assert menu._persistent_target_name == quarry.GetName()


def test_no_restore_when_the_player_already_has_a_target(scene, posted):
    """OUR DEFAULT, not recovered behaviour: overriding a live selection would
    be the more surprising reading. Flagged in the register."""
    menu, player, quarry = scene
    other = ShipClass()
    App.g_kSetManager.GetSet("TestSystem").AddObjectToSet(other, "Other")
    _remember(menu, player, quarry)
    player.SetTarget(other)
    _see(menu, quarry, other)
    posted.clear()

    target_menu.attempt_persistent_restore(player)

    assert player.GetTarget() is other
    assert _of_type(posted, App.ET_RESTORE_PERSISTENT_TARGET) == []


# ── the guard order: skip vs clear ──────────────────────────────────────────

def test_a_not_currently_targetable_object_skips_the_tick(scene, posted):
    """The asymmetry that matters. Not targetable (cloaked, out of sensor
    range) must NOT clear the memory -- otherwise a ship that cloaks once is
    forgotten forever, and the feature silently stops working."""
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    _see(menu, quarry, targetable=False)
    posted.clear()

    target_menu.attempt_persistent_restore(player)

    assert player.GetTarget() is None, "not targetable -> no restore this tick"
    assert menu._persistent_target_name == quarry.GetName(), "...but remembered"
    assert _of_type(posted, App.ET_RESTORE_PERSISTENT_TARGET) == []


def test_a_dead_object_clears_the_memory(scene, posted):
    """Only gone-or-dead clears. Uses the same liveness predicate our target
    LIST membership uses (perception: alive_or_wreck), mirroring the original,
    where the clear is gated on the same pair the menu-membership scan uses.

    `SetDead()` is the real flag `_out_of_action` reads via `IsDead()` — an
    earlier version of this test set `SetDeleteMe(1)` and a private
    `_destroyed`, neither of which any predicate consults, so the ship read as
    perfectly alive and the test failed against correct code.
    """
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    quarry.SetDead()
    _see(menu)

    assert not target_menu._persistent_target_alive(quarry), (
        "precondition: the ship must actually read as dead")

    target_menu.attempt_persistent_restore(player)

    assert menu._persistent_target_name is None
    assert player.GetTarget() is None


def test_a_targetable_wreck_is_still_worth_remembering(scene, posted):
    """`alive_or_wreck`, not `alive`. A ship in its death throes stays
    selectable in the target list for the linger window, so it is a
    legitimate thing to have remembered — clearing on the first sign of death
    would drop the memory while the wreck is still a valid target."""
    from engine.appc import ship_death

    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    ship_death.begin(quarry)

    assert target_menu._persistent_target_alive(quarry), (
        "a wreck still in the death registry counts as alive_or_wreck")

    _see(menu, quarry)
    target_menu.attempt_persistent_restore(player)

    assert menu._persistent_target_name == quarry.GetName()


def test_an_object_that_no_longer_resolves_clears_the_memory(scene, posted):
    menu, player, quarry = scene
    _remember(menu, player, quarry)
    player.SetTarget(None)
    App.g_kSetManager.GetSet("TestSystem").RemoveObjectFromSet("Quarry")
    _see(menu)

    target_menu.attempt_persistent_restore(player)

    assert menu._persistent_target_name is None


def test_nothing_remembered_is_a_no_op(scene, posted):
    menu, player, _quarry = scene
    player.SetTarget(None)

    target_menu.attempt_persistent_restore(player)

    assert posted == []


# ── integration with the existing clear sites ───────────────────────────────

def test_warp_clears_the_memory(scene):
    """warp._clear_all_targets already calls ClearPersistentTarget, mirroring
    HelmMenuHandlers.PostWarpEnableMenu -- whose comment ("so that we don't
    retarget the same thing when we return to the old set") is the behaviour
    BC's own authors removed. That call was inert until this branch gave the
    field a writer; pin it now that it does something."""
    from engine.appc.warp import _clear_all_targets

    menu, player, quarry = scene
    _remember(menu, player, quarry)

    _clear_all_targets(player)

    assert menu._persistent_target_name is None
    assert menu._persistent_target_subsystem is None


def test_clear_persistent_target_clears_the_subsystem_too(scene):
    """ClearPersistentTarget is real published API (nine-entry surface). It
    must clear BOTH halves of the pair, or a stale subsystem outlives the
    object it belonged to."""
    menu, player, quarry = scene
    _remember(menu, player, quarry, ShipSubsystem("Warp Engines"))

    menu.ClearPersistentTarget()

    assert menu._persistent_target_name is None
    assert menu._persistent_target_subsystem is None


def test_the_host_loop_actually_drives_both_halves():
    """Guard against dead code -- a correct mechanism nothing runs. Both calls
    must sit inside the contact-pump block, AFTER _pump_contacts: the restore
    reads this frame's `targetable` verdict to choose skip-vs-restore, so
    running it before the push would decide on last frame's answer."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine/host_loop.py").read_text()

    assert "remember_player_target(_player)" in src
    assert "attempt_persistent_restore(_player)" in src
    assert src.index("_pump_contacts(_menu, _player)") < \
        src.index("remember_player_target(_player)") < \
        src.index("attempt_persistent_restore(_player)")
