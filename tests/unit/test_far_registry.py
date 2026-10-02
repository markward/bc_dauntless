"""The far-tier registry (far-tier plan Task 10): which rocks are flagged,
which frame is viewed, and what is pushed to native when."""
from engine.rocks import far_tier


class _R:
    def __init__(self):
        self.calls = []
        self._next_handle = 0
    def load_model(self, nif_path, texture_search_path, texture_replacements=None,
                   decals=None, scale=1.0):
        """Mirrors engine.renderer.load_model: a fresh handle per load."""
        self.calls.append(("load_model", (nif_path, texture_search_path,
                                          texture_replacements, decals, scale)))
        self._next_handle += 1
        return self._next_handle
    def __getattr__(self, name):
        def rec(*a, **k):
            self.calls.append((name, a))
            return True
        return rec


def _names(r):
    return [c[0] for c in r.calls]


def test_note_model_flags_catalogue_rocks_only(monkeypatch):
    from engine.rocks import catalogue
    from engine.rocks.rock import RockClass_Create
    rocks = catalogue.load()
    lod0 = rocks[3].lod_paths[0]

    from pathlib import Path
    from engine import paths
    monkeypatch.setattr(paths, "game_root", lambda: Path("/x"))
    cat_rock = RockClass_Create(2.0, name="Cat Rock", kind="major")
    far_tier.note_model(cat_rock, lod0, 2.5)
    stock_rock = RockClass_Create(2.0, name="Stock Rock", kind="major")
    far_tier.note_model(
        stock_rock, "/x/data/models/misc/asteroids/asteroid1.nif", 1.0)

    class _Ship:
        pass
    ship = _Ship()
    far_tier.note_model(ship, lod0, 1.0)

    flagged = far_tier.desired_rocks({cat_rock: 11, stock_rock: 12, ship: 13})
    assert flagged[0]["instance"] == 11 and flagged[0]["index"] == 3
    assert abs(flagged[0]["radius_mu"] - 57.142857 * 2.5) < 1e-4
    assert flagged[1] == {"instance": 12, "index": -1,
                          "radius_mu": catalogue.STOCK_RADIUS_MU["asteroid1.nif"]}
    assert len(flagged) == 2


def test_a_mods_own_stock_named_asteroid_is_not_flagged(monkeypatch):
    """A mod overriding a stock asteroid NIF in place keeps its own mesh, of
    unknown size: only a genuine stock NIF under the configured game root
    gets STOCK_RADIUS_MU. The mod's rock stays unflagged (mesh at all
    distances), and forgets an earlier stock note."""
    from pathlib import Path
    from engine import paths
    from engine.rocks.rock import RockClass_Create
    monkeypatch.setattr(paths, "game_root", lambda: Path("/bc"))
    rock = RockClass_Create(2.0, name="Mod Rock", kind="major")
    far_tier.note_model(rock, "/bc/data/Models/Misc/Asteroids/asteroid1.nif", 1.0)
    assert far_tier.desired_rocks({rock: 1})[0]["index"] == -1
    far_tier.note_model(rock, "/mods/X/data/Models/Misc/Asteroids/asteroid1.nif", 1.0)
    assert far_tier.desired_rocks({rock: 1}) == []


def test_a_rock_with_a_non_rock_model_is_not_flagged():
    from engine.rocks.rock import RockClass_Create
    rock = RockClass_Create(2.0, name="Odd Rock", kind="major")
    far_tier.note_model(rock, "/mods/odd/rock.nif", 1.0)
    assert far_tier.desired_rocks({rock: 1}) == []


def test_rocks_pushed_only_on_change():
    r = _R()
    far_tier.reconcile_with(r, None, {})
    far_tier.reconcile_with(r, None, {})
    assert _names(r).count("far_set_rocks") == 1


def test_catalogue_and_dials_pushed_once():
    r = _R()
    far_tier.reconcile_with(r, None, {})
    far_tier.reconcile_with(r, None, {})
    assert _names(r).count("far_set_catalogue") == 1
    assert _names(r).count("far_set_dials") == 1
    (entries, dirs) = next(a for n, a in r.calls if n == "far_set_catalogue")
    from engine.rocks import catalogue
    assert len(entries) == len(catalogue.load())
    assert {"albedo", "normal", "avg_albedo", "kind", "family",
            "bound_radius_mu"} <= set(entries[0])
    assert len(dirs) == len(catalogue.impostor_view_dirs())


