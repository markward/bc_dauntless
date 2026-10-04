"""The minor-cloud registry (minor-rocks spec §1, §4): which clouds exist for
the viewed set, and the add/remove diff it sends to native."""
import zlib

import pytest

from engine.rocks import minor_dials as md
from engine.rocks import minors


class _Loc:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Rock:
    def __init__(self, name, r=4.0, family="icy"):
        self._name, self._r = name, r
        self.__dict__["_rock_family"] = family
    def GetName(self): return self._name
    def IsDead(self): return 0


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    md.reset()
    minors.reset(None)
    monkeypatch.setattr(minors, "_effective_radius", lambda rock: rock._r)
    monkeypatch.setattr(minors, "_is_dying", lambda rock: False)
    yield
    minors.reset(None)


def test_halo_spec_follows_the_dials():
    s = minors.halo_spec(_Rock("Asteroid 1", r=4.0), iid=object())
    assert s.key == "halo::Asteroid 1" and s.anchor == "instance"
    assert s.shell_inner == pytest.approx(4.4) and s.shell_outer == pytest.approx(12.0)
    assert s.count == 128                       # 8 x 16
    assert s.r_max == pytest.approx(0.6)        # min(0.15 x 4, 1.0)
    assert s.family == md.FAMILY_INDEX["icy"]


def test_halo_count_is_clamped():
    assert minors.halo_spec(_Rock("a", r=0.5), iid=1).count == 12
    assert minors.halo_spec(_Rock("b", r=50.0), iid=1).count == 400


def test_dying_rock_has_no_halo(monkeypatch):
    monkeypatch.setattr(minors, "_is_dying", lambda rock: True)
    assert minors.halo_spec(_Rock("a"), iid=1) is None


def test_no_catalogue_means_no_clouds(monkeypatch):
    from engine.rocks import catalogue
    monkeypatch.setattr(catalogue, "load", lambda: ())
    calls = []
    class _R:
        def __getattr__(self, n):
            return lambda *a, **k: calls.append(n)
        def minors_enabled(self): return True
    minors.reconcile_with(_R(), view_set=None, rock_instances={},
                          fields=[], player_iid=None)
    assert "minors_add_cloud" not in calls


def test_diff_adds_then_removes():
    added, removed = [], []
    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): added.append(d["id"])
        def minors_remove_cloud(self, i): removed.append(i)
        def minors_set_fragments(self, *a): pass
        def minors_set_player(self, *a): pass
        def minors_set_dials(self, *a): pass
        def load_model(self, *a, **k): return 7
    r = _R()
    rock = _Rock("A")
    minors.reconcile_with(r, view_set=None, rock_instances={rock: 11},
                          fields=[], player_iid=None)
    assert len(added) == 1
    minors.reconcile_with(r, view_set=None, rock_instances={rock: 11},
                          fields=[], player_iid=None)
    assert len(added) == 1                       # unchanged -> no re-add
    minors.reconcile_with(r, view_set=None, rock_instances={},
                          fields=[], player_iid=None)
    assert removed == added


def test_first_reconcile_does_not_fade_in_later_ones_do():
    descs = []
    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): descs.append(d)
        def __getattr__(self, n): return lambda *a, **k: 7
    r = _R()
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    minors.reconcile_with(r, None, {_Rock("A"): 1, _Rock("B"): 2}, [], None)
    assert descs[0]["fade_in"] is False and descs[1]["fade_in"] is True


def test_swap_reset_clears_registry():
    class _R:
        def minors_enabled(self): return True
        def __getattr__(self, n): return lambda *a, **k: 7
    minors.reconcile_with(_R(), None, {_Rock("A"): 1}, [], None)
    assert minors.native_ids()
    cleared = []
    class _C:
        def minors_clear(self): cleared.append(1)
    minors.reset(_C())
    assert minors.native_ids() == {} and cleared == [1]

def test_budget_evicts_oldest_free_cloud_first(monkeypatch):
    md._dials["max_live_minors"] = 100
    faded = []
    class _R:
        def minors_enabled(self): return True
        def minors_fade_out(self, i, s): faded.append(i)
        def __getattr__(self, n): return lambda *a, **k: 7
    r = _R()
    for name in ("old", "new"):
        minors.register_free_cloud(minors.FreeCloudSpec(
            name, None, (0, 0, 0), (0, 0, 0), 0.0, "silicate",
            tuple({"offset": (0, 0, 0), "v0": (0, 0, 0), "radius": 0.1, "seed": i}
                  for i in range(10)), 4.0))
        minors.reconcile_with(r, None, {}, [], None)
    big = _Rock("Big", r=50.0)                       # a 400-minor halo
    minors.reconcile_with(r, None, {big: 3}, [], None)
    ids = minors.native_ids()
    assert faded and faded[0] == ids["free::old"]
    assert "halo::Big" in ids                         # halos never evicted


