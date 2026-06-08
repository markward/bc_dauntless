"""Root-cause regression: torpedo hits must emit a persistent damage decal.

Bug: `projectiles.update_all` resolved the mesh surface normal via
`_resolve_hit_point` but DISCARDED it (returned a 3-tuple), and
`host_loop._advance_combat` then passed `normal=None` to `apply_hit`. Since
`hit_feedback.dispatch` only emits a decal when `normal is not None`, NO
torpedo decal ever rendered in the live game — scorch was invisible.

The phaser path (the working reference) forwards its resolved `impact_normal`;
the torpedo path must do the same. These tests pin that contract.
"""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo, register, update_all, _active


@pytest.fixture(autouse=True)
def clear_registry():
    _active.clear()
    yield
    _active.clear()


class _FakeShip:
    """Minimal victim sufficient for update_all collision + apply_hit routing.

    Shields are absent (offline) so post-shield damage reaches the hull and
    `absorbed_hull > 0` — the condition dispatch requires to emit a decal.
    """
    def __init__(self, x, y, z, radius=10.0):
        self._loc = TGPoint3(x, y, z)
        self._r = radius
        self._hull = _Hull()
        self.damaged = []

    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r
    def IsDead(self): return 0
    def GetShields(self): return None              # offline -> full hull damage
    def GetHull(self): return self._hull
    def DamageSystem(self, sub, amt): self.damaged.append((sub, amt))
    def GetNumChildSubsystems(self): return 0      # no subsystems to iterate


class _Hull:
    def IsDestroyed(self): return 0


class _Host:
    """Renderer-host stub: a successful mesh trace + a recording decal sink."""
    def __init__(self, normal):
        self._normal = normal          # 3-tuple, as the real binding returns
        self.decal_calls = []

    def ray_trace_mesh(self, iid, origin, direction, max_dist):
        # (point, normal, t) — same shape the real binding returns.
        return ((5.0, 0.0, 0.0), self._normal, 5.0)

    def damage_decal_add(self, *, instance_id, world_point, world_normal,
                         radius, intensity, weapon_class, time):
        self.decal_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, weapon_class=weapon_class))


def _torp(src):
    t = Torpedo()
    t._position = TGPoint3(0, 0, 0)
    t._velocity = TGPoint3(10, 0, 0)
    t._ttl = 30.0
    t._age = 0.0
    t._source_ship = src
    t._damage = 100.0
    register(t)
    return t


def test_update_all_forwards_resolved_hit_normal():
    """update_all must return the mesh normal, not discard it."""
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    _torp(src)
    host = _Host(normal=(0.0, 0.0, 1.0))

    hits = update_all(0.1, [src, target],
                      host=host, ship_instances={target: "IID"})

    assert len(hits) == 1
    rec = hits[0]
    assert len(rec) == 4, \
        "update_all must forward the hit normal (got %d-tuple)" % len(rec)
    _t, ship, point, normal = rec
    assert ship is target
    assert normal is not None, "mesh-trace normal was discarded"
    assert abs(normal.z - 1.0) < 1e-6


def test_torpedo_path_emits_decal_end_to_end():
    """The full torpedo hit path (update_all -> apply_hit) emits a decal."""
    from engine.appc.combat import apply_hit
    from engine.appc import damage_decals as dd

    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    torp = _torp(src)
    host = _Host(normal=(0.0, 0.0, 1.0))
    ship_instances = {target: "IID"}

    hits = update_all(0.1, [src, target],
                      host=host, ship_instances=ship_instances)

    # Replicate host_loop._advance_combat's torpedo loop (the fixed form).
    for torpedo, ship, hit_point, hit_normal in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship,
                  normal=hit_normal, host=host, ship_instances=ship_instances,
                  weapon_type="torpedo", hardpoint_weapon=torpedo)

    assert len(host.decal_calls) == 1, "torpedo hull hit did not emit a decal"
    call = host.decal_calls[0]
    assert call["instance_id"] == "IID"
    assert call["weapon_class"] == dd.WEAPON_CLASS_SCORCH