def test_a_native_dial_change_repushes_the_dials():
    from engine.rocks import far_dials
    r = _R()
    far_tier.reconcile_with(r, None, {})
    far_dials._step("haze_gain", +1)
    far_tier.reconcile_with(r, None, {})
    pushes = [a[0] for n, a in r.calls if n == "far_set_dials"]
    assert len(pushes) == 2
    assert pushes[1]["haze_gain"] == far_dials.get("haze_gain")


def test_frame_is_pushed_every_frame_and_sources_on_change(monkeypatch):
    monkeypatch.setattr(far_tier, "frame_for", lambda v: ("Vesuvi", (1.0, 2.0, 3.0)))
    r = _R()
    far_tier.reconcile_with(r, object(), {})
    far_tier.reconcile_with(r, object(), {})
    assert _names(r).count("far_set_frame") == 2
    assert _names(r).count("far_set_sources") == 1


def test_population_dial_change_repushes_sources(monkeypatch):
    from engine.rocks import far_dials
    monkeypatch.setattr(far_tier, "frame_for", lambda v: ("Vesuvi", (0.0, 0.0, 0.0)))
    r = _R()
    far_tier.reconcile_with(r, object(), {})
    far_dials._step("scale_height_frac", +1)
    far_tier.reconcile_with(r, object(), {})
    assert _names(r).count("far_set_sources") == 2


def test_leaving_a_system_pushes_empty_sources(monkeypatch):
    frames = iter([("Vesuvi", (0.0, 0.0, 0.0)), (None, (0.0, 0.0, 0.0))])
    monkeypatch.setattr(far_tier, "frame_for", lambda v: next(frames))
    r = _R()
    far_tier.reconcile_with(r, object(), {})
    far_tier.reconcile_with(r, object(), {})
    pushes = [a[0] for n, a in r.calls if n == "far_set_sources"]
    assert len(pushes) == 2 and pushes[1] == []


def test_warp_set_has_no_frame():
    class _Warp:
        def GetName(self): return "warp"
    assert far_tier.frame_for(_Warp())[0] is None
    assert far_tier.frame_for(None)[0] is None


def test_reset_clears_native_and_forgets_models():
    from engine.rocks.rock import RockClass_Create
    rock = RockClass_Create(2.0, name="Stock Rock", kind="major")
    far_tier.note_model(rock, "/x/data/models/misc/asteroids/asteroid.nif", 1.0)
    r = _R()
    far_tier.reset(r)
    assert "far_clear" in _names(r)
    assert far_tier.desired_rocks({rock: 1}) == []


def test_reset_makes_the_next_reconcile_push_everything_again():
    r = _R()
    far_tier.reconcile_with(r, None, {})
    far_tier.reset(None)
    far_tier.reconcile_with(r, None, {})
    for name in ("far_set_catalogue", "far_set_dials", "far_set_rocks"):
        assert _names(r).count(name) == 2, name


def test_reconcile_never_raises():
    class _Boom:
        def __getattr__(self, name):
            raise RuntimeError("renderer down")
    far_tier.reconcile(object(), _Boom())


def test_a_failed_catalogue_push_is_retried(monkeypatch):
    """The root counts as pushed only once far_set_catalogue succeeded; a
    raising catalogue load or native call is swallowed and retried."""
    from engine.rocks import catalogue
    far_tier.reset(None)
    calls = []

    class _Flaky(_R):
        def far_set_catalogue(self, *a):
            calls.append(a)
            if len(calls) == 1:
                raise RuntimeError("native refused")

    r = _Flaky()
    far_tier.reconcile_with(r, None, {})
    far_tier.reconcile_with(r, None, {})
    assert len(calls) == 2
    far_tier.reconcile_with(r, None, {})
    assert len(calls) == 2, "pushed once it succeeded"

    far_tier.reset(None)
    real_load = catalogue.load

    def boom():
        raise RuntimeError("catalogue unreadable")
    monkeypatch.setattr(catalogue, "load", boom)
    far_tier.reconcile_with(r, None, {})          # must not raise
    monkeypatch.setattr(catalogue, "load", real_load)
    far_tier.reconcile_with(r, None, {})
    assert len(calls) == 3, "a failed load is retried"


# ── Tile-field haze (added 2026-10-02) ───────────────────────────────────────


