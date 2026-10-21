"""Tests for the BC visible-damage API -> Internal hull-damage records
(engine/appc/visible_damage.py + DamageableObject delegators).

Every authored (AddObjectDamageVolume, DamageTool) and runtime (AddDamage,
the death cascade) volume becomes one Internal record through
engine.host_io.hull_damage_add; these tests patch that wrapper with a
call-capturing spy (host_io owns the single guard point)."""
import pytest

from engine import host_io
from engine.appc import internal_blast, visible_damage
from engine.appc.math import TGMatrix3, TGPoint3

MIN_HOLE_RADIUS_GU = visible_damage.MIN_HOLE_RADIUS_GU


class _Ship:
    def __init__(self, loc=None, rot=None, radius_mod=None, radius=3.0):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._rot = rot or TGMatrix3()  # identity
        self._radius = radius
        if radius_mod is not None:
            self._vis_dmg_radius_mod = radius_mod

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return self._radius


class _RecordSpy:
    """Positional-arg capture matching host_io.hull_damage_add's signature."""

    def __init__(self):
        self.records = []  # (iid, point, normal, radius, wear, kind)
        self.rest_frame = []  # the rest_frame flag of each record, in order

    def __call__(self, iid, point, normal, radius, wear, kind, rest_frame=False):
        self.records.append((iid, point, normal, radius, wear, kind))
        self.rest_frame.append(rest_frame)


@pytest.fixture
def host(monkeypatch):
    """Patch host_io.hull_damage_add with a call-capturing spy and return it.
    No mesh to probe (the trace misses) and no part check, unless a test
    patches them itself."""
    from engine.appc import hull_breakup
    spy = _RecordSpy()
    monkeypatch.setattr(host_io, "hull_damage_add", spy)
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)
    monkeypatch.setattr(hull_breakup, "after_wear", lambda *a, **k: [])
    return spy


def _hole(influ, strength, radius_mod=1.0):
    """The record radius visible_damage gives a volume: its floor, capped by
    a cap that scales with strength / 600 (Ruling 5)."""
    floor = max(MIN_HOLE_RADIUS_GU, influ) * radius_mod
    rel = max(visible_damage.ADD_DAMAGE_HOLE_SCALE_MIN,
              min(visible_damage.ADD_DAMAGE_HOLE_SCALE_MAX, strength / 600.0))
    return min(floor, internal_blast.ADD_DAMAGE_MAX_HOLE_GU * rel)


@pytest.fixture(autouse=True)
def _clean():
    visible_damage.reset()
    yield
    visible_damage.reset()


# ── Body-frame authored volumes ─────────────────────────────────────────────

def test_body_volume_emits_an_internal_record_at_its_world_point(host):
    """A DamageTool volume (AddObjectDamageVolume) is an Internal record."""
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 7})

    assert len(host.records) == 1
    iid, point, normal, radius, wear, kind = host.records[0]
    assert iid == 7
    # Identity rotation, ship at origin -> world point == body point.
    assert point == pytest.approx((1.0, 0.0, 0.0))
    # Outward radial normal (unit).
    assert normal == pytest.approx((1.0, 0.0, 0.0))
    assert radius == pytest.approx(_hole(0.5, 300.0))
    assert kind == 3, "an Internal record"
    assert wear > 0.0


def test_body_volume_respects_ship_position_and_rotation(host):
    # 90 deg about Z: body (1,0,0) -> world (0,1,0), offset by ship location.
    rot = TGMatrix3().MakeZRotation(3.14159265358979 / 2.0)
    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0), rot=rot)
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 1})

    _iid, point, normal, _r, _w, _k = host.records[0]
    assert point == pytest.approx((10.0, -4.0, 2.0))   # loc + R.(1,0,0)
    assert normal == pytest.approx((0.0, 1.0, 0.0))


