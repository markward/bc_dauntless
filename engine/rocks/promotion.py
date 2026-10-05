"""Rock promotion (docs/superpowers/specs/2026-10-05-rock-promotion-design.md §2-§3).

The nearest big near-band rocks around the player become real RockClass
objects -- the generator's exact rock -- so they can be targeted, scanned
and broken, and block torpedoes. Sim side (host_loop's rock_breakup scope),
never render side. Native draws nothing for a promoted or destroyed key
(rockfield_set_promoted). Session record: damaged keys come back damaged,
destroyed keys never regrow; reset() (mission swap) forgets both.
"""
from __future__ import annotations

import math

import engine.dev_mode as dev_mode

_promoted: dict = {}      # key -> RockClass
_damaged: dict = {}       # key -> hull fraction (0, 1)
_destroyed: set = set()   # keys whose promoted rock died
_last = None              # game time of the last acting tick
_view_set = None          # the SetClass the player was last promoted into


def field_name(key: int) -> str:
    return "Field Rock %04X" % (int(key) & 0xFFFF)


def promoted() -> dict:
    return dict(_promoted)


def _dial(name):
    from engine.rocks import far_dials
    return far_dials.get(name)


def _demote_cap() -> float:
    """Ruling R1: never hold a rock past the large billboard's fade-in, or
    the field would draw nothing there once it is handed back."""
    return min(_dial("promote_range_gu") * _dial("demote_range_mult"),
               _dial("near_large_billboard_gu") - _dial("near_fade_gu") - 1.0)


def _loc(obj) -> tuple:
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def _dist(rock, player) -> float:
    return math.dist(_loc(rock), _loc(player))


def _hull_fraction(rock) -> float:
    hull = rock.GetHull()
    if hull is None or hull.GetMaxCondition() <= 0.0:
        return 1.0
    return hull.GetCondition() / hull.GetMaxCondition()


def _muted(player, view_set, r) -> bool:
    """No NEW promotions (existing ones still demote by distance)."""
    if player is None or player.GetContainingSet() is not view_set:
        return True
    try:
        if not r.far_enabled():
            return True
    except Exception as e:
        dev_mode.log_swallowed("rock promotion far_enabled", e)
        return True
    from engine.rocks import minor_contact
    return bool(minor_contact._muted(player))


def _candidates(player, anchor, r) -> list:
    p = _loc(player)
    p_sys = tuple(a + b for a, b in zip(anchor, p))
    try:
        hits = r.rockfield_query_large(p_sys, _dial("promote_range_gu"),
                                       _dial("promote_min_radius_gu"))
    except Exception as e:
        dev_mode.log_swallowed("rock promotion rockfield_query_large", e)
        return []
    hits = [h for h in hits if h["key"] not in _destroyed]
    return hits[:int(_dial("promote_max"))]


def _reap() -> None:
    """Ruling R3: a dying or already-removed promoted rock belongs to the
    death path now; its key never regrows."""
    from engine.rocks import death
    for key, rock in list(_promoted.items()):
        if death.is_dying_rock(rock) or rock.GetContainingSet() is None:
            del _promoted[key]
            _destroyed.add(key)


def _held(rock, player) -> bool:
    return player is not None and player.GetTarget() is rock


def _demote(key) -> None:
    rock = _promoted.pop(key)
    fraction = _hull_fraction(rock)
    if fraction < 1.0:
        _damaged[key] = fraction
    pset = rock.GetContainingSet()
    if pset is not None:
        pset.RemoveObjectFromSet(rock.GetName())


def _demote_far(player, keep) -> None:
    cap = _demote_cap()
    for key, rock in list(_promoted.items()):
        if key in keep or _held(rock, player):
            continue
        if player is None or _dist(rock, player) > cap:
            _demote(key)


