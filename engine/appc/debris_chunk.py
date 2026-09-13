"""Detached hull chunks: persistent, tumbling, COLLIDING debris.

When a carve severs a component of a breakable hull (spec: docs/superpowers/
specs/2026-09-11-breakable-hull-components-design.md), the native side has
already made a renderer instance for it and split its damage field out
(host_io.hull_split_detached). This module is the BODY: position,
orientation, velocity, tumble, mass and radius, integrated in Python each
frame and registered with the collision system so a chunk can be struck and
can strike. Deliberately NOT a ShipClass -- it carries exactly the surface
collisions._resolve_body reads, and GetHull() returns None so combat.apply_hit
on a chunk is a no-op: it never carves and never dies.

Chunks are persistent (no timer despawn -- that was the complaint against the
old death sequence), bounded instead by kMaxLiveChunks with oldest-first
eviction, and cleared on mission swap.
"""
import math
import random
import weakref

import engine.dev_mode as dev_mode
from engine.appc.math import TGPoint3, TGMatrix3

# -- Tuning (Python: turnable live without a rebuild) ------------------------
kChunkMinCells = 8            # smaller components vanish as particles instead
kMaxLiveChunks = 32
kChunkSeparationSpeed = 0.15  # GU/s, along parent-centre -> component-centroid
kChunkTumbleRate = 0.4        # rad/s about a random body axis

_live: list = []
_next_obj_id = 0x7C000000     # far above any SDK ObjID band
_X_AXIS = TGPoint3(1.0, 0.0, 0.0)
_Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
_Z_AXIS = TGPoint3(0.0, 0.0, 1.0)


class DebrisChunk:
    """`_loc` is the PIECE's centre (the component centroid in world space),
    not the parent's origin. The renderer instance shares the parent's model,
    whose origin is the ship's origin, so the mesh is placed at
    `_loc - R . centroid_body` each frame: the centroid then lands exactly on
    `_loc`, and the tumble rotates the piece about itself. With `_loc` at the
    model origin instead, a nacelle whose centroid sits 2 GU out swept a
    2 GU circle at ~0.8 GU/s -- an orbit, not a tumble -- and its collision
    sphere sat 2 GU away from the visible piece."""

    def __init__(self, iid, origin_ship, component_cells, mass, radius,
                 scale, centroid_body, loc, rot, vel, angular, obj_id):
        self.iid = iid
        # weakref: a chunk outlives its parent by design (spec §8, "parent
        # death"), and a strong ref here would pin a dead ship -- and its
        # transform slot -- for as long as the chunk lives.
        self._origin_ref = weakref.ref(origin_ship)
        self.component_cells = int(component_cells)
        self.mass = float(mass)
        self.radius = float(radius)
        self.scale = float(scale)
        self._centroid_body = centroid_body     # GU, parent body frame
        self._loc = loc
        self._rot = rot
        self._vel = vel
        # Same slot name ship_motion uses, body frame, so collisions.
        # _resolve_body picks it up for the contact-point velocity.
        self._current_angular_velocity = angular
        self._obj_id = obj_id
        # Symmetric pair mask collisions.resolve_collisions reads
        # (obj.__dict__["_collision_disabled_ids"]). The chunk is born INSIDE
        # its parent's sphere and recedes at kChunkSeparationSpeed, so
        # without this the grind channel abrades the parent for the ~20 s it
        # takes to clear. Emptied by tick() once the pair is clear, so a
        # later re-contact counts.
        self._collision_disabled_ids = frozenset()

    @property
    def origin_ship(self):
        return self._origin_ref()

    # -- the surface collisions._resolve_body reads --------------------------
    def GetWorldLocation(self): return self._loc
    def GetTranslate(self): return self._loc
    def SetTranslateXYZ(self, x, y, z): self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldRotation(self): return self._rot
    def GetRadius(self): return self.radius
    def GetMass(self): return self.mass
    def GetVelocity(self): return self._vel
    def GetScale(self): return self.scale
    def IsImmobile(self): return False
    def GetObjID(self): return self._obj_id
    def GetHull(self): return None   # no hull: apply_hit is a no-op on us

    def _mesh_origin(self):
        """Where the shared model's origin goes so the piece's centroid
        sits at `_loc` under the CURRENT rotation: `_loc - R . centroid`."""
        c = self._centroid_body
        off = TGPoint3(c.x, c.y, c.z)
        off.MultMatrixLeft(self._rot)                  # body -> world
        return TGPoint3(self._loc.x - off.x, self._loc.y - off.y, self._loc.z - off.z)

    def _release_parent_mask_if_clear(self):
        if not self._collision_disabled_ids:
            return
        parent = self._origin_ref()
        if parent is None:
            self._collision_disabled_ids = frozenset()
            return
        from engine.appc.collisions import COLLISION_RADIUS_SCALE
        p = parent.GetWorldLocation()
        dx, dy, dz = self._loc.x - p.x, self._loc.y - p.y, self._loc.z - p.z
        reach = (self.radius + float(parent.GetRadius())) * COLLISION_RADIUS_SCALE
        if dx * dx + dy * dy + dz * dz >= reach * reach:
            self._collision_disabled_ids = frozenset()