def test_radius_modifier_scales_the_floor(host):
    # Strength 1800 lifts the cap (3 x 0.35 GU) clear of the floor, so the
    # floor is what sizes the record.
    plain, scaled = _Ship(), _Ship(radius_mod=2.0)
    visible_damage.queue_body_volume(plain, 1.0, 0.0, 0.0, 0.1, 1800.0)
    visible_damage.queue_body_volume(scaled, 1.0, 0.0, 0.0, 0.1, 1800.0)
    visible_damage.advance(0.0, {plain: 1, scaled: 2})

    (_i1, _p1, _n1, r_plain, _w1, _k1), (_i2, _p2, _n2, r_scaled, _w2, _k2) = \
        host.records
    assert r_plain == pytest.approx(MIN_HOLE_RADIUS_GU)
    assert r_scaled == pytest.approx(MIN_HOLE_RADIUS_GU * 2.0)


# ── Deferral until the render instance is realized ──────────────────────────

def test_defers_until_instance_realized_then_emits_once(host):
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)

    # Not yet realized: kept, no emit.
    visible_damage.advance(0.1, {})
    assert host.records == []
    assert len(visible_damage._pending) == 1

    # Realized: emits exactly once...
    visible_damage.advance(0.1, {ship: 4})
    assert len(host.records) == 1
    # ...and is not re-emitted on the next tick.
    visible_damage.advance(0.1, {ship: 4})
    assert len(host.records) == 1
    assert visible_damage._pending == []


def test_unrealized_entry_ages_out(host):
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    # Never realized; age past MAX_PENDING_AGE -> dropped, never emitted.
    visible_damage.advance(visible_damage.MAX_PENDING_AGE + 1.0, {})
    assert host.records == []
    assert visible_damage._pending == []


def test_unrealized_ship_keeps_pending_and_never_raises():
    # No ship_instances mapping (unrealized render instance): the entry is kept,
    # nothing is emitted, and advance never raises even without any host_io
    # wrapper patched (the real host_io.hull_damage_add no-ops when the native
    # module is absent — the single guard point).
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.1, ship_instances={})            # unmapped ship
    visible_damage.advance(0.1, ship_instances=None)          # no map at all
    assert len(visible_damage._pending) == 1  # still waiting, nothing emitted


def test_authored_body_volume_is_sent_as_rest_frame(host):
    """Layered damage phase 4 §2.1: a DamageTool volume is authored in the
    ship's REST frame (mission init), so it opts out of the binding's posed
    part attribution (rest_frame=True, recorded on the hull body)."""
    ship = _Ship()
    visible_damage.queue_body_volume(ship, 1.0, 0.0, 0.0, 0.5, 300.0)
    visible_damage.advance(0.0, {ship: 7})
    assert host.rest_frame == [True]


def test_runtime_add_damage_is_attributed_to_the_posed_part(host):
    """AddDamage (the death cascade) lands at posed-time points: the binding
    attributes it (rest_frame False)."""
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})
    assert host.rest_frame == [False]


# ── Runtime world-space volume (AddDamage / DeathExplosionDamage) ──────────

def test_world_carve_passes_point_through_with_radial_normal(host):
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    _iid, point, normal, radius, _wear, kind = host.records[0]
    assert point == pytest.approx((13.0, 4.0, 0.0))   # already world-space
    assert normal == pytest.approx((0.6, 0.8, 0.0))   # unit (point - loc)
    assert radius == pytest.approx(_hole(0.6, 600.0))
    assert kind == 3


# ── clear / reset ───────────────────────────────────────────────────────────

def test_clear_for_drops_only_that_ships_pending():
    a, b = _Ship(), _Ship()
    visible_damage.queue_body_volume(a, 1, 0, 0, 0.5, 1)
    visible_damage.queue_body_volume(b, 1, 0, 0, 0.5, 1)
    visible_damage.clear_for(a)
    assert len(visible_damage._pending) == 1
    assert visible_damage._pending[0]["ship"] is b


def test_none_ship_is_ignored():
    visible_damage.queue_body_volume(None, 1, 0, 0, 0.5, 1)
    visible_damage.queue_world_carve(None, TGPoint3(0, 0, 0), 0.5, 1)
    assert visible_damage._pending == []


# ── DamageableObject delegators ─────────────────────────────────────────────