class _Loc:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Set:
    def __init__(self, name):
        self._name = name
    def GetName(self):
        return self._name


class _Field:
    def __init__(self, pSet, name="Asteroid Field 1", loc=(1.0, 2.0, 3.0), per_tile=15):
        self._set, self._name, self._loc, self._per = pSet, name, loc, per_tile
    def GetContainingSet(self): return self._set
    def GetName(self): return self._name
    def GetWorldLocation(self): return _Loc(*self._loc)
    def GetFieldRadius(self): return 1000.0
    def GetNumTilesPerAxis(self): return 3
    def GetNumAsteroidsPerTile(self): return self._per
    def GetAsteroidSizeFactor(self): return 7.0


def _source_pushes(r):
    return [a[0] for n, a in r.calls if n == "far_set_sources"]


def test_one_sphere_source_per_field_in_the_viewed_set_only():
    view, other = _Set("Multi7"), _Set("Elsewhere")
    fields = [_Field(view, "F1", (10.0, 0.0, 0.0)), _Field(view, "F2", (0.0, 20.0, 0.0)),
              _Field(other, "F3")]
    r = _R()
    far_tier.reconcile_with(r, view, {}, fields)
    (pushed,) = _source_pushes(r)
    assert [d["shape"] for d in pushed] == ["sphere", "sphere"]
    assert [d["centre"] for d in pushed] == [(10.0, 0.0, 0.0), (0.0, 20.0, 0.0)]
    assert all(d["view_space"] and not d["procedural"] for d in pushed)


def test_tile_sources_are_pushed_only_on_change():
    view = _Set("Multi7")
    fields = [_Field(view)]
    r = _R()
    far_tier.reconcile_with(r, view, {}, fields)
    far_tier.reconcile_with(r, view, {}, fields)
    assert len(_source_pushes(r)) == 1
    fields.append(_Field(view, "F2"))          # the field list changed
    far_tier.reconcile_with(r, view, {}, fields)
    assert len(_source_pushes(r)) == 2
    assert len(_source_pushes(r)[1]) == 2
    other = _Set("Other")                      # the viewed set changed
    far_tier.reconcile_with(r, other, {}, [_Field(other)])
    assert len(_source_pushes(r)) == 3


def test_a_tile_haze_dial_change_repushes_the_sources():
    from engine.rocks import far_dials
    view = _Set("Multi7")
    fields = [_Field(view)]
    r = _R()
    far_tier.reconcile_with(r, view, {}, fields)
    far_dials._step("tile_haze_gain", +1)
    far_tier.reconcile_with(r, view, {}, fields)
    pushes = _source_pushes(r)
    assert len(pushes) == 2
    assert pushes[1][0]["gain_scale"] == far_dials.get("tile_haze_gain") / far_dials.get("haze_gain")
    far_dials._step("tile_haze_edge_frac", -1)
    far_tier.reconcile_with(r, view, {}, fields)
    assert _source_pushes(r)[2][0]["sphere_edge_frac"] == far_dials.get("tile_haze_edge_frac")


def test_a_tile_haze_noise_dial_change_repushes_the_sources():
    from engine.rocks import far_dials
    view = _Set("Multi7")
    fields = [_Field(view)]
    r = _R()
    far_tier.reconcile_with(r, view, {}, fields)
    steps = [("tile_haze_noise_scale_gu", "noise_scale_gu"),
             ("tile_haze_noise_contrast", "noise_contrast"),
             ("tile_haze_noise_octaves", "noise_octaves"),
             ("tile_haze_steps", "steps")]
    for i, (dial, key) in enumerate(steps):
        far_dials._step(dial, +1)
        far_tier.reconcile_with(r, view, {}, fields)
        pushes = _source_pushes(r)
        assert len(pushes) == i + 2, dial
        assert pushes[-1][0][key] == far_dials.get(dial), dial
        assert far_dials.get(dial) != far_dials.DEFAULTS[dial], dial


