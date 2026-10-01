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
# Cap on each render-side queue. The host drains them every frame; headless
# nothing does, so a long run of rock deaths would grow them for ever. Past
# the cap the OLDEST entries go (a stale chunk matters least).
kMaxQueuedSpecs = 256

_dying: list = []           # [{"rock", "time_left"}]
_ghosts: list = []          # [{"a", "b", "time_left"}], one per masked pair
_chunk_specs: list = []
_vfx_specs: list = []
_warned_setless = False


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
    # The breakup's parent, major pieces and killer: the host ghosts the
    # chunk against these (and its sibling chunks) until each pair separates.
    ghost_peers: tuple = ()


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
            _break_up(rock, pSet, name, killer)
        except Exception as e:
            dev_mode.log_swallowed("rock breakup", e)
    else:
        # Pieces need a set to join, so a set-less rock cannot break up, and
        # advance() drops it without a retire. Say so once, not silently.
        global _warned_setless
        if not _warned_setless:
            _warned_setless = True
            dev_mode.log_swallowed("set-less dying rock: no breakup",
                                   RuntimeError(str(name)))


def _is_immovable(obj) -> bool:
    """A Planet (moons and suns included), or anything whose class says it is
    immobile (SetStatic / SetStationary ships). Class-level lookup, not
    getattr on the instance: TGObject.__getattr__ vends a truthy _Stub."""
    from engine.appc.planet import Planet
    if isinstance(obj, Planet):
        return True
    fn = getattr(type(obj), "IsImmobile", None)
    if fn is None:
        return False
    try:
        return bool(fn(obj))
    except Exception as e:
        dev_mode.log_swallowed("rock killer IsImmobile", e)
        return False


def _killer_centre(killer, pSet):
    """The killer's centre in `pSet`'s coordinates, or None when its frame is
    not comparable (it has left, or sits in an unrelated set)."""
    from engine.systems import frames
    try:
        k_set = frames.containing_set(killer)
        off = frames.offset_between(pSet, k_set)
        if off is None:
            return None
        c = killer.GetWorldLocation()
        return (c.x + off[0], c.y + off[1], c.z + off[2])
    except Exception as e:
        dev_mode.log_swallowed("rock killer centre", e)
        return None


def _strip_inward(vel, at, centre) -> tuple:
    """`vel` with its component toward `centre` (seen from `at`) removed. A
    piece born against an immovable killer must not keep flying into it: its
    next contact would be lethal too, and the breakup would cascade."""
    dx, dy, dz = centre[0] - at[0], centre[1] - at[1], centre[2] - at[2]
    n = (dx * dx + dy * dy + dz * dz) ** 0.5
    if n < 1e-9:
        return vel
    dx, dy, dz = dx / n, dy / n, dz / n
    vn = vel[0] * dx + vel[1] * dy + vel[2] * dz
    if vn <= 0.0:
        return vel
    return (vel[0] - vn * dx, vel[1] - vn * dy, vel[2] - vn * dz)