def test_damageable_object_methods_route_to_visible_damage():
    from engine.appc.objects import DamageableObject

    obj = DamageableObject()
    obj.SetTranslateXYZ(0.0, 0.0, 0.0)

    obj.AddObjectDamageVolume(1.0, 0.0, 0.0, 0.5, 300.0)
    assert len(visible_damage._pending) == 1

    obj.SetVisibleDamageRadiusModifier(2.0)
    assert obj._vis_dmg_radius_mod == pytest.approx(2.0)
    obj.SetVisibleDamageStrengthModifier(3.0)
    assert obj._vis_dmg_strength_mod == pytest.approx(3.0)

    obj.DamageRefresh()          # no-op, must not raise
    obj.AddDamage(TGPoint3(1.0, 2.0, 3.0), 0.4, 600.0)
    assert len(visible_damage._pending) == 2

    obj.RemoveVisibleDamage()    # clears this object's pending volumes
    assert visible_damage._pending == []


# ── True surface normal for world volumes ───────────────────────────────────
# The record is anchored on the hull and oriented by this normal. A
# radial-from-centre guess is nearly TANGENTIAL on a wide flat structure -- a
# Galaxy saucer sits ~2 GU off-axis but only ~0.3 GU above centre -- so a real
# mesh normal is worth the ray cast. The combat path always has one: it passes
# ray_trace's mesh normal.

def test_world_carve_prefers_the_mesh_surface_normal(host, monkeypatch):
    """A saucer-top hit: radial is nearly horizontal, the true normal is +Z."""
    hit_normal = (0.0, 0.0, 1.0)
    monkeypatch.setattr(host_io, "ray_trace_mesh",
                        lambda iid, o, d, m: ((13.0, 4.0, 0.3), hit_normal, 0.1))

    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.3), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    _iid, _point, normal, *_rest = host.records[0]
    assert normal == pytest.approx(hit_normal), (
        "the record used the radial guess where a real mesh normal was available")


def test_world_carve_probes_along_the_radial_toward_the_hull(host, monkeypatch):
    """The probe must start OUTSIDE the surface and fire inward, or it starts
    inside the hull and the trace exits through the far side. The FIRST probe
    is the radial one (a later one re-anchors along the mesh normal it
    found)."""
    seen = {}

    def _trace(iid, origin, direction, max_dist):
        seen.setdefault("origin", origin)
        seen.setdefault("direction", direction)
        return ((13.0, 4.0, 0.0), (0.0, 0.0, 1.0), 0.1)

    monkeypatch.setattr(host_io, "ray_trace_mesh", _trace)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    # Radial at that point is (0.6, 0.8, 0); origin sits outward along it and
    # the ray fires back inward.
    ox, oy, _oz = seen["origin"]
    assert ox > 13.0 and oy > 4.0, "probe did not start outside the surface"
    assert seen["direction"] == pytest.approx((-0.6, -0.8, 0.0))


def test_world_carve_falls_back_to_radial_when_the_trace_misses(host, monkeypatch):
    """Headless, no instance, or a grazing sample: keep the old behaviour
    rather than dropping the carve -- authored wrecks must still appear."""
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)

    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    _iid, _point, normal, *_rest = host.records[0]
    assert normal == pytest.approx((0.6, 0.8, 0.0))


def test_world_carve_survives_a_raising_trace(host, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no native module")
    monkeypatch.setattr(host_io, "ray_trace_mesh", _boom)

    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})

    assert host.records, "a failing normal probe must not lose the record"
    _iid, _point, normal, *_rest = host.records[0]
    assert normal == pytest.approx((0.6, 0.8, 0.0))


# ── Scuff seeding (developer Damage Preview) ────────────────────────────────

class _DecalSpy:
    def __init__(self):
        self.decals = []

    def __call__(self, iid, point, normal, radius, intensity, weapon_class, time,
                 world_tangent=None, dent=0.0):
        self.decals.append((iid, point, normal, radius, intensity, weapon_class,
                            time, world_tangent, dent))


@pytest.fixture
def decal_host(monkeypatch):
    spy = _DecalSpy()
    monkeypatch.setattr(host_io, "damage_decal_add", spy)
    return spy


