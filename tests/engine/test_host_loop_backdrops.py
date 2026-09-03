import types
import engine.host_loop as hl


class _Set:
    def GetName(self): return "Vesuvi6"


def test_map_driven_when_toggle_on(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    import engine.appc.sky_projection as sp
    monkeypatch.setattr(sp, "vantage_for_set", lambda pSet, model=None: [0.0, 0.0, 0.0])
    monkeypatch.setattr(sp, "project_sky", lambda v, m=None: [{"src": "map"}])
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "map"}]


def test_falls_back_to_authored_when_unmapped(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    import engine.appc.sky_projection as sp
    monkeypatch.setattr(sp, "vantage_for_set", lambda pSet, model=None: None)  # unmapped
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "authored"}]


def test_stock_when_toggle_off(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: False))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "authored"}]


# ---- warp transit backdrops ------------------------------------------------

class _Vfx:
    """Warp VFX manager stub: only sky_vantage is read during transit."""

    def __init__(self, vantage=(1.0, 2.0, 3.0)):
        self._v = vantage

    def sky_vantage(self, rate):
        return self._v


def test_transit_holds_the_static_starbox_when_sky_is_off(monkeypatch):
    """Procedural Sky off: the source set is deleted at burst, so a transit has
    no authored backdrops to aggregate and used to render black. The last
    starbox seen before the burst is held, unmoving, for the whole transit."""
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: False))
    hl._note_static_backdrops([{"src": "authored"}])
    vfx = _Vfx()
    assert hl._warp_transit_backdrops(vfx) == [{"src": "authored"}]
    # Held STATIC: the same descriptors every frame, no vantage advance.
    assert hl._warp_transit_backdrops(vfx) == [{"src": "authored"}]


def test_transit_static_starbox_is_not_aliased_to_the_remembered_list(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: False))
    hl._note_static_backdrops([{"src": "authored"}])
    out = hl._warp_transit_backdrops(_Vfx())
    out.append({"src": "mutated"})
    assert hl._warp_transit_backdrops(_Vfx()) == [{"src": "authored"}]


def test_transit_is_black_when_sky_off_and_nothing_remembered(monkeypatch):
    """Mission sets without authored backdrops still go black — documented
    fallback, not a regression."""
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: False))
    assert hl._warp_transit_backdrops(_Vfx()) == []


def test_transit_projects_the_flying_sky_when_procedural_sky_is_on(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    import engine.appc.sky_projection as sp
    monkeypatch.setattr(sp, "load_sector_model", lambda: None)
    monkeypatch.setattr(sp, "project_sky", lambda v, m=None: [{"src": "map", "v": v}])
    hl._note_static_backdrops([{"src": "authored"}])   # must NOT win here
    out = hl._warp_transit_backdrops(_Vfx(vantage=(4.0, 5.0, 6.0)))
    assert out == [{"src": "map", "v": (4.0, 5.0, 6.0)}]


def test_transit_is_black_when_sky_on_but_source_unmapped(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    assert hl._warp_transit_backdrops(_Vfx(vantage=None)) == []
