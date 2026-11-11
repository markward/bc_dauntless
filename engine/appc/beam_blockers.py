"""The first object in a beam's path (Python reference).

Spec: docs/superpowers/specs/2026-11-11-beam-blocking-design.md section 4.
The native K2 walk and the beam feed port ``first_blocker`` statement by
statement: keep the operand order and the broadphase order below as they are.

A candidate blocks only when something real is in the way: a mesh trace hit,
the shield bubble of a shielded ship, or (a planet with no renderer instance)
its sphere. A bare bounding-sphere graze never blocks a ship.
"""
import math
from dataclasses import dataclass
from typing import Optional

from engine.appc import combat
from engine.appc.collisions import world_radius
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet
from engine.systems import frames

PLANET_BOUND_SLACK: float = 1.02


@dataclass(frozen=True)
class Blocker:
    obj: object
    kind: str                       # "ship" | "planet"
    dist: float
    point: TGPoint3
    normal: Optional[TGPoint3]
    bubble: Optional[TGPoint3]
    tier: str                       # "mesh" | "sphere" | "bubble"


_step_ships: list = []
_step_planets: dict = {}


def begin_step(ships_list, planet_instances) -> None:
    global _step_ships, _step_planets
    _step_ships = ships_list
    _step_planets = planet_instances


def end_step() -> None:
    global _step_ships, _step_planets
    _step_ships = []
    _step_planets = {}


def step_ships():
    return _step_ships


def step_planets():
    return _step_planets


def contact_distance(emitter, impact_point, bubble_entry) -> float:
    p = bubble_entry if bubble_entry is not None else impact_point
    return _dist(emitter, p)


def _dist(a, b) -> float:
    dx = b.x - a.x
    dy = b.y - a.y
    dz = b.z - a.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def planet_rows(shooter_set, planet_instances):
    """Every Planet (a Sun included) in ``shooter_set`` with its renderer
    instance id, or None, in the set's object order."""
    rows = []
    if shooter_set is None:
        return rows
    for obj in shooter_set._objects.values():
        if isinstance(obj, Planet):
            rows.append((obj, planet_instances.get(obj)))
    return rows


def _in_reach(c, emitter, aim_unit, contact_dist, bound) -> bool:
    p = c.GetWorldLocation()
    vx = p.x - emitter.x
    vy = p.y - emitter.y
    vz = p.z - emitter.z
    t = vx * aim_unit.x + vy * aim_unit.y + vz * aim_unit.z
    if t < -bound or t > contact_dist + bound:
        return False
    if (vx * vx + vy * vy + vz * vz) - t * t > bound * bound:
        return False
    return True


def first_blocker(shooter, target, emitter, aim_unit, contact_dist,
                  ships, planet_instances, ship_instances):
    shooter_set = frames.containing_set(shooter)
    best = contact_dist
    found = None
    for c in ships:
        if c is shooter or c is target:
            continue
        if hasattr(c, "IsDead") and c.IsDead():
            continue
        if c.IsHidden():
            continue
        if frames.containing_set(c) is not shooter_set:
            continue
        bound = combat.bubble_bound_radius(c)
        if not _in_reach(c, emitter, aim_unit, contact_dist, bound):
            continue
        b = None
        if combat.shields_block(c):
            b = combat.shield_bubble_entry(c, emitter, aim_unit, contact_dist)
        if b is not None:
            d = _dist(emitter, b)
            if d < best:
                point, normal = combat._resolve_hit_point(
                    ship_instances, c, emitter, aim_unit,
                    contact_dist * 1.5, b)
                if normal is None:
                    point = b
                best = d
                found = Blocker(c, "ship", d, point, normal, b, "bubble")
            continue
        point, normal = combat._resolve_hit_point(
            ship_instances, c, emitter, aim_unit, contact_dist * 1.5,
            emitter)
        if normal is None:
            continue
        d = _dist(emitter, point)
        if d < best:
            best = d
            found = Blocker(c, "ship", d, point, normal, None, "mesh")
    for planet, iid in planet_rows(shooter_set, planet_instances):
        if planet is shooter or planet is target:
            continue
        if planet.IsHidden():
            continue
        if frames.containing_set(planet) is not shooter_set:
            continue
        radius = world_radius(planet)
        bound = radius * PLANET_BOUND_SLACK
        if not _in_reach(planet, emitter, aim_unit, contact_dist, bound):
            continue
        if iid is not None:
            point, normal = combat._resolve_hit_point(
                planet_instances, planet, emitter, aim_unit,
                contact_dist * 1.5, emitter)
            if normal is None:
                continue
            d = _dist(emitter, point)
            if d < best:
                best = d
                found = Blocker(planet, "planet", d, point, normal, None,
                                "mesh")
            continue
        point = combat.ray_sphere_entry(emitter, aim_unit, contact_dist,
                                        planet.GetWorldLocation(), radius)
        if point is None or point is emitter:
            continue
        d = _dist(emitter, point)
        if d < best:
            best = d
            found = Blocker(planet, "planet", d, point, None, None, "sphere")
    return found
