"""_pump_contacts — the one wire from the player's containing set to the target
menu. Runs every frame: membership is DERIVED, so the push is the feature.

Behaviour of the helper itself is covered by
tests/integration/test_target_list_follows_player_system.py, whose `_pump`
helper calls this exact function. What lives here is the call-site guard —
without it, deleting the push from run() leaves the whole suite green while the
bug this task fixed (contacts bound to a departed system) silently returns.
"""
import inspect

import App
from engine import host_loop
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass
from engine.host_loop import _pump_contacts


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _ships(contacts):
    """_pump_contacts returns perception.Contact RECORDS now, not ships — the
    record is what the menu needs to derive both membership and row
    visibility. These tests are about WHICH contacts get pushed, so unwrap."""
    return tuple(c.ship for c in contacts)


def test_pump_contacts_pushes_the_players_set_into_the_menu():
    contact_index.reset()
    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    pSet = SetClass()
    player = _ship("player")
    pSet.AddObjectToSet(player, "player")
    galor = _ship("Galor")
    pSet.AddObjectToSet(galor, "Galor")

    assert _ships(_pump_contacts(menu, player)) == (galor,)
    assert menu.GetNumChildren() == 1


def test_pump_contacts_excludes_ships_in_other_sets():
    contact_index.reset()
    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    here, elsewhere = SetClass(), SetClass()
    player = _ship("player")
    here.AddObjectToSet(player, "player")
    elsewhere.AddObjectToSet(_ship("Galor"), "Galor")

    assert _ships(_pump_contacts(menu, player)) == ()
    assert menu.GetNumChildren() == 0


# ---------------------------------------------------------------------------
# Source-level guard on the host_loop.run() wiring.
#
# Same rationale as tests/host/test_letterbox_pump.py: run() is one monolithic
# while-loop built from real Appc/CEF/GL state and cannot be executed headless,
# so the call site is pinned by inspecting its source. Here the stakes are
# higher than usual — the per-frame push IS the fix. Deleting it from run()
# restores the original bug (the target list frozen on whichever set the
# player occupied at mission load) while every other test in the suite stays
# green, because they all exercise the helper directly.
#
# Be honest about the limit: a text match proves the wiring's SHAPE hasn't
# regressed, not its runtime behaviour (the two tests above cover that). It
# would also need updating alongside a deliberate rename of _menu/_player.
# ---------------------------------------------------------------------------


def test_run_calls_pump_contacts_every_frame():
    """Guards outright deletion of the push from run().

    The call site must read exactly `_pump_contacts(_menu, _player)`. If a
    future edit deletes it, inlines the contacts_for/set_contacts sequence
    again, or drops the affiliation recompute by open-coding only part of the
    helper, this string disappears from run()'s source and this fails.
    """
    src = inspect.getsource(host_loop.run)
    assert "_pump_contacts(_menu, _player)" in src, (
        "the per-frame contact push must read exactly "
        "'_pump_contacts(_menu, _player)' in run() -- without it the target "
        "list stops following the player's system and silently re-freezes on "
        "the set they occupied at mission load, with no other test failing")


def test_mission_swap_clears_the_contact_buckets():
    """contact_index.reset() must have a PRODUCTION call site.

    Buckets key on the SetClass object, so a stale bucket is not a correctness
    bug — a new mission builds new sets and gets fresh buckets. It is a leak:
    without this, every set and every ship from every mission played this
    session stays referenced for the process lifetime. reset_sdk_globals is
    the right home; it is where the retired target-menu unwire block lived.
    """
    from engine.host_loop import reset_sdk_globals
    contact_index.reset()
    pSet = SetClass()
    pSet.AddObjectToSet(_ship("Galor"), "Galor")
    assert contact_index.ships_in(pSet) != ()

    reset_sdk_globals()

    assert contact_index.ships_in(pSet) == ()
