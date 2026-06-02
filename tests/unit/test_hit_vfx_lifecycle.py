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
    update_ages(dt=0.8)  # > 0.7 lifetime
    assert snapshot() == []


def test_snapshot_returns_copy_not_internal_list():
    spawn(TGPoint3(0, 0, 0))
    snap = snapshot()
    snap.clear()
    assert len(snapshot()) == 1


def test_multiple_spawns_independent():
    spawn(TGPoint3(1, 0, 0))
    update_ages(dt=0.4)
    spawn(TGPoint3(2, 0, 0))
    update_ages(dt=0.4)
    # First aged to 0.8 (pruned, > 0.7 lifetime); second to 0.4 (survives).
    snap = snapshot()
    assert len(snap) == 1
    assert snap[0]["position"].x == 2.0
    assert snap[0]["age"] == pytest.approx(0.4)


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


def test_lifetime_widens_to_cover_critical_tail():
    """_LIFETIME must be at least 0.7s — CRITICAL kTotalLife in the renderer."""
    from engine.appc import hit_vfx
    assert hit_vfx._LIFETIME >= 0.7
