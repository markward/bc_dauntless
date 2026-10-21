"""Plating wear from the hull damage a hit actually dealt.

Every weapon's real hull damage becomes wear in the instance's
HullDamageStore. Projectile and collision wear is sent on EVERY hit
(`host_io.hull_damage_add`): the C++ store merges co-located hits, so nothing
is gained by summing here and a volley spread over the hull lands where each
shot struck. Only phaser ticks accumulate (a beam deposits a few hull per
tick, every tick): the pending entry is kept in the ship's BODY frame,
converted once when the tick lands, so a ship that moves or turns before the
flush still gets the wear where the beam touched it. A pending entry is sent
on the scorch-throttle emit, by `drain` once the window elapses, and early
when a new tick lands farther from it than the store would merge.

On an articulated (posed) ship the wear bindings attribute each point to the
part it lies on, by geometry, and store it in that part's REST frame, so the
damage moves with the part (layered damage phase 4 §2.1). Nothing here names
a part: a pending phaser entry holds a POSED body point and is attributed
when it is sent, with the pose the part has then (the window is
DECAL_EMIT_INTERVAL, 0.2 s), so the per-tick path pays nothing for it.
Visible damage only: nothing here touches hull, subsystem or shield health.

The constants are plain module values (not wired into a dial group: the
plating dial group is mirrored by native param slots, which is more than this
task warrants).
"""
from engine import host_io

REFERENCE_DAMAGE = 500.0       # stock photon hull damage == 1 wear
PROJECTILE_MIN = 0.25
PROJECTILE_MAX = 1.5
PHASER_RATE = 1.0              # x hull damage / REFERENCE_DAMAGE, per tick
COLLISION_MIN_HULL_DAMAGE = 100.0
COLLISION_MAX = 1.5
# Mirrors HullDamageStore::kMergeFactor: a tick farther than this x reach from
# the pending point would not merge in the store, so it flushes the pending.
MERGE_FACTOR = 0.5

_SURFACE = 1


class _Pending:
    """Held phaser wear for one ship, in its body frame (model units).
    `ship` is a strong reference for the entry's (short) life, so id(ship)
    can never be recycled onto a new ship while wear is pending; sending the
    entry releases it."""
    __slots__ = ("ship", "iid", "body_point", "body_normal", "radius",
                 "model_per_gu", "wear", "since")

    def __init__(self, ship, iid, body_point, body_normal, radius,
                 model_per_gu, wear, since):
        self.ship = ship
        self.iid = iid
        self.body_point = body_point
        self.body_normal = body_normal
        self.radius = radius
        self.model_per_gu = model_per_gu
        self.wear = wear
        self.since = since


# id(ship) -> _Pending
_pending: dict = {}


def _now():
    from engine.appc import damage_decals
    return damage_decals.current_game_time()


def wear_for_hit(weapon_type, absorbed_hull, decal_dent=0.0):
    if absorbed_hull <= 0.0:
        return 0.0
    base = absorbed_hull / REFERENCE_DAMAGE
    if weapon_type == "phaser":
        return min(base * PHASER_RATE, PROJECTILE_MAX)
    if weapon_type == "collision":
        if decal_dent != 1 or absorbed_hull < COLLISION_MIN_HULL_DAMAGE:
            return 0.0
        return min(base, COLLISION_MAX)
    return max(PROJECTILE_MIN, min(base, PROJECTILE_MAX))


def _after_wear(ship, iid):
    """Wear is in the store: may it have cut a structure part off?
    (hull_breakup.after_wear, throttled per ship.) Isolated: a failure there
    must never cost the hit its wear."""
    if ship is None:
        return
    try:
        from engine.appc import hull_breakup
        hull_breakup.after_wear(ship, iid)
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("hull_breakup.after_wear", _e)


def send(iid, world_point, world_normal, radius, wear, ship=None):
    """One projectile/collision hit's wear, straight to the store, then the
    part check for `ship` (None: no check)."""
    if wear <= 0.0 or radius <= 0.0:
        return
    host_io.hull_damage_add(iid, world_point, world_normal, radius, wear,
                            _SURFACE)
    _after_wear(ship, iid)


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def accumulate_phaser(ship, iid, world_point, world_normal, radius, wear):
    """Hold a phaser tick's wear in the ship's body frame. A tick landing
    farther than MERGE_FACTOR x reach from the pending point sends the
    pending entry first and starts a new one there."""
    if wear <= 0.0 or radius <= 0.0:
        return
    conv = host_io.world_to_body(iid, world_point, world_normal)
    if conv is None:
        return                                  # stale instance
    body_point, body_normal = conv
    entry = _pending.get(id(ship))
    if entry is not None and entry.ship is ship and entry.iid == iid:
        reach_model = max(entry.radius, radius) * entry.model_per_gu
        if _dist(body_point, entry.body_point) <= MERGE_FACTOR * reach_model:
            entry.wear += wear
            return
        flush(ship)
    # Model units per game unit, measured once per entry through the same
    # conversion the point took: a second point one radius away (rotation
    # and uniform scale keep lengths, so any direction serves).
    off = (world_point[0] + radius, world_point[1], world_point[2])
    conv_off = host_io.world_to_body(iid, off, world_normal)
    if conv_off is None:
        return
    model_per_gu = _dist(conv_off[0], body_point) / radius
    _pending[id(ship)] = _Pending(ship, iid, tuple(body_point),
                                  tuple(body_normal), radius, model_per_gu,
                                  wear, _now())


def _send_pending(entry):
    host_io.hull_damage_add_body(entry.iid, entry.body_point,
                                 entry.body_normal, entry.radius, entry.wear,
                                 _SURFACE)
    _after_wear(entry.ship, entry.iid)


def flush(ship):
    entry = _pending.pop(id(ship), None)
    if entry is not None and entry.ship is ship:
        _send_pending(entry)


def drain(now=None):
    """Per tick: send every pending entry whose throttle window has elapsed,
    so wear held after a beam stops is never stranded."""
    from engine.appc import hit_feedback
    now = _now() if now is None else now
    for key, entry in list(_pending.items()):
        if now - entry.since >= hit_feedback.DECAL_EMIT_INTERVAL:
            del _pending[key]
            _send_pending(entry)


def reset():
    _pending.clear()