# ── Beyond the brief's minimum: the rules the registry must also hold ─────────

class _Rec:
    """A renderer double that records every minors_* call, in order."""
    def __init__(self, enabled=True):
        self.calls = []
        self._enabled = enabled
        self._next = 100
    def minors_enabled(self): return self._enabled
    def load_model(self, path, *a, **k):
        self.calls.append(("load_model", path, a, k))
        self._next += 1
        return self._next
    def __getattr__(self, n):
        if not n.startswith("minors_"):
            raise AttributeError(n)
        return lambda *a, **k: self.calls.append((n,) + a)
    def named(self, n):
        return [c for c in self.calls if c[0] == n]


def _field(name="Asteroid Field 1", x=0.0, y=0.0, z=0.0):
    from engine.appc.asteroid_field import AsteroidField
    f = AsteroidField()
    f.SetName(name)
    f.SetTranslateXYZ(x, y, z)
    f.SetFieldRadius(100.0); f.SetNumTilesPerAxis(3)
    f.SetNumAsteroidsPerTile(2); f.SetAsteroidSizeFactor(10.0)
    return f


def test_every_desc_carries_every_native_key():
    r = _Rec()
    minors.register_free_cloud(_free("B"))
    minors.reconcile_with(r, None, {_Rock("A"): 5}, [], None)
    keys = {"id", "anchor", "instance", "point", "velocity", "t0",
            "shell_inner", "shell_outer", "falloff", "count", "r_min",
            "r_max", "size_exponent", "family", "seed", "orbit_rate",
            "fade_in", "debris"}
    descs = [c[1] for c in r.named("minors_add_cloud")]
    assert len(descs) == 2
    for d in descs:
        assert set(d) == keys
        assert isinstance(d["debris"], list)
    halo = next(d for d in descs if d["anchor"] == "instance")
    assert halo["instance"] == 5
    assert halo["seed"] == zlib.crc32(b"halo:A")


def test_fragments_load_once_per_family_and_reload_after_reset():
    from engine.rocks import catalogue
    icy = [c for c in catalogue.load() if c.kind == "fragment" and c.family == "icy"]
    assert icy, "the committed catalogue has icy fragments"
    r = _Rec()
    minors.reconcile_with(r, None, {_Rock("A", family="icy"): 1}, [], None)
    minors.reconcile_with(r, None, {_Rock("A", family="icy"): 1}, [], None)
    frags = r.named("minors_set_fragments")
    assert len(frags) == 1
    fam, entries = frags[0][1], frags[0][2]
    assert fam == md.FAMILY_INDEX["icy"]
    assert len(entries) == len(icy)
    assert entries[0][2] == pytest.approx(
        icy[0].bound_radius_m * catalogue.MODEL_UNITS_PER_METRE)
    # Far tier: the 4th element is the rock's speck albedo.
    assert all(len(e) == 4 for e in entries)
    assert [e[3] for e in entries] == [tuple(c.avg_albedo) for c in icy]
    loads = r.named("load_model")
    assert loads[0][1] == icy[0].lod_paths[0] and loads[1][1] == icy[0].lod_paths[1]
    assert loads[0][3].get("scale") == 1.0
    minors.reset(r)                       # native clear wipes the tables too
    minors.reconcile_with(r, None, {_Rock("A", family="icy"): 1}, [], None)
    assert len(r.named("minors_set_fragments")) == 2


def test_disabled_renderer_removes_every_native_cloud():
    r = _Rec()
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    (cid,) = minors.native_ids().values()
    r._enabled = False
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    assert ("minors_remove_cloud", cid) in r.calls
    assert minors.native_ids() == {}


def test_player_iid_is_pushed_every_frame():
    r = _Rec()
    minors.reconcile_with(r, None, {}, [], player_iid=42)
    minors.reconcile_with(r, None, {}, [], player_iid=None)
    # The first frame is a view change: the sweep is reset before the push.
    assert r.named("minors_set_player") == [("minors_set_player", None),
                                           ("minors_set_player", 42),
                                           ("minors_set_player", None)]


