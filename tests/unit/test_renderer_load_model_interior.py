import engine.renderer as renderer


def test_load_model_forwards_interior_flag(monkeypatch):
    seen = {}
    def fake(nif, tex, reps, decals, scale, geosphere, interior, sibling_overlay_dirs):
        seen.update(geosphere=geosphere, interior=interior)
        return 7
    monkeypatch.setattr(renderer._h, "load_model", fake)
    assert renderer.load_model("x.nif", [], interior=True) == 7
    assert seen == {"geosphere": False, "interior": True}


def test_load_model_interior_defaults_off(monkeypatch):
    seen = {}
    monkeypatch.setattr(renderer._h, "load_model",
                        lambda *a: seen.setdefault("interior", a[6]) or 1)
    renderer.load_model("x.nif", [])
    assert seen["interior"] is False