def test_body_scuff_emits_a_scuff_decal_in_world_space(decal_host, host):
    from engine.appc.damage_decals import WEAPON_CLASS_SCUFF
    rot = TGMatrix3().MakeZRotation(3.14159265358979 / 2.0)   # body +X -> world +Y
    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0), rot=rot)
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.5,
                                    tangent_body=(0.0, 1.0, 0.0), intensity=0.7)
    visible_damage.advance(0.0, {ship: 1})

    assert host.records == [], "a scuff leaves no damage record"
    (iid, point, normal, radius, intensity, cls, _t, tangent, _dent), = decal_host.decals
    assert iid == 1
    assert point == pytest.approx((10.0, -4.0, 2.0))
    assert normal == pytest.approx((0.0, 1.0, 0.0))     # outward radial (no mesh)
    assert tangent == pytest.approx((-1.0, 0.0, 0.0))   # body +Y -> world -X
    assert radius == pytest.approx(1.5)
    assert intensity == pytest.approx(0.7)
    assert cls == WEAPON_CLASS_SCUFF


def test_body_scuff_defers_until_the_instance_is_realized(decal_host):
    ship = _Ship()
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.0)
    visible_damage.advance(0.0, {})
    assert decal_host.decals == []
    visible_damage.advance(0.0, {ship: 7})
    assert len(decal_host.decals) == 1
    visible_damage.advance(0.0, {ship: 7})
    assert len(decal_host.decals) == 1, "emitted once, then dropped"


def test_body_scuff_anchors_at_the_mesh_surface_not_the_authored_point(
        decal_host, host, monkeypatch):
    """The authored body point sits INSIDE the hull (0.1-0.3 GU below the
    surface, like any AddObjectDamageVolume sphere) -- a real collision decal
    anchors at _resolve_hit_point's mesh point (combat.py), so a preview
    scuff must too. Before this fix the scuff branch only asked _mesh_normal
    for the normal and kept the authored (interior) point regardless."""
    hit_point = (11.0, -4.2, 2.05)
    hit_normal = (0.0, 1.0, 0.0)
    monkeypatch.setattr(host_io, "ray_trace_mesh",
                        lambda iid, o, d, m: (hit_point, hit_normal, 0.05))

    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0))
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.5)
    visible_damage.advance(0.0, {ship: 1})

    assert host.records == [], "a scuff leaves no damage record"
    (_iid, point, normal, *_rest), = decal_host.decals
    assert point == pytest.approx(hit_point), (
        "scuff decal stayed at the authored (interior) point instead of the "
        "ray-traced hull surface")
    assert normal == pytest.approx(hit_normal)


def test_body_scuff_carries_its_dent_weight(decal_host):
    ship = _Ship()
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.0, dent=1.0)
    visible_damage.queue_body_scuff(ship, -1.0, 0.0, 0.0, radius_gu=1.0)
    visible_damage.advance(0.0, {ship: 1})
    assert [d[8] for d in decal_host.decals] == [1.0, 0.0]


# ── AddDamage -> an Internal hole record ────────────────────────────────────

def test_add_damage_leaves_an_internal_hole_record(monkeypatch):
    from engine.appc import internal_blast
    wear_calls = []
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: wear_calls.append(a))
    decals = []
    monkeypatch.setattr(host_io, "damage_decal_add",
                        lambda *a, **k: decals.append(a))
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.1, 150.0)
    visible_damage.advance(0.0, {ship: 2})
    assert decals == [], "no Internal decal any more"
    big, small = wear_calls
    assert big[5] == 3
    assert big[3] == pytest.approx(internal_blast.ADD_DAMAGE_MAX_HOLE_GU)   # capped
    assert small[3] == pytest.approx(min(max(MIN_HOLE_RADIUS_GU, 0.1),
                                         internal_blast.ADD_DAMAGE_MAX_HOLE_GU * 0.5))
    rooms = 4.5 + 0.7 * (6.0 - 4.5)
    assert big[4] == pytest.approx(rooms), "600: torn into the rooms, decks hold"
    assert small[4] == pytest.approx(rooms)