def test_first_reconcile_pushes_native_dials_and_a_native_change_repushes():
    r = _Rec()
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    assert r.named("minors_set_dials") == [("minors_set_dials", md.native())]
    md._step("shove_min_gups", +1)        # a NATIVE key
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    assert len(r.named("minors_set_dials")) == 2
    assert r.named("minors_set_dials")[-1][1]["shove_min_gups"] == pytest.approx(0.375)
    assert len(r.named("minors_add_cloud")) == 1      # native: no rebuild


def test_only_a_shape_dial_rebuilds_a_cloud():
    """Response / budget / debris dials are read at use and never rebuild
    (controller ruling): a rebuild would wipe the shove wake. A SHAPE dial
    changes the recomputed spec, so the per-key diff rebuilds exactly the
    clouds it affects."""
    r = _Rec()
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    (old,) = minors.native_ids().values()
    for dial in ("puff_spark_count", "grit_volume", "max_live_minors",
                 "free_cloud_fade_seconds", "debris_gravel_per_gu"):
        md._step(dial, +1)
        minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    assert r.named("minors_remove_cloud") == []
    assert minors.native_ids() == {"halo::A": old}
    md._step("halo_per_gu2", +1)          # a count change rebuilds
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    assert ("minors_remove_cloud", old) in r.calls
    assert r.named("minors_add_cloud")[-1][1]["count"] == 160


def _free(name, pSet=None, p0=(1.0, 2.0, 3.0), v=(0.5, 0.0, 0.0), t0=7.0):
    return minors.FreeCloudSpec(
        name, pSet, p0, v, t0, "metallic",
        ({"offset": (0.1, 0.0, 0.0), "v0": (1.0, 0.0, 0.0),
          "radius": 0.2, "seed": 9},), 4.0)


def test_free_spec_detaches_an_existing_halo_and_rekeys_it():
    r = _Rec()
    rock = _Rock("Rock 1")
    minors.reconcile_with(r, None, {rock: 1}, [], None)
    hid = minors.native_ids()["halo::Rock 1"]
    minors.register_free_cloud(_free("Rock 1"))
    minors.reconcile_with(r, None, {}, [], None)     # the dying rock is gone
    ids = minors.native_ids()
    assert "halo::Rock 1" not in ids and ids["free::Rock 1"] == hid
    det = r.named("minors_detach")
    assert len(det) == 1
    _, cid, p0, v, t0, debris = det[0]
    assert cid == hid and p0 == (1.0, 2.0, 3.0) and v == (0.5, 0.0, 0.0)
    assert t0 == 7.0 and debris == [{"offset": (0.1, 0.0, 0.0),
                                     "v0": (1.0, 0.0, 0.0),
                                     "radius": 0.2, "seed": 9}]
    assert ("minors_remove_cloud", hid) not in r.calls
    assert len(r.named("minors_add_cloud")) == 1     # never re-added


def test_pending_free_is_capped_dropping_the_oldest():
    """Headless nothing drains the pending queue (only reconcile does), so a
    long run of rock deaths must not grow it for ever: past kMaxPendingFree
    the oldest goes."""
    cap = minors.kMaxPendingFree
    assert cap == 256
    for i in range(cap + 7):
        minors.register_free_cloud(_free("Rock %d" % i))
    assert len(minors._pending_free) == cap
    assert minors._pending_free[0].rock_name == "Rock 7"
    assert minors._pending_free[-1].rock_name == "Rock %d" % (cap + 6)


def test_free_spec_without_a_halo_adds_a_free_cloud():
    r = _Rec()
    minors.register_free_cloud(_free("Rock 2"))
    minors.reconcile_with(r, None, {}, [], None)
    (d,) = [c[1] for c in r.named("minors_add_cloud")]
    assert d["anchor"] == "free" and d["point"] == (1.0, 2.0, 3.0)
    assert d["velocity"] == (0.5, 0.0, 0.0) and d["t0"] == 7.0
    # The halo's orbit rate: native freezes a Free cloud's orbit at t0.
    assert d["orbit_rate"] == md.get("halo_orbit_rate") and len(d["debris"]) == 1
    assert d["family"] == md.FAMILY_INDEX["metallic"]
    assert d["count"] == 128 and d["shell_outer"] == pytest.approx(12.0)
    assert d["seed"] == zlib.crc32(b"halo:Rock 2")
    assert minors.live_minor_count() == 129