def test_a_brightness_dial_change_repushes_the_sources(monkeypatch):
    from engine.rocks import far_dials
    monkeypatch.setattr(far_tier, "frame_for", lambda v: ("Vesuvi", (0.0, 0.0, 0.0)))
    view = _Set("Vesuvi1")
    fields = [_Field(view)]
    r = _R()
    far_tier.reconcile_with(r, view, {}, fields)
    far_dials._step("haze_brightness", +1)
    far_tier.reconcile_with(r, view, {}, fields)
    far_dials._step("tile_haze_brightness", -1)
    far_tier.reconcile_with(r, view, {}, fields)
    pushes = _source_pushes(r)
    assert len(pushes) == 3
    belt, tile = pushes[2]
    assert belt["brightness"] == far_dials.get("haze_brightness")
    assert tile["brightness"] == far_dials.get("tile_haze_brightness")
    assert belt["brightness"] != tile["brightness"]


def test_belts_and_tile_spheres_ride_together(monkeypatch):
    monkeypatch.setattr(far_tier, "frame_for", lambda v: ("Vesuvi", (0.0, 0.0, 0.0)))
    view = _Set("Vesuvi1")
    r = _R()
    far_tier.reconcile_with(r, view, {}, [_Field(view)])
    (pushed,) = _source_pushes(r)
    assert [d["shape"] for d in pushed] == ["disc", "sphere"]


def test_a_failing_field_gather_still_pushes_the_frame_and_rocks(monkeypatch):
    """reconcile(): a view whose GetClassObjectList raises loses only its
    tile haze -- far_set_frame and far_set_rocks still go out."""
    from engine.systems import frames

    class _BadView(_Set):
        def GetClassObjectList(self, *a):
            raise RuntimeError("boom")

    monkeypatch.setattr(frames, "viewing_set", lambda: _BadView("Multi7"))

    class _Session:
        ship_instances = {}
        scope_hidden = ()

    r = _R()
    far_tier.reconcile(_Session(), r)
    assert "far_set_frame" in _names(r)
    assert "far_set_rocks" in _names(r)
    assert _source_pushes(r) == [[]]


def test_catalogue_entries_carry_near_band_kind_family_and_lod_handles():
    """Rock fields Task 7: silicate fragments and majors carry lod0/lod1
    handles loaded as minors loads fragments; other families none."""
    from engine.rocks import catalogue
    r = _R()
    far_tier.reconcile_with(r, None, {})
    (entries, _dirs) = next(a for n, a in r.calls if n == "far_set_catalogue")
    rocks = catalogue.load()
    handles = set()
    for rock, e in zip(rocks, entries):
        assert e["kind"] == rock.kind and e["family"] == rock.family
        assert abs(e["bound_radius_mu"] - rock.bound_radius_m
                   * catalogue.MODEL_UNITS_PER_METRE) < 1e-9
        if rock.family == "silicate" and rock.kind in ("fragment", "major"):
            assert isinstance(e["lod0"], int) and isinstance(e["lod1"], int)
            assert e["lod0"] != e["lod1"]
            handles.update((e["lod0"], e["lod1"]))
        else:
            assert "lod0" not in e and "lod1" not in e
    assert any(e["kind"] == "fragment" and "lod0" in e for e in entries)
    assert any(e["kind"] == "major" and "lod0" in e for e in entries)
    loads = [a for n, a in r.calls if n == "load_model"]
    assert len(loads) == len(handles)
    assert all(a[1:] == ([], None, None, 1.0) for a in loads)


class _NearR(_R):
    """A renderer whose native near catalogue can be emptied (host re-init)."""
    def __init__(self):
        super().__init__()
        self.near_size = 0
    def far_set_catalogue(self, entries, view_dirs):
        self.calls.append(("far_set_catalogue", (entries, view_dirs)))
        self.near_size = sum(1 for e in entries if "lod0" in e)
    def rockfield_catalogue_size(self):
        return self.near_size


def test_an_emptied_native_near_catalogue_is_repushed():
    r = _NearR()
    far_tier.reconcile_with(r, None, {})
    far_tier.reconcile_with(r, None, {})
    assert _names(r).count("far_set_catalogue") == 1
    r.near_size = 0                       # host shutdown + init
    far_tier.reconcile_with(r, None, {})
    assert _names(r).count("far_set_catalogue") == 2
    assert r.near_size > 0


def test_a_catalogue_without_near_rocks_is_not_repushed_every_frame(monkeypatch):
    from engine.rocks import catalogue
    monkeypatch.setattr(far_tier, "_NEAR_FAMILY", "no-such-family")
    r = _NearR()
    for _ in range(3):
        far_tier.reconcile_with(r, None, {})
    assert _names(r).count("far_set_catalogue") == 1
    assert len(catalogue.load()) > 0