# ── Ruling 5: death holes tear into the rooms; only the big tier blows
#    through. A deliberate departure from BC's fixed fRadius x 0.25. ────────

def _record_adds(monkeypatch):
    calls = []
    monkeypatch.setattr(host_io, "hull_damage_add", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)
    return calls


def test_ordinary_death_holes_stay_below_deck_break(monkeypatch):
    from engine.appc import plating_dials
    calls = _record_adds(monkeypatch)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    for strength in (420.0, 600.0, 960.0, 1079.0):   # m 0.7 .. just under 1.8
        visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 1.0, strength)
    visible_damage.advance(0.0, {ship: 2})
    d = plating_dials.current()
    for c in calls:
        assert d["breach_wear"] < c[4] < d["deck_break_wear"]
        assert c[4] == pytest.approx(d["breach_wear"] + 0.7 * (
            d["deck_break_wear"] - d["breach_wear"]))


def test_the_big_tier_blows_through(monkeypatch):
    from engine.appc import internal_blast
    calls = _record_adds(monkeypatch)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    for strength in (1080.0, 1560.0):                 # m 1.8, 2.6
        visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 1.0, strength)
    visible_damage.advance(0.0, {ship: 2})
    assert [c[4] for c in calls] == pytest.approx([internal_blast.STRENGTH] * 2)


def test_room_wear_follows_the_live_dials(monkeypatch):
    from engine.appc import plating_dials
    calls = _record_adds(monkeypatch)
    monkeypatch.setattr(plating_dials, "_dials", dict(
        plating_dials.DEFAULTS, breach_wear=3.0, deck_break_wear=8.0))
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 1.0, 600.0)
    visible_damage.advance(0.0, {ship: 2})
    assert calls[0][4] == pytest.approx(3.0 + 0.7 * 5.0)


def test_the_hole_cap_scales_with_strength(monkeypatch):
    from engine.appc import internal_blast
    calls = _record_adds(monkeypatch)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    for strength in (150.0, 420.0, 1200.0, 6000.0):
        visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 5.0, strength)
    visible_damage.advance(0.0, {ship: 2})
    cap = internal_blast.ADD_DAMAGE_MAX_HOLE_GU
    assert [c[3] for c in calls] == pytest.approx(
        [cap * 0.5, cap * 0.7, cap * 2.0, cap * 3.0]), "clamp(s / 600, 0.5, 3)"


def test_carve_scale_sizes_only_the_visible_entry():
    """visible_damage.carve_scale(m) (the death cascade's blast size) scales
    the queued visible radius and strength while it is active, never after."""
    ship = _Ship()
    with visible_damage.carve_scale(2.0):
        assert visible_damage.current_carve_scale() == 2.0
        visible_damage.queue_world_carve(ship, TGPoint3(1.0, 0.0, 0.0), 0.5, 600.0)
    visible_damage.queue_world_carve(ship, TGPoint3(1.0, 0.0, 0.0), 0.5, 600.0)
    scaled, plain = visible_damage._pending
    assert (scaled["influ"], scaled["strength"]) == pytest.approx((1.0, 1200.0))
    assert (plain["influ"], plain["strength"]) == pytest.approx((0.5, 600.0))
    assert visible_damage.current_carve_scale() == 1.0


def test_add_damage_asks_for_severed_parts(monkeypatch):
    """The death cascade / scripted AddDamage wears the hull too: once its
    Internal record is in the store, the part check must run (a dying ship
    sheds parts like a fighting one)."""
    from engine.appc import hull_breakup
    order = []
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: order.append(("add", a[0])))
    monkeypatch.setattr(hull_breakup, "after_wear",
                        lambda ship, iid, *a, **k: order.append(("wear", ship, iid)))
    monkeypatch.setattr(host_io, "ray_trace_mesh", lambda *a, **k: None)
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0))
    visible_damage.queue_world_carve(ship, TGPoint3(13.0, 4.0, 0.0), 0.6, 600.0)
    visible_damage.advance(0.0, {ship: 2})
    assert order == [("add", 2), ("wear", ship, 2)], "after the add, once"
