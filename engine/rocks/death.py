"""Rock death (rock-class spec §2): replaces ship_death for rocks.

At 0 HP: death script, ET_OBJECT_EXPLODING at once, pieces out, no splash,
no fireball; ET_OBJECT_DESTROYED fires after kRockDeathLife (or the lifetime a
death script set -- E1M2 sets 0.5 s) and the rock then leaves its set.
Pieces that are majors are real RockClass objects added to the parent's set
here; chunks and the death VFX are queued for the host (render-side).

Removal reuses ship_death.retire, so the ordering is exactly the ship one:
SetDead + ET_OBJECT_DESTROYED while still in the set, then target locks
cleared, then set removal, then ET_DELETE_OBJECT_PUBLIC.
"""
from dataclasses import dataclass, replace

import engine.dev_mode as dev_mode
from engine.appc.math import TGPoint3
from engine.rocks import breakup, stats

kRockDeathLife = 0.5

_dying: list = []           # [{"rock", "time_left"}]
_ghosts: list = []          # [{"objs": [parent, piece...], "time_left"}]
_chunk_specs: list = []
_vfx_specs: list = []


@dataclass(frozen=True)
class ChunkSpec:
    family: str
    seed: str
    radius_gu: float
    mass: float
    loc: tuple
    vel: tuple
    angular: tuple
    pSet: object
    # ObjIDs of the breakup's parent and major pieces: the host ghosts the
    # chunk against these (and its sibling chunks) for kPieceGhostTime.
    ghost_ids: tuple = ()


@dataclass(frozen=True)
class DeathVfxSpec:
    loc: tuple
    radius_gu: float
    pSet: object


def is_dying_rock(rock) -> bool:
    return any(e["rock"] is rock for e in _dying)


def _life(rock) -> float:
    """kRockDeathLife unless a lifetime was set (below BC's 1e6 "unset"
    sentinel, the boundary death_cascade.roll_duration also uses)."""
    from engine.appc.death_cascade import LIFETIME_UNSET
    try:
        life = float(rock.GetLifeTime())
    except Exception:
        return kRockDeathLife
    return life if life < LIFETIME_UNSET else kRockDeathLife


def begin(rock, killer=None) -> None:
    if rock is None or is_dying_rock(rock) or rock.IsDead():
        return
    rock.SetDying(True)
    pSet = rock.GetContainingSet()
    name = rock.GetName()
    try:
        rock.RunDeathScript()
    except Exception as e:
        dev_mode.log_swallowed("rock death script", e)
    from engine.appc import ship_death
    ship_death._broadcast_exploding(rock, killer)
    # The parent stops colliding at once (E1M2's authored death script does
    # the same), so the grind path cannot damage the pieces born inside it.
    rock.SetCollisionsOn(0)
    # Read the lifetime AFTER the death script: that is where E1M2 sets it.
    _dying.append({"rock": rock, "time_left": _life(rock)})
    if pSet is not None:
        try:
            _break_up(rock, pSet, name)
        except Exception as e:
            dev_mode.log_swallowed("rock breakup", e)


