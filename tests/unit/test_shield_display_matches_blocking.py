"""The target-status shield bar must agree with whether shields actually block.

Reported live: "Disable NPC Shields" appeared to do nothing. It was working --
the diagnostic showed `blocks=False` on the NPC and the hull took full damage --
but the target status panel kept drawing a FULL shield bar, so the cheat was
indistinguishable on screen from being off. For a debugging tool that is nearly
as bad as broken: you cannot tell from the screen whether it is armed.

The panel was the only reader that ignored `combat.shields_block`. The beam
stop (host_loop.py:1551) and the shield bubble both already consult it -- live-
confirmed: with the cheat on, no bubble renders. And `_shields_tuple` already
implemented "not blocking => show down" for ONE reason, the cloak-transition
window, with a comment saying exactly that. This generalises that rule to every
reason rather than special-casing the cheat, so the bar can no longer
contradict the bubble drawn beside it.

PRODUCTION BEHAVIOUR CHANGES in two cases, and both are bugs in their own
right, found while measuring rather than assumed: a shield generator that is
DISABLED or DESTROYED still drew its stored charge as a full bar, while no
bubble rendered and nothing absorbed. Shoot out a ship's shield generator and
the target panel claimed it still had shields. A generator merely powered OFF
already read zero (GetSingleShieldPercentage short-circuits on it), so that
case was never broken -- measured, after an earlier guess said otherwise.

Stored charge is preserved and returns with the generator; this hides, it does
not drain.
"""
import pytest

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
from engine.ui.ship_display_panel import _shields_tuple


def _ship(name="NPC", face_max=1000.0):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(2000.0)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    ss.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    return ship


def test_a_healthy_shield_still_reads_full():
    """The common case must be untouched -- this fix must not blank every bar."""
    ship = _ship()

    assert _shields_tuple(ship) == (1.0,) * ShieldSubsystem.NUM_SHIELDS


def test_a_powered_down_generator_reads_zero():
    """Already true before this change -- GetSingleShieldPercentage
    short-circuits on the off state. Pinned so the rewrite below cannot
    regress it."""
    ship = _ship()
    ship.GetShieldSubsystem().TurnOff()

    assert _shields_tuple(ship) == (0.0,) * ShieldSubsystem.NUM_SHIELDS


def test_a_disabled_generator_reads_zero():
    """PRODUCTION CHANGE, and a bug on its own: a generator damaged below its
    disabled threshold stops blocking and renders no bubble, but the bar kept
    drawing its stored charge."""
    ship = _ship()
    ship.GetShieldSubsystem().SetCondition(0.0)

    assert _shields_tuple(ship) == (0.0,) * ShieldSubsystem.NUM_SHIELDS


def test_a_destroyed_generator_reads_zero():
    """PRODUCTION CHANGE. Shoot out a ship's shield generator and the target
    panel used to claim it still had full shields."""
    ship = _ship()
    ship.GetShieldSubsystem().SetDestroyed(1)

    assert _shields_tuple(ship) == (0.0,) * ShieldSubsystem.NUM_SHIELDS


def test_the_stored_charge_is_not_destroyed_only_hidden():
    """Hiding, not draining. The charge must come back with the generator --
    otherwise powering shields down would silently cost the player their
    shields, which is a gameplay change and not what this fixes."""
    ship = _ship()
    ss = ship.GetShieldSubsystem()
    ss.TurnOff()
    assert _shields_tuple(ship) == (0.0,) * ss.NUM_SHIELDS

    ss.TurnOn()

    assert _shields_tuple(ship) == (1.0,) * ss.NUM_SHIELDS


