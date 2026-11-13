"""The opening: before first contact a wing's target picks read every enemy
within engage_gu, not only the ones inside its commander's leash.

Quick Battle places both rows mirrored around the player at "Standard"
range: 35 km = 200 GU = leash_gu. Each enemy commander then has exactly ONE
ship inside its leash (the one straight opposite it, the player when the
commander is slot 0), so "weakest in reach" was "that ship" and the wing's
target group held only it."""
import dataclasses

from engine.quickbattle import placement
from engine.quickbattle.scenario import DISTANCE_KM
from engine.units import GU_TO_KM
from engine.wings import dials, decisions, plans
from engine.wings.assess import ShipView

_COLS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def setup_function(_):
    dials.reset()
    decisions.reset_registry()


def V(name, pos, power, hull=1.0):
    return ShipView(name=name, pos=tuple(pos), hull=hull, shield=1.0,
                    power=power, faces=(1.0,) * 6)


def _mirrored(distance="standard"):
    """The player (strongest) with three escorts, and the enemy row the way
    spawn places it; the enemy commander is slot 0, straight opposite the
    player. The player is under disable_threat (1.5) x an enemy: a much
    stronger player is disable's case, not the geometry's."""
    d = DISTANCE_KM[distance] / GU_TO_KM
    esc = placement.escort_positions((0.0, 0.0, 0.0), _COLS, 3.0,
                                     [2.0, 2.0, 2.0])
    row = placement.group_positions((0.0, 0.0, 0.0), _COLS, "fore", d,
                                    [2.0] * 3)
    ours = ([V("player", (0.0, 0.0, 0.0), 1400.0)]
            + [V("esc%d" % i, p, 800.0 + 100.0 * i)
               for i, p in enumerate(esc)])
    theirs = [V("E%d" % i, p, 1000.0) for i, p in enumerate(row)]
    return ours, theirs


def _enemy_ctx(ours, theirs, **kw):
    kw.setdefault("opening", True)
    kw.setdefault("slot_eligible", len(theirs))
    return decisions.Context(members=theirs, anchor=theirs[0],
                             enemies=list(ours), armed_strength=3000.0, **kw)


def _opening_choice(ctx):
    """What the brain applies: the picked decision's choice, marked far
    while the wing is opening (brain.tick_wing)."""
    choice = decisions.pick(ctx).choose(ctx)
    if ctx.opening and not choice.far:
        choice = dataclasses.replace(choice, far=True)
    return choice


def test_mirrored_rows_open_on_the_weakest_not_the_ship_opposite():
    ours, theirs = _mirrored()
    ctx = _enemy_ctx(ours, theirs)
    choice = _opening_choice(ctx)
    assert choice.primary == "esc0"                 # the weakest of the four
    assert choice.secondaries == ("esc1", "esc2")
    group = plans.target_priorities(ctx.enemies, ctx.anchor, choice, {},
                                    None)
    # The pick and two secondaries to overflow to (§9); the player, inside
    # the leash, stays a candidate at the reach set's 0.0.
    assert group == {"esc0": 3.0, "esc1": 1.5, "esc2": 1.5, "player": 0.0}


def test_after_contact_the_leash_is_the_reach_again():
    """The pre-fix behaviour, kept once contacted: only the ship opposite
    is inside the leash, so it is the pick and the whole group."""
    ours, theirs = _mirrored()
    ctx = _enemy_ctx(ours, theirs, opening=False)
    choice = decisions.pick(ctx).choose(ctx)
    assert choice.primary == "player" and not choice.far
    assert plans.target_priorities(ctx.enemies, ctx.anchor, choice, {},
                                   None) == {"player": 3.0}


def test_close_range_spawn_is_still_an_opening():
    """'Close' is 20 km = ~114 GU: past contact_gu, so the opening holds."""
    ours, theirs = _mirrored("close")
    assert DISTANCE_KM["close"] / GU_TO_KM > dials.get("contact_gu")
    assert not plans.in_contact(theirs, ours)
    assert _opening_choice(_enemy_ctx(ours, theirs)).primary == "esc0"


def test_opening_never_reaches_past_engage_gu():
    ours, theirs = _mirrored("out_of_range")        # 150 km = ~857 GU
    ctx = _enemy_ctx(ours, theirs)
    assert decisions._in_reach(ctx) == []


def test_opening_skips_a_retiring_ship_like_the_weakest_pick():
    ours, theirs = _mirrored()
    ours[1] = ShipView(name="esc0", pos=ours[1].pos, hull=1.0, shield=1.0,
                       power=800.0, faces=(1.0,) * 6, retiring=True)
    assert _opening_choice(_enemy_ctx(ours, theirs)).primary == "esc1"


def test_disable_never_reads_the_opening_reach():
    """A much stronger enemy past the leash but inside engage_gu: the
    opening widens swarm picks only. Disable from there charged a ship the
    wing should lure to an ally (Phase D feint)."""
    ours, theirs = _mirrored()
    big = V("big", (0.0, -100.0, 0.0), 5000.0)       # 300 GU from E0
    ctx = _enemy_ctx([big] + ours[1:], theirs)
    assert big in decisions._in_reach(ctx)
    assert decisions._disable_target(ctx) is None
    assert decisions.pick(ctx).name != "disable"


def test_in_contact_reads_any_member_against_any_enemy():
    a = [V("a", (0.0, 0.0, 0.0), 1.0), V("b", (0.0, 150.0, 0.0), 1.0)]
    e = [V("x", (0.0, 240.0, 0.0), 1.0)]
    assert plans.in_contact(a, e)                     # b is 90 GU away
    assert not plans.in_contact(a[:1], e)
    dials._dials["contact_gu"] = 300.0
    assert plans.in_contact(a[:1], e)
    assert not plans.in_contact(a, [])
