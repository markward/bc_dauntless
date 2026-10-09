"""engine.renderer's planet surface-detail dev-tuning wrappers (spec
2026-10-08 §7): OPTIONAL bindings, so a missing native function degrades to
a documented default/no-op rather than raising (this module is loaded in
headless tests with no real `_h`)."""
import engine.renderer as renderer


def test_wrappers_passthrough(monkeypatch):
    calls = {}

    class FakeH:
        def planet_detail_target_type(self):
            calls["target_type"] = True
            return 4

        def get_surface_type_params(self, t):
            calls["get"] = t
            return {"bump": 0.35}

        def set_surface_type_params(self, t, params):
            calls["set"] = (t, dict(params))

        def set_planet_detail_budget(self, cost):
            calls["budget"] = cost

        def set_planet_detail_debug(self, on):
            calls["debug"] = on

    monkeypatch.setattr(renderer, "_h", FakeH())
    assert renderer.planet_detail_target_type() == 4
    assert renderer.get_surface_type_params(4) == {"bump": 0.35}
    renderer.set_surface_type_params(4, {"bump": 0.5})
    renderer.set_planet_detail_budget(1024)
    renderer.set_planet_detail_debug(True)

    assert calls["get"] == 4
    assert calls["set"] == (4, {"bump": 0.5})
    assert calls["budget"] == 1024
    assert calls["debug"] is True


def test_wrappers_degrade_with_no_native_binding(monkeypatch):
    """A stale/minimal `_h` with none of the five bindings: reads return the
    documented default, writes are quiet no-ops -- never an AttributeError."""
    class EmptyH:
        pass

    monkeypatch.setattr(renderer, "_h", EmptyH())
    assert renderer.planet_detail_target_type() == 0
    assert renderer.get_surface_type_params(1) == {}
    renderer.set_surface_type_params(1, {"bump": 0.5})   # no-op, no raise
    renderer.set_planet_detail_budget(1024)               # no-op, no raise
    renderer.set_planet_detail_debug(True)                # no-op, no raise