def test_free_cloud_in_another_frame_is_not_sent_until_viewed():
    from engine.appc.sets import SetClass
    a, b = SetClass(), SetClass()
    a.SetName("A"); b.SetName("B")
    r = _Rec()
    minors.register_free_cloud(_free("Rock 3", pSet=b))
    minors.reconcile_with(r, a, {}, [], None)
    assert minors.native_ids() == {}
    minors.reconcile_with(r, b, {}, [], None)
    assert "free:B:Rock 3" in minors.native_ids()
    minors.reconcile_with(r, a, {}, [], None)           # viewed away: removed
    assert minors.native_ids() == {}
    minors.reconcile_with(r, b, {}, [], None)           # back: re-sent
    assert "free:B:Rock 3" in minors.native_ids()


def test_asteroid_fields_get_no_minor_cloud():
    """Rock-fields (Task 2): a BC AsteroidField is a density source (its
    near band, puffs and specks), never a 405-minor tile cloud."""
    from engine.appc.sets import SetClass
    a = SetClass()
    a.SetName("A")
    fa = _field("FA")
    a.AddObjectToSet(fa, "FA")
    for view in (None, a):
        desired = minors.desired_clouds(view_set=view, rock_instances={}, fields=[fa])
        assert not any(k.startswith("tile:") for k in desired)


def test_a_new_view_set_does_not_fade_in():
    from engine.appc.sets import SetClass
    a, b = SetClass(), SetClass()
    a.SetName("A"); b.SetName("B")
    minors.register_free_cloud(_free("RA", pSet=a))
    minors.register_free_cloud(_free("RB", pSet=b))
    r = _Rec()
    minors.reconcile_with(r, a, {}, [], None)
    minors.reconcile_with(r, b, {}, [], None)
    descs = [c[1] for c in r.named("minors_add_cloud")]
    assert [d["fade_in"] for d in descs] == [False, False]


def test_faded_free_cloud_is_removed_after_the_fade(monkeypatch):
    md._dials["max_live_minors"] = 10
    clock = [0.0]
    monkeypatch.setattr(minors, "_game_time", lambda: clock[0])
    r = _Rec()
    minors.register_free_cloud(_free("Old"))
    minors.reconcile_with(r, None, {}, [], None)
    cid = minors.native_ids()["free::Old"]
    assert r.named("minors_fade_out") == [("minors_fade_out", cid, 2.0)]
    clock[0] = 1.9
    minors.reconcile_with(r, None, {}, [], None)
    assert ("minors_remove_cloud", cid) not in r.calls
    clock[0] = 2.0
    minors.reconcile_with(r, None, {}, [], None)
    assert ("minors_remove_cloud", cid) in r.calls
    assert minors.native_ids() == {}
    minors.reconcile_with(r, None, {}, [], None)        # dropped, not re-added
    assert len(r.named("minors_add_cloud")) == 1


def test_a_failing_native_call_never_raises():
    class _Boom(_Rec):
        def __getattr__(self, n):
            def boom(*a, **k):
                raise RuntimeError("native down")
            return boom
    minors.reconcile_with(_Boom(), None, {_Rock("A"): 1}, [_field()], 3)


def test_reconcile_adapter_reads_the_session():
    from engine.rocks import rock as rock_mod
    calls = {}

    class _Sess:
        player = "P"
        ship_instances = {"P": 9}
        scope_hidden = set()

    def fake_with(r, view_set, rock_instances, fields, player_iid):
        calls.update(view=view_set, rocks=rock_instances, fields=fields,
                     player=player_iid)
    import engine.rocks.minors as m
    orig = m.reconcile_with
    m.reconcile_with = fake_with
    try:
        m.reconcile(_Sess(), _Rec())
    finally:
        m.reconcile_with = orig
    assert calls["player"] == 9 and calls["rocks"] == {}


def test_a_changed_spec_is_removed_and_re_added():
    """No dial hook involved: the rock GREW, so its halo's numbers changed."""
    r = _Rec()
    rock = _Rock("A", r=4.0)
    minors.reconcile_with(r, None, {rock: 1}, [], None)
    (old,) = minors.native_ids().values()
    rock._r = 5.0
    minors.reconcile_with(r, None, {rock: 1}, [], None)
    (new,) = minors.native_ids().values()
    assert ("minors_remove_cloud", old) in r.calls and new != old
    assert r.named("minors_add_cloud")[-1][1]["count"] == 200    # 8 x 25