def _promote(view_set, anchor, key, hit, now) -> None:
    import App
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.rocks.rock import RockClass_Create
    name = field_name(key)
    if view_set.GetObject(name) is not None:
        dev_mode.log_swallowed("rock promotion name taken",
                               RuntimeError(name))
        return
    rock = RockClass_Create(hit["radius"], name=name, kind="major",
                            catalogue_index=hit["rock"], exact_radius=True,
                            seed=name)
    rock._field_key = key
    rock.SetTranslateXYZ(*(p - a for p, a in zip(hit["pos"], anchor)))
    spin = hit["rate"] * _dial("near_tumble_scale")
    axis = hit["axis"]
    rock.SetMatrixRotation(
        TGMatrix3().MakeRotation(hit["phase"] + spin * now, TGPoint3(*axis)))
    rock.SetAngularVelocity(TGPoint3(*(a * spin for a in axis)),
                            App.DIRECTION_WORLD_SPACE)
    rock.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    rock.SetTargetable(1)
    rock.SetScannable(1)
    rock.SetHailable(0)
    if key in _damaged:
        hull = rock.GetHull()
        hull.SetCondition(hull.GetMaxCondition() * _damaged.pop(key))
    try:
        view_set.AddObjectToSet(rock, name)
    finally:
        # A raising add (e.g. a set handler) may still have inserted the
        # rock: track it so it demotes and stays excluded -- never orphan it.
        if view_set.GetObject(name) is rock:
            _promoted[key] = rock


def _make_room(player, d_new) -> bool:
    """Full: drop the farthest untargeted promoted rock if it is farther
    than the candidate (`d_new` GU away). True when there is room."""
    if len(_promoted) < int(_dial("promote_max")):
        return True
    spare = [(_dist(rock, player), key) for key, rock in _promoted.items()
             if not _held(rock, player)]
    if not spare:
        return False
    d_far, key = max(spare)
    if d_far <= d_new:
        return False
    _demote(key)
    return True


def _push(r) -> None:
    try:
        r.rockfield_set_promoted(sorted(set(_promoted) | _destroyed))
    except Exception as e:
        dev_mode.log_swallowed("rock promotion rockfield_set_promoted", e)


def tick(player, view_set, now, r) -> None:
    """One promotion step, rate-limited to promote_hz (game time `now`).

    A view-set change or the start of a dash demote every promoted rock
    immediately -- both checks run ahead of the rate limit, so neither
    waits for the next due tick (spec §3, Review Focus 3)."""
    global _view_set
    try:
        if _view_set is not None and view_set is not _view_set:
            demote_all(r)
        _view_set = view_set
        from engine.rocks import minor_contact
        if _promoted and minor_contact._muted(player):
            demote_all(r)
            return
    except Exception as e:
        dev_mode.log_swallowed("rock promotion lifecycle", e)
    try:
        if not _due(now):
            return
    except Exception as e:
        dev_mode.log_swallowed("rock promotion rate limit", e)
        return
    try:
        _reap()
        hits = []
        anchor = (0.0, 0.0, 0.0)
        if not _muted(player, view_set, r):
            from engine.rocks import far_tier
            anchor = far_tier.frame_for(view_set)[1]
            hits = _candidates(player, anchor, r)
        _demote_far(player, {h["key"] for h in hits})
        p_sys = tuple(a + b for a, b in zip(anchor, _loc(player))) if hits else None
        for h in hits:
            if h["key"] in _promoted:
                continue
            if not _make_room(player, math.dist(p_sys, h["pos"])):
                break
            try:
                _promote(view_set, anchor, h["key"], h, now)
            except Exception as e:
                dev_mode.log_swallowed("rock promotion promote", e)
    except Exception as e:
        dev_mode.log_swallowed("rock promotion tick", e)
    finally:
        _push(r)                      # ruling R-A: every acting tick


def _due(now) -> bool:
    """Rate limit to promote_hz. Game time running backwards without a
    reset() (now < _last) acts and restarts the clock instead of stalling."""
    global _last
    if _last is not None and _last <= now < _last + 1.0 / _dial("promote_hz"):
        return False
    _last = now
    return True


def demote_all(r) -> None:
    """Every promoted rock back to scenery (hull fractions recorded)."""
    _reap()
    for key in list(_promoted):
        try:
            _demote(key)
        except Exception as e:
            _promoted.pop(key, None)
            dev_mode.log_swallowed("rock promotion demote", e)
    if r is not None:
        _push(r)


def reset(r=None) -> None:
    """demote_all, then forget the session record (mission swap)."""
    global _last, _view_set
    demote_all(None)
    _damaged.clear()
    _destroyed.clear()
    _last = None
    _view_set = None
    if r is not None:
        _push(r)