def spawn(iid, origin_ship, cells, centroid_gu, radius_gu,
          parent_mass, parent_occupied_cells, rng=None):
    """Create the body for a chunk the native side has already instanced.
    `centroid_gu` is BODY frame of the parent; the separation push is that
    direction rotated into world. Registered immediately; eviction past the
    cap happens on the next tick, when a renderer is in hand."""
    global _next_obj_id
    rng = rng or random
    ploc = origin_ship.GetWorldLocation()
    rot = origin_ship.GetWorldRotation()
    pv = origin_ship.GetVelocity()

    centroid = TGPoint3(*centroid_gu)
    world_c = TGPoint3(centroid.x, centroid.y, centroid.z)
    world_c.MultMatrixLeft(rot)                       # body -> world
    # The chunk's centre is the PIECE's centre, not the parent's origin.
    loc = TGPoint3(ploc.x + world_c.x, ploc.y + world_c.y, ploc.z + world_c.z)

    n = math.sqrt(world_c.x * world_c.x + world_c.y * world_c.y + world_c.z * world_c.z)
    if n > 1e-6:
        push = TGPoint3(world_c.x / n, world_c.y / n, world_c.z / n)
    else:
        push = TGPoint3(0.0, 0.0, 0.0)
    vel = TGPoint3(pv.x + push.x * kChunkSeparationSpeed,
                   pv.y + push.y * kChunkSeparationSpeed,
                   pv.z + push.z * kChunkSeparationSpeed)

    ax = TGPoint3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    an = math.sqrt(ax.x * ax.x + ax.y * ax.y + ax.z * ax.z) or 1.0
    angular = TGPoint3(ax.x / an * kChunkTumbleRate,
                       ax.y / an * kChunkTumbleRate,
                       ax.z / an * kChunkTumbleRate)

    frac = (float(cells) / float(parent_occupied_cells)) if parent_occupied_cells else 0.0
    mass = max(1.0, float(parent_mass) * frac)

    _next_obj_id += 1
    chunk = DebrisChunk(iid, origin_ship, cells, mass, radius_gu,
                        float(origin_ship.GetScale()) if hasattr(origin_ship, "GetScale") else 1.0,
                        centroid, loc, _copy_rot(rot), vel, angular, _next_obj_id)
    # Class lookup, not getattr on the instance: TGObject.__getattr__ vends a
    # truthy _Stub for any unknown name, and a fake parent in a test may
    # carry no ObjID at all.
    if getattr(type(origin_ship), "GetObjID", None) is not None:
        chunk._collision_disabled_ids = frozenset((origin_ship.GetObjID(),))
    _live.append(chunk)
    return chunk


def live():
    return list(_live)


def _copy_rot(rot):
    m = TGMatrix3()
    for c in range(3):
        col = rot.GetCol(c)
        m.SetCol(c, TGPoint3(col.x, col.y, col.z))
    return m


def _integrate_rotation(chunk, dt):
    cav = chunk._current_angular_velocity
    if not (cav.x or cav.y or cav.z):
        return
    # Body-frame delta POST-multiplies (R . D) -- CLAUDE.md rotation convention,
    # same construction as ship_motion._integrate_rotation.
    R = chunk._rot
    Rp = TGMatrix3(); Rp.MakeRotation(cav.x * dt, _X_AXIS)
    Ry = TGMatrix3(); Ry.MakeRotation(cav.z * dt, _Z_AXIS)
    Rr = TGMatrix3(); Rr.MakeRotation(cav.y * dt, _Y_AXIS)
    delta = Rp.MultMatrix(Ry).MultMatrix(Rr)
    chunk._rot = R.MultMatrix(delta)


def tick(dt, renderer):
    """Integrate every live chunk and push its transform. Applies cap
    eviction first so the renderer instance is destroyed here, not left
    dangling."""
    while len(_live) > kMaxLiveChunks:
        old = _live.pop(0)
        _destroy(old, renderer)
    from engine.host_loop import _world_matrix_from, BC_MODEL_SCALE
    for c in _live:
        v = c._vel
        c._loc = TGPoint3(c._loc.x + v.x * dt, c._loc.y + v.y * dt, c._loc.z + v.z * dt)
        _integrate_rotation(c, dt)
        c._release_parent_mask_if_clear()
        try:
            renderer.set_world_transform(
                c.iid, _world_matrix_from(c._mesh_origin(), c._rot,
                                          BC_MODEL_SCALE * c.scale))
        except Exception as _e:
            dev_mode.log_swallowed("debris chunk transform push", _e)


def _destroy(chunk, renderer):
    try:
        renderer.destroy_instance(chunk.iid)
    except Exception as _e:
        dev_mode.log_swallowed("debris chunk destroy_instance", _e)


def clear(renderer):
    """Mission swap / teardown: destroy every chunk's instance and empty the
    registry."""
    for c in _live:
        _destroy(c, renderer)
    _live.clear()
