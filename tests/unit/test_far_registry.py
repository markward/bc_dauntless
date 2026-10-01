"""The far-tier registry (far-tier plan Task 10): which rocks are flagged,
which frame is viewed, and what is pushed to native when."""
from engine.rocks import far_tier


class _R:
    def __init__(self):
        self.calls = []
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
    assert set(entries[0]) == {"albedo", "normal", "avg_albedo"}
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
