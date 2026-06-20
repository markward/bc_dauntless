from engine.appc import backdrops as bd


def _backdrop(kind, tex):
    b = bd.Backdrop(kind)
    b.SetTextureFileName(tex)
    return b


class _Set:
    def __init__(self, items): self._backdrops = items
    def GetName(self): return "TestSet"


def test_procedural_fields_classify_and_colour(monkeypatch, tmp_path):
    # fake appearance table
    monkeypatch.setattr(bd, "_appearance_table", lambda: {
        "treknebula6.tga": {"meanColor": [111, 94, 169], "palette": [], "coverage": 0.5},
        "galaxy4.tga":     {"meanColor": [55, 44, 44], "palette": [], "coverage": 0.31},
    })
    # make texture paths resolve: point project_root at a tmp tree with the files
    for sub in ("data",):
        (tmp_path / "game" / sub).mkdir(parents=True, exist_ok=True)
    for name in ("stars.tga", "treknebula6.tga", "galaxy4.tga"):
        (tmp_path / "game" / "data" / name).write_bytes(b"x")
    items = [
        _backdrop(bd.Backdrop.KIND_STAR, "data/stars.tga"),
        _backdrop(bd.Backdrop.KIND_BACKDROP, "data/treknebula6.tga"),
        _backdrop(bd.Backdrop.KIND_BACKDROP, "data/galaxy4.tga"),
    ]
    out = bd.aggregate_for_renderer(_Set(items), tmp_path)
    by_kind = {d["proc_kind"]: d for d in out}
    assert set(by_kind) == {"stars", "starcloud", "nebula"}
    # nebula colour is brightened dominant (max channel near 0.8)
    assert max(by_kind["nebula"]["color"]) > 0.75
    # starcloud keeps the dim galaxy mean (max channel < 0.5)
    assert max(by_kind["starcloud"]["color"]) < 0.5
    assert by_kind["nebula"]["coverage"] == 0.5
    # seed stable + per-texture distinct
    assert by_kind["nebula"]["seed"] != by_kind["starcloud"]["seed"]


def test_unknown_texture_is_graceful(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, "_appearance_table", lambda: {})
    (tmp_path / "game" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "game" / "data" / "mystery.tga").write_bytes(b"x")
    b = _backdrop(bd.Backdrop.KIND_BACKDROP, "data/mystery.tga")
    out = bd.aggregate_for_renderer(_Set([b]), tmp_path)
    assert out[0]["proc_kind"] == "nebula"
    assert "color" in out[0] and "seed" in out[0]  # defaults, no crash