def _break_up(rock, pSet, name, killer=None) -> None:
    """Spawn the breakup. `killer` is the body whose hit caused the death (a
    collision's other body, planets included -- collisions passes it to
    apply_hit as `source`, which DamageSystem hands to begin()). It joins
    the ghost set (masked until separated), and when it is immovable every
    piece's velocity toward its centre is removed."""
    from engine.rocks.rock import RockClass_Create, effective_radius
    if killer is rock:
        killer = None
    centre = (_killer_centre(killer, pSet)
              if killer is not None and _is_immovable(killer) else None)
    loc = rock.GetWorldLocation()
    R = rock.GetWorldRotation()
    v = rock.GetVelocityTG()
    radius = effective_radius(rock)
    hull = rock.GetHull()
    parent_max = float(hull.GetMaxCondition()) if hull is not None else stats.size_hull(radius)
    parent_mass = float(rock.GetMass())
    family = rock.__dict__.get("_rock_family", "silicate")
    parent_gen = int(rock.__dict__.get("_rock_generation", 0))
    gen = parent_gen + 1
    _enqueue(_vfx_specs, [DeathVfxSpec((loc.x, loc.y, loc.z), radius, pSet)])
    major_i = 0
    pieces = []
    chunk_specs = []
    for i, p in enumerate(breakup.plan(name, radius, generation=parent_gen)):
        d = TGPoint3(*p.offset)
        d.MultMatrixLeft(R)                  # body -> world
        at = (loc.x + d.x * radius * 0.5, loc.y + d.y * radius * 0.5,
              loc.z + d.z * radius * 0.5)
        sp = breakup.kSeparationSpeedGU
        vel = (v.x + d.x * sp, v.y + d.y * sp, v.z + d.z * sp)
        if centre is not None:
            vel = _strip_inward(vel, at, centre)
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
            # Only the remnant may stay targetable, and only at a BUILT
            # radius (RockClass_Create quantises: planned 1.96 is a 2.0 GU
            # rock, and the player sees the built one) >= the threshold.
            if (p.rank != "remnant" or float(piece.GetRadius())
                    < breakup.kTargetableMinRadiusGU):
                piece.SetTargetable(0)    # still solid: shoot it by aiming
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
    # Chunk specs wait for the majors: they carry every piece, and the killer.
    ghosted = [rock] + pieces + ([killer] if killer is not None else [])
    _enqueue(_chunk_specs, [replace(s, ghost_peers=tuple(ghosted))
                            for s in chunk_specs])
    if pieces:
        _ghost(ghosted)


def _enqueue(queue: list, items: list) -> None:
    """Append to a render-side queue, dropping the oldest past
    kMaxQueuedSpecs."""
    queue.extend(items)
    over = len(queue) - kMaxQueuedSpecs
    if over > 0:
        del queue[:over]


def _set_pairs(objs, on) -> None:
    """EnableCollisionsWith both ways for every pair in `objs`. Raise-safe per
    pair, so a piece that has since left the world cannot stop the rest.

    An object whose class has no EnableCollisionsWith (a Planet is not a
    DamageableObject) is masked from the other side only -- calling it on
    the instance would hit TGObject's silent _Stub. resolve_collisions reads
    the mask symmetrically, so one side is enough."""
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            for x, y in ((a, b), (b, a)):
                if getattr(type(x), "EnableCollisionsWith", None) is None:
                    continue
                try:
                    x.EnableCollisionsWith(y, 1 if on else 0)
                except Exception as e:
                    dev_mode.log_swallowed("rock piece collision mask", e)


def _ghost(objs) -> None:
    """Mask every pair in `objs`; each is unmasked by _advance_ghosts once its
    contact spheres are clear, or after kGhostMaxTime."""
    _set_pairs(objs, False)
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            _ghosts.append({"a": a, "b": b, "time_left": breakup.kGhostMaxTime})


def _advance_ghosts(dt: float) -> None:
    from engine.appc.collisions import ghost_peer_gone, spheres_clear
    done = []
    for g in list(_ghosts):
        g["time_left"] -= dt
        a, b = g["a"], g["b"]
        if ghost_peer_gone(a) or ghost_peer_gone(b):
            done.append(g)               # dropped; _set_pairs is raise-safe
        elif g["time_left"] <= 0.0:
            done.append(g)
        else:
            try:
                clear = spheres_clear(a, b, breakup.kGhostSeparationMarginGU)
            except Exception as e:
                dev_mode.log_swallowed("rock ghost separation", e)
                clear = True             # deliberate fail-open, logged
            if not clear:
                continue
            done.append(g)
        _set_pairs([a, b], True)
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
    global _warned_setless
    _warned_setless = False
    _dying.clear()
    _ghosts.clear()
    _chunk_specs.clear()
    _vfx_specs.clear()
