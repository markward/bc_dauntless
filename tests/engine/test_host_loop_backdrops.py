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