def test_the_disable_npc_shields_cheat_shows_the_bar_down(monkeypatch):
    """The reported bug. With the cheat on the NPC's bar must read zero, so the
    tool is visibly armed rather than silently working."""
    import App
    from engine import dev_mode, dev_combat_cheats as cheats

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    player, npc = _ship("Player"), _ship("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        cheats.set_disable_npc_shields(True)

        assert _shields_tuple(npc) == (0.0,) * ShieldSubsystem.NUM_SHIELDS
        assert _shields_tuple(player) == (1.0,) * ShieldSubsystem.NUM_SHIELDS, (
            "the cheat is NPC-only; the player's own bar must be untouched")
    finally:
        cheats.reset()
        App._set_current_game(None)


def test_the_panel_agrees_with_the_blocking_predicate():
    """The invariant, stated directly: the bar is non-zero iff shields block.
    Pins the two readers together so they cannot drift apart again."""
    from engine.appc.combat import shields_block

    healthy = _ship("Healthy")
    off = _ship("Off"); off.GetShieldSubsystem().TurnOff()
    disabled = _ship("Disabled"); disabled.GetShieldSubsystem().SetCondition(0.0)
    destroyed = _ship("Destroyed"); destroyed.GetShieldSubsystem().SetDestroyed(1)

    for ship in (healthy, off, disabled, destroyed):
        blocks = shields_block(ship)
        drawn = any(v > 0.0 for v in _shields_tuple(ship))
        assert blocks == drawn, (
            "%s: shields_block=%s but the panel draws %s"
            % (ship.GetName(), blocks, drawn))


# ── the third reader: the tractor beam's grip gate ──────────────────────────
# Reported live alongside the display bug: with "Disable NPC Shields" on,
# weapons went through but the tractor still refused to engage. _target_tractorable
# re-derived a SUBSET of shields_block (IsDisabled/IsOn only), so it missed the
# cheat, a destroyed generator, and the cloak window.

def test_the_tractor_can_grip_when_shields_do_not_block(monkeypatch):
    import App
    from engine import dev_mode, dev_combat_cheats as cheats
    from engine.appc.weapon_subsystems import _target_tractorable

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    player, npc = _ship("Player"), _ship("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        assert not _target_tractorable(npc), (
            "precondition: healthy shields deflect the beam")

        cheats.set_disable_npc_shields(True)

        assert _target_tractorable(npc), (
            "with NPC shields cheated off the beam must grip -- this is the "
            "half of the report that is functional, not cosmetic")
    finally:
        cheats.reset()
        App._set_current_game(None)


def test_the_tractor_can_grip_a_destroyed_generator():
    """Not a cheat case -- a real one. A shot-out shield generator stops
    blocking, so it cannot deflect a tractor beam either."""
    from engine.appc.weapon_subsystems import _target_tractorable

    ship = _ship("NPC")
    assert not _target_tractorable(ship)

    ship.GetShieldSubsystem().SetDestroyed(1)

    assert _target_tractorable(ship)


def test_healthy_shields_still_deflect_the_tractor():
    """The gate must not be blown open -- charged shields still refuse."""
    from engine.appc.weapon_subsystems import _target_tractorable

    assert not _target_tractorable(_ship("NPC"))


# ── the second HUD readout ──────────────────────────────────────────────────
# The TARGETS list draws its own shield number from GetShieldPercentage. It had
# the identical cloak-only special case, so it showed a full percentage for a
# disabled/destroyed generator and under the cheat. Fixed in the same commit
# because the two readouts sit on screen together -- but it went in without a
# test at first, which is the exact untested-edit pattern this file exists to
# prevent.

def _tl_pct(ship):
    from engine.ui.target_list_view import _query_shield_percentage
    return _query_shield_percentage(ship)


def test_the_targets_list_reads_full_for_healthy_shields():
    assert _tl_pct(_ship("NPC")) == 100


def test_the_targets_list_reads_zero_for_a_destroyed_generator():
    ship = _ship("NPC")
    ship.GetShieldSubsystem().SetDestroyed(1)

    assert _tl_pct(ship) == 0


def test_the_targets_list_reads_zero_for_a_disabled_generator():
    ship = _ship("NPC")
    ship.GetShieldSubsystem().SetCondition(0.0)

    assert _tl_pct(ship) == 0


def test_both_hud_readouts_agree(monkeypatch):
    """The reason both were fixed in one change: they are drawn together, so a
    disagreement between them is worse than both being wrong."""
    import App
    from engine import dev_mode, dev_combat_cheats as cheats

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    player, npc = _ship("Player"), _ship("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        cheats.set_disable_npc_shields(True)

        panel_shows = any(v > 0.0 for v in _shields_tuple(npc))
        list_shows = _tl_pct(npc) > 0

        assert panel_shows == list_shows == False
    finally:
        cheats.reset()
        App._set_current_game(None)
