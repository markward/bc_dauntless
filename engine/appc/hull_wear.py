"""Plating wear from the hull damage a hit actually dealt.

Every weapon's real hull damage becomes wear in the instance's
HullDamageStore (`host_io.hull_damage_add`). Wear is summed across the scorch
decal throttle in `hit_feedback` so a volley inside the window is not dropped.
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

_SURFACE = 1

# id(ship) -> [iid, point, normal, radius, total_wear]
_pending: dict = {}


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


def accumulate(ship, iid, world_point, world_normal, radius, wear):
    if wear <= 0.0:
        return
    entry = _pending.get(id(ship))
    total = wear + (entry[4] if entry is not None else 0.0)
    _pending[id(ship)] = [iid, world_point, world_normal, radius, total]


def flush(ship):
    entry = _pending.pop(id(ship), None)
    if entry is None:
        return
    iid, point, normal, radius, wear = entry
    host_io.hull_damage_add(iid, point, normal, radius, wear, _SURFACE)


def reset():
    _pending.clear()