def test_drain_frame_with_the_dying_rock_still_listed_detaches_not_removes(
        monkeypatch):
    """Task 10's contract: the free spec is registered only once
    death.is_dying_rock(rock) is true, so on the drain frame the rock is
    still realised (in rock_instances) but dying -- its halo must be
    detached into the free cloud, never removed and never re-added."""
    r = _Rec()
    rock = _Rock("Rock 4")
    minors.reconcile_with(r, None, {rock: 1}, [], None)
    hid = minors.native_ids()["halo::Rock 4"]
    monkeypatch.setattr(minors, "_is_dying", lambda rk: rk is rock)
    minors.register_free_cloud(_free("Rock 4"))
    minors.reconcile_with(r, None, {rock: 1}, [], None)
    ids = minors.native_ids()
    assert not any(k.startswith("halo:") for k in ids)
    assert ids == {"free::Rock 4": hid}
    assert [c[1] for c in r.named("minors_detach")] == [hid]
    assert r.named("minors_remove_cloud") == []
    assert len(r.named("minors_add_cloud")) == 1


def test_halo_keys_are_set_qualified_and_the_drain_matches_by_set():
    from engine.appc.sets import SetClass

    class _SetRock(_Rock):
        def __init__(self, name, pSet):
            super().__init__(name)
            self._set = pSet
        def GetContainingSet(self): return self._set

    a, b = SetClass(), SetClass()
    a.SetName("A"); b.SetName("B")
    ra, rb = _SetRock("Twin", a), _SetRock("Twin", b)
    assert minors.halo_spec(ra, 1).key == "halo:A:Twin"
    assert minors.halo_spec(rb, 2).key == "halo:B:Twin"
    r = _Rec()
    minors.reconcile_with(r, a, {ra: 1}, [], None)
    hid = minors.native_ids()["halo:A:Twin"]
    minors.register_free_cloud(_free("Twin", pSet=b))   # the OTHER set's twin
    minors.reconcile_with(r, a, {ra: 1}, [], None)
    assert r.named("minors_detach") == []
    assert minors.native_ids()["halo:A:Twin"] == hid
    minors.register_free_cloud(_free("Twin", pSet=a))
    minors.reconcile_with(r, a, {}, [], None)
    assert minors.native_ids()["free:A:Twin"] == hid


# ── Final review #1: a view change or a hidden player never sweeps ────────────

def test_a_view_change_resets_the_sweep_before_setting_the_player():
    """BC's set-to-set warp lands a few hundred GU from where the ship left,
    far under the teleport guard: a view change must drop the sweep origin
    (set_player(None)) before the player is pushed again, or the arrival
    frame's step sweeps departure -> arrival through the new set's clouds."""
    from engine.appc.sets import SetClass
    a, b = SetClass(), SetClass()
    a.SetName("A"); b.SetName("B")
    r = _Rec()
    minors.reconcile_with(r, a, {}, [], player_iid=42)
    minors.reconcile_with(r, a, {}, [], player_iid=42)
    minors.reconcile_with(r, b, {}, [], player_iid=42)
    assert r.named("minors_set_player") == [
        ("minors_set_player", None), ("minors_set_player", 42),   # first view
        ("minors_set_player", 42),                                # same view
        ("minors_set_player", None), ("minors_set_player", 42),   # new view
    ]


def test_a_scope_hidden_player_has_no_contact_box():
    """A cutscene showing another frame keeps the player's instance but
    scope-hides it: no phantom hull box may sweep the cutscene set."""
    calls = {}

    class _Sess:
        player = "P"
        ship_instances = {"P": 9}
        scope_hidden = {9}

    def fake_with(r, view_set, rock_instances, fields, player_iid):
        calls.update(player=player_iid)
    import engine.rocks.minors as m
    orig = m.reconcile_with
    m.reconcile_with = fake_with
    try:
        m.reconcile(_Sess(), _Rec())
    finally:
        m.reconcile_with = orig
    assert calls["player"] is None


def test_a_free_cloud_carries_the_halos_seed_and_orbit_rate():
    """Final review #2: native freezes a Free cloud's orbit at t0, so a
    re-sent free cloud rebuilds the detached halo exactly only if it carries
    the halo's own seed AND orbit rate (0.0 would pose every minor at angle 0)."""
    md._dials["halo_orbit_rate"] = 0.25
    r = _Rec()
    minors.register_free_cloud(_free("Rock 1"))
    minors.reconcile_with(r, None, {}, [], None)
    desc = r.named("minors_add_cloud")[0][1]
    halo = minors.halo_spec(_Rock("Rock 1"), iid=1)
    assert desc["anchor"] == "free"
    assert desc["seed"] == halo.seed
    assert desc["orbit_rate"] == halo.orbit_rate == 0.25
