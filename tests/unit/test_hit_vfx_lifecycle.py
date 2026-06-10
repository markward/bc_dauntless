"""hit_vfx.spawn / update_ages / snapshot — transient impact sprites."""
import pytest
from engine.appc.math import TGPoint3
from engine.appc.hit_vfx import spawn, update_ages, snapshot, _active, Severity
from engine.appc import hit_vfx


@pytest.fixture(autouse=True)
def clear_registry():
    _active.clear()
    yield
    _active.clear()


def test_spawn_appends_with_age_zero():
    spawn(TGPoint3(1, 2, 3))
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["age"] == 0.0
    assert snap[0]["position"].x == 1.0


def test_update_ages_increments_each():
    spawn(TGPoint3(0, 0, 0))
    update_ages(dt=0.1)
    snap = snapshot()
    assert snap[0]["age"] == pytest.approx(0.1)


def test_update_ages_prunes_expired():
    spawn(TGPoint3(0, 0, 0))
    update_ages(dt=1.1)  # > 1.0 lifetime
    assert snapshot() == []


def test_snapshot_returns_copy_not_internal_list():
    spawn(TGPoint3(0, 0, 0))
    snap = snapshot()
    snap.clear()
    assert len(snapshot()) == 1


def test_multiple_spawns_independent():
    spawn(TGPoint3(1, 0, 0))
    update_ages(dt=0.6)
    spawn(TGPoint3(2, 0, 0))
    update_ages(dt=0.6)
    # First aged to 1.2 (pruned, > 1.0 lifetime); second to 0.6 (survives).
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["position"].x == 2.0
    assert snap[0]["age"] == pytest.approx(0.6)


def test_spark_bearing_descriptor_outlives_flash_only():
    # A flash-only hit prunes by _FLASH_LIFETIME; a spark-bearing hit must
    # survive far longer (covers the renderer's kSparkLife).
    hit_vfx._active.clear()
    spawn(TGPoint3(0, 0, 0))  # flash only (spark_count default 0)
    spawn(TGPoint3(9, 9, 9), instance_id=3, body_point=(0.0, 0.0, 0.0),
          body_normal=(0.0, 0.0, 1.0), spark_count=8)
    update_ages(dt=2.0)  # > _FLASH_LIFETIME (0.7), < _SPARK_LIFETIME (5.2)
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["spark_count"] == 8
    update_ages(dt=4.0)  # cumulative 6.0 > _SPARK_LIFETIME
    assert snapshot() == []


# ── extended spawn signature: normal + severity ────────────────────────────

def test_spawn_with_normal_and_severity_records_both():
    hit_vfx._active.clear()

    pos = TGPoint3(1.0, 2.0, 3.0)
    n = TGPoint3(0.0, 0.0, -1.0)
    hit_vfx.spawn(pos, normal=n, severity=Severity.HULL)

    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    entry = snap[0]
    assert entry["position"].x == 1.0
    assert entry["normal"].z == -1.0
    assert entry["severity"] == int(Severity.HULL)


def test_spawn_shield_severity_is_noop():
    """SHIELD severity is filtered at the Python side — the shield_hit
    pass on the renderer handles the bubble splash separately."""
    hit_vfx._active.clear()
    hit_vfx.spawn(TGPoint3(0, 0, 0), severity=Severity.SHIELD)
    assert hit_vfx.snapshot() == []


def test_spawn_legacy_call_defaults_to_hull():
    """Old call sites that pass only the point still work; severity
    defaults to HULL and normal defaults to None."""
    hit_vfx._active.clear()
    hit_vfx.spawn(TGPoint3(0, 0, 0))
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.HULL)
    assert snap[0]["normal"] is None


def test_lifetimes_cover_renderer_sprite_lives():
    """Flash-only descriptors must outlast the renderer's CRITICAL flash tail
    (0.65s); spark-bearing descriptors must outlast the renderer's kSparkLife
    (3.0s)."""
    from engine.appc import hit_vfx
    assert hit_vfx._FLASH_LIFETIME >= 0.65
    assert hit_vfx._SPARK_LIFETIME >= 3.0


def test_spawn_records_spark_anchor_and_kind():
    hit_vfx._active.clear()
    pos = TGPoint3(1.0, 2.0, 3.0)
    nrm = TGPoint3(0.0, 0.0, 1.0)
    spawn(pos, normal=nrm, severity=Severity.HULL,
          instance_id=7, body_point=(0.5, -0.5, 0.25),
          body_normal=(0.0, 0.0, 1.0), weapon_kind=1, spark_count=12)
    e = snapshot()[0]
    assert e["instance_id"] == 7
    assert e["body_point"] == (0.5, -0.5, 0.25)
    assert e["body_normal"] == (0.0, 0.0, 1.0)
    assert e["weapon_kind"] == 1
    assert e["spark_count"] == 12


def test_spawn_defaults_have_no_sparks():
    hit_vfx._active.clear()
    spawn(TGPoint3(0, 0, 0))
    e = snapshot()[0]
    assert e["spark_count"] == 0
    assert e["instance_id"] is None
