"""Stats probe against real SDK hardpoints. Values: roadmap 'Scale-bar reference
values' (Warbird hull 24,000; Sovereign shield total 49,500)."""
import pytest

pytest.importorskip("_dauntless_host")


@pytest.fixture
def sdk():
    from tools import mission_harness
    mission_harness.setup_sdk()
    import App
    return App


def test_stock_values(sdk):
    from engine.quickbattle import stats
    assert stats.probe("Warbird").hull == pytest.approx(24000.0)
    assert stats.probe("Sovereign").shields == pytest.approx(49500.0)


def test_probe_restores_local_templates(sdk):
    from engine.quickbattle import stats
    mgr = sdk.g_kModelPropertyManager
    sentinel = sdk.HullProperty_Create("SentinelHull")
    mgr.RegisterLocalTemplate(sentinel)
    before = dict(mgr._local)
    stats.probe("Galaxy")
    assert mgr._local == before


def test_probe_restores_templates_on_failure(sdk, monkeypatch):
    from engine.quickbattle import stats
    mgr = sdk.g_kModelPropertyManager
    mgr.RegisterLocalTemplate(sdk.HullProperty_Create("SentinelHull"))
    before = dict(mgr._local)
    assert stats.probe("NoSuchShipScript") is None
    assert mgr._local == before


def test_probe_restores_articulated_part_snapshot(sdk):
    """probe() reloads ships.Hardpoints.<leaf>, which re-fires
    sdk_overrides.on_sdk_module_exec -> articulated_part.snapshot_for_leaf,
    overwriting the process-wide _BY_LEAF[leaf] entry with freshly reloaded
    parts. A live SPV session mutates those objects in place while it has
    unsaved rig edits; a probe of the same leaf must never discard them."""
    from engine.quickbattle import stats
    from engine.appc import articulated_part

    real_before = dict(articulated_part._BY_LEAF)
    sentinel = object()
    articulated_part._BY_LEAF["galaxy"] = (sentinel,)
    before = dict(articulated_part._BY_LEAF)
    try:
        stats.probe("Galaxy")
        assert articulated_part._BY_LEAF == before
        assert articulated_part._BY_LEAF["galaxy"][0] is sentinel
    finally:
        articulated_part._BY_LEAF.clear()
        articulated_part._BY_LEAF.update(real_before)


def test_cache_and_playable_maxima(sdk):
    from engine.quickbattle import stats
    from engine import ship_catalog
    cache = stats.StatsCache()
    assert cache.get("Warbird") is cache.get("Warbird")
    hull_max, shield_max = cache.maxima(ship_catalog.entries())
    assert hull_max == pytest.approx(24000.0)       # Warbird: largest playable hull
    assert shield_max == pytest.approx(49500.0)     # Sovereign: largest playable shields