def _break_up(rock, pSet, name) -> None:
    from engine.rocks.rock import RockClass_Create
    loc = rock.GetWorldLocation()
    R = rock.GetWorldRotation()
    v = rock.GetVelocityTG()
    radius = float(rock.GetRadius())
    hull = rock.GetHull()
    parent_max = float(hull.GetMaxCondition()) if hull is not None else stats.size_hull(radius)
    parent_mass = float(rock.GetMass())
    family = rock.__dict__.get("_rock_family", "silicate")
    gen = int(rock.__dict__.get("_rock_generation", 0)) + 1
    _vfx_specs.append(DeathVfxSpec((loc.x, loc.y, loc.z), radius, pSet))
    major_i = 0
    pieces = []
    chunk_specs = []
    for i, p in enumerate(breakup.plan(name, radius)):
        d = TGPoint3(*p.offset)
        d.MultMatrixLeft(R)                  # body -> world
        at = (loc.x + d.x * radius * 0.5, loc.y + d.y * radius * 0.5,
              loc.z + d.z * radius * 0.5)
        sp = breakup.kSeparationSpeedGU
        vel = (v.x + d.x * sp, v.y + d.y * sp, v.z + d.z * sp)
        tr = breakup.kTumbleRate
        ang = (d.y * tr, d.z * tr, d.x * tr)
        if p.tier == "major":
            major_i += 1
            piece_name = "%s-%d" % (name, major_i)
            piece = RockClass_Create(
                p.radius_gu, family=family, seed=piece_name, name=piece_name,
                kind="fragment",
                hull=stats.piece_hull(parent_max, p.v_ratio),
                mass=stats.piece_mass(parent_mass, p.v_ratio))
            piece._rock_generation = gen
            for getter, setter in (("IsTargetable", "SetTargetable"),
                                   ("IsScannable", "SetScannable"),
                                   ("IsHailable", "SetHailable")):
                g = getattr(rock, getter, None)
                s = getattr(piece, setter, None)
                if callable(g) and callable(s):
                    s(g())
            piece.SetTranslateXYZ(*at)
            piece.SetMatrixRotation(R)
            piece.SetVelocity(TGPoint3(*vel))
            piece.SetAngularVelocity(TGPoint3(*ang))
            pSet.AddObjectToSet(piece, piece_name)
            pieces.append(piece)
        elif p.tier == "chunk":
            chunk_specs.append(ChunkSpec(
                family, "%s#%d" % (name, i), p.radius_gu,
                stats.piece_mass(parent_mass, p.v_ratio), at, vel, ang, pSet))
    # Chunk specs wait for the majors: they carry every piece's ObjID.
    ghost_ids = tuple(o.GetObjID() for o in [rock] + pieces)
    _chunk_specs.extend(replace(s, ghost_ids=ghost_ids) for s in chunk_specs)
    if pieces:
        _ghost([rock] + pieces)


def _set_pairs(objs, on) -> None:
    """EnableCollisionsWith both ways for every pair in `objs`. Raise-safe per
    pair, so a piece that has since left the world cannot stop the rest."""
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            for x, y in ((a, b), (b, a)):
                try:
                    x.EnableCollisionsWith(y, 1 if on else 0)
                except Exception as e:
                    dev_mode.log_swallowed("rock piece collision mask", e)


def _ghost(objs) -> None:
    _set_pairs(objs, False)
    _ghosts.append({"objs": objs, "time_left": breakup.kPieceGhostTime})


def _advance_ghosts(dt: float) -> None:
    done = []
    for g in list(_ghosts):
        g["time_left"] -= dt
        if g["time_left"] <= 0.0:
            done.append(g)
            _set_pairs(g["objs"], True)
    _remove_entries(_ghosts, done)


def _remove_entries(registry: list, done: list) -> None:
    """Drop `done` from `registry` by identity. Anything appended while the
    caller was iterating (a handler that killed another rock) survives."""
    registry[:] = [e for e in registry if not any(e is d for d in done)]


def advance(dt: float) -> None:
    if _ghosts:
        _advance_ghosts(dt)
    if not _dying:
        return
    from engine.appc import ship_death
    # retire() dispatches ET_OBJECT_DESTROYED / EXITED_SET /
    # ET_DELETE_OBJECT_PUBLIC synchronously, and a handler may kill another
    # rock (begin() appends to _dying). Iterate a snapshot, drop only what
    # was processed.
    done = []
    for e in list(_dying):
        e["time_left"] -= dt
        if e["time_left"] > 0.0:
            continue
        done.append(e)
        rock = e["rock"]
        # A mission removed it first, or object_lifetime already retired it
        # (a death script's SetLifeTime also registers the rock there).
        if rock.GetContainingSet() is None or rock.IsDead():
            continue
        ship_death.retire(rock)
    _remove_entries(_dying, done)


def drain_chunk_specs() -> list:
    out = list(_chunk_specs)
    _chunk_specs.clear()
    return out


def drain_death_vfx() -> list:
    out = list(_vfx_specs)
    _vfx_specs.clear()
    return out


def reset() -> None:
    _dying.clear()
    _ghosts.clear()
    _chunk_specs.clear()
    _vfx_specs.clear()
