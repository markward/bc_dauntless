import App
import pytest
from engine.appc.math import TGPoint3
from tests.unit.test_rock_class import _make


@pytest.fixture(autouse=True)
def _fresh_sets():
    """conftest deliberately keeps g_kSetManager's sets across tests, so drop
    this file's scratch sets: a piece "Asteroid 5b-1" left by one test would
    otherwise answer GetObject in the next."""
    yield
    for name in ("RockTest", "Ship"):
        if App.g_kSetManager.GetSet(name) is not None:
            App.g_kSetManager.DeleteSet(name)


def _in_set(obj, name, set_name="RockTest"):
    pSet = App.g_kSetManager.GetSet(set_name) or App.SetClass_Create()
    if App.g_kSetManager.GetSet(set_name) is None:
        App.g_kSetManager.AddSet(pSet, set_name)
    pSet.AddObjectToSet(obj, name)
    return pSet


def _events(monkeypatch):
    seen = []
    real = App.g_kEventManager.AddEvent
    def spy(evt):
        seen.append(evt.GetEventType())
        return real(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return seen


def test_hull_zero_routes_to_rock_death_not_ship_death(monkeypatch):
    from engine.appc import ship_death
    from engine.rocks import death
    called = []
    monkeypatch.setattr(ship_death, "begin", lambda *a, **k: called.append(a))
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    rock.DamageSystem(rock.GetHull(), 1e9)
    assert called == []
    assert death.is_dying_rock(rock)


def test_destroy_system_routes_to_rock_death(monkeypatch):
    from engine.appc import ship_death
    from engine.rocks import death
    called = []
    monkeypatch.setattr(ship_death, "begin", lambda *a, **k: called.append(a))
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    rock.DestroySystem(rock.GetHull())
    assert called == []
    assert death.is_dying_rock(rock)


def test_ship_hull_zero_still_uses_ship_death(monkeypatch):
    from engine.appc import ship_death
    called = []
    monkeypatch.setattr(ship_death, "begin", lambda *a, **k: called.append(a))
    ship = _make(App.GENUS_SHIP)
    _in_set(ship, "Ship")
    ship.DamageSystem(ship.GetHull(), 1e9)
    assert len(called) == 1


def test_event_order_and_lifetime(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    assert seen.count(App.ET_OBJECT_EXPLODING) == 1
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(0.49)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(0.02)
    assert seen.count(App.ET_OBJECT_DESTROYED) == 1
    assert pSet.GetObject("Asteroid 5b") is None


def test_destroyed_fires_while_still_in_set_then_deleted(monkeypatch):
    """Mirrors ship_death.retire: ET_OBJECT_DESTROYED while the rock is still
    in its set, then set removal, then ET_DELETE_OBJECT_PUBLIC."""
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    pSet = _in_set(rock, "Asteroid 5b")
    log = []
    real = App.g_kEventManager.AddEvent
    def spy(evt):
        log.append((evt.GetEventType(), pSet.GetObject("Asteroid 5b") is not None))
        return real(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    death.begin(rock)
    death.advance(1.0)
    types = [t for t, _ in log]
    assert (App.ET_OBJECT_DESTROYED, True) in log
    assert (App.ET_DELETE_OBJECT_PUBLIC, False) in log
    assert types.index(App.ET_OBJECT_DESTROYED) < types.index(App.ET_DELETE_OBJECT_PUBLIC)
    assert rock.IsDead()


def test_death_script_lifetime_is_honoured(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    # Set INSIDE the death script (E1M2's pattern): pins that the lifetime is
    # read after the script has run.
    rock.RunDeathScript = lambda: rock.SetLifeTime(2.0)
    death.begin(rock)
    death.advance(1.0)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(1.01)
    assert App.ET_OBJECT_DESTROYED in seen


def test_death_script_runs_once():
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    runs = []
    rock.RunDeathScript = lambda: runs.append(1)
    death.begin(rock)
    death.begin(rock)        # idempotent
    assert runs == [1]


def test_big_rock_spawns_named_major_pieces_without_death_script():
    from engine.rocks import breakup, death
    from engine.rocks.rock import is_rock
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    rock.SetDeathScript("nowhere.Fn")
    rock.SetTargetable(1)
    pSet = _in_set(rock, "Asteroid 5b")
    rock.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    death.begin(rock)
    majors = [p for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "major"]
    assert majors
    for i in range(1, len(majors) + 1):
        piece = pSet.GetObject("Asteroid 5b-%d" % i)
        assert piece is not None and is_rock(piece)
        assert piece.GetDeathScript() is None
        assert piece._rock_generation == 1
        # Parent velocity carried: what remains is the separation kick alone
        # (identity rotation, so the kick is exactly offset * speed).
        v = piece.GetVelocityTG()
        off = majors[i - 1].offset
        sp = breakup.kSeparationSpeedGU
        assert abs(v.x - (1.0 + off[0] * sp)) < 1e-9
        assert abs(v.y - off[1] * sp) < 1e-9
        assert abs(v.z - off[2] * sp) < 1e-9
        # Targetable parent: only the large piece, at or above the threshold.
        big = piece.GetRadius() >= breakup.kTargetableMinRadiusGU
        assert bool(piece.IsTargetable()) is (big and majors[i - 1].rank == "large")


def test_piece_hull_scales_from_parent_max():
    from engine.rocks import breakup, death, stats
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    # Through the property, the way E1M2 CreateDebris sets an asteroid's HP:
    # HullSubsystem.GetMaxCondition reads the property template.
    rock.GetHull().GetProperty().SetMaxCondition(8000.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    majors = [p for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "major"]
    first = pSet.GetObject("Asteroid 5b-1")
    assert abs(first.GetHull().GetMaxCondition()
               - stats.piece_hull(8000.0, majors[0].v_ratio)) < 1e-6
    assert abs(first.GetMass()
               - stats.piece_mass(rock.GetMass(), majors[0].v_ratio)) < 1e-6


def test_chunks_and_vfx_are_queued():
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(1.6)                  # 1 major + 2 chunks (see _big_rock)
    _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    n_chunks = sum(1 for p in breakup.plan("Asteroid 5b", 1.6) if p.tier == "chunk")
    assert n_chunks and len(death.drain_chunk_specs()) == n_chunks
    assert death.drain_chunk_specs() == []
    assert len(death.drain_death_vfx()) == 1


def test_small_rock_queues_chunks_not_objects():
    """A stock-size rock (0.8 GU) makes no majors: every non-dust piece is a
    render-side chunk spec, and nothing new joins the set."""
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(0.8)                  # _make leaves the ship radius at 0
    pSet = _in_set(rock, "Asteroid 5b")
    before = len(list(pSet.GetClassObjectList(App.CT_SHIP))) \
        if hasattr(pSet, "GetClassObjectList") else None
    death.begin(rock)
    plan = breakup.plan("Asteroid 5b", 0.8)
    chunks = [p for p in plan if p.tier == "chunk"]
    specs = death.drain_chunk_specs()
    assert chunks and len(specs) == len(chunks)
    assert all(s.pSet is pSet for s in specs)
    assert pSet.GetObject("Asteroid 5b-1") is None
    if before is not None:
        assert len(list(pSet.GetClassObjectList(App.CT_SHIP))) == before


def test_rock_death_clears_target_locks(monkeypatch):
    from engine.appc import ship_death
    from engine.rocks import death
    cleared = []
    monkeypatch.setattr(ship_death, "_clear_target_locks", lambda s: cleared.append(s))
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    death.advance(1.0)
    assert rock in cleared


def test_reset_drops_pending_and_removed_rock_is_skipped(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pSet.RemoveObjectFromSet("Asteroid 5b")
    death.advance(1.0)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.begin(_make(App.GENUS_ASTEROID))
    death.reset()
    assert death.drain_chunk_specs() == []


def test_no_splash_from_or_to_rocks(monkeypatch):
    from engine.appc import combat, splash_damage
    hits = []
    monkeypatch.setattr(combat, "apply_hit", lambda target, *a, **k: hits.append(target))
    rock = _make(App.GENUS_ASTEROID)
    ship = _make(App.GENUS_SHIP)
    _in_set(rock, "Asteroid 5b")
    _in_set(ship, "Ship")
    rock.SetSplashDamage(1000.0, 50.0)
    splash_damage.apply(rock)
    assert hits == []                        # a rock splashes nothing
    ship.SetSplashDamage(1000.0, 50.0)
    splash_damage.apply(ship)
    assert rock not in hits                  # a ship's splash skips rocks


def test_game_loop_tick_advances_rock_death(monkeypatch):
    from engine.core.loop import GameLoop, TICK_DELTA
    from engine.rocks import death
    seen = []
    monkeypatch.setattr(death, "advance", lambda dt: seen.append(dt))
    GameLoop().tick()
    assert seen == [TICK_DELTA]


def _typed_events(monkeypatch, obj):
    """Event types whose source is `obj`, in dispatch order."""
    seen = []
    real = App.g_kEventManager.AddEvent
    def spy(evt):
        if evt.GetSource() is obj:
            seen.append(evt.GetEventType())
        return real(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return seen


def test_rock_killed_during_advance_is_still_retired(monkeypatch):
    """A DESTROYED handler that kills a second rock (retire dispatches
    synchronously inside advance) must not lose that rock's death entry."""
    from engine.rocks import death
    a = _make(App.GENUS_ASTEROID)
    b = _make(App.GENUS_ASTEROID)
    pSet = _in_set(a, "Asteroid 5b")
    _in_set(b, "Asteroid 6b")
    b_events = []
    real = App.g_kEventManager.AddEvent
    def spy(evt):
        if evt.GetSource() is b:
            b_events.append(evt.GetEventType())
        rv = real(evt)
        if evt.GetEventType() == App.ET_OBJECT_DESTROYED and evt.GetSource() is a:
            death.begin(b)                   # a handler kills another rock
        return rv
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    death.begin(a)
    death.advance(1.0)                       # a retires; b begins mid-advance
    assert death.is_dying_rock(b)
    death.advance(1.0)
    assert b_events.count(App.ET_OBJECT_DESTROYED) == 1
    assert pSet.GetObject("Asteroid 6b") is None
    assert not death.is_dying_rock(b)


def _pair_masked(x, y):
    from engine.appc.collisions import _collision_disabled_ids
    return (y.GetObjID() in _collision_disabled_ids(x)
            or x.GetObjID() in _collision_disabled_ids(y))


def _majors_of(pSet, name, radius):
    from engine.rocks import breakup
    n = sum(1 for p in breakup.plan(name, radius) if p.tier == "major")
    return [pSet.GetObject("%s-%d" % (name, i)) for i in range(1, n + 1)]


def _spread(objs, step=100.0):
    """Move every object far from every other (and from the origin, where the
    parent sits): headless nothing integrates the pieces apart."""
    for i, o in enumerate(objs):
        o.SetTranslateXYZ(step * (i + 1), 0.0, 0.0)


def test_parent_collisions_off_and_pieces_ghosted_while_overlapping():
    """Ghost until separated (tuned after live test 2026-10-01): pieces born
    overlapping stay masked as long as they overlap, well past the old fixed
    1 s window that let them grind each other afterwards."""
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    assert rock.CanCollide() == 0
    pieces = _majors_of(pSet, "Asteroid 5b", 4.0)
    assert len(pieces) >= 2
    for i, x in enumerate(pieces):
        assert _pair_masked(x, rock)
        for y in pieces[i + 1:]:
            assert _pair_masked(x, y)
    for _ in range(150):                          # 2.5 s, nothing moves
        death.advance(1.0 / 60.0)
    assert _pair_masked(pieces[0], pieces[1])     # still overlapping


def test_pieces_unmask_within_one_advance_of_separating():
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pieces = _majors_of(pSet, "Asteroid 5b", 4.0)
    death.advance(1.0 / 60.0)
    assert _pair_masked(pieces[0], pieces[1])
    _spread(pieces)
    death.advance(1.0 / 60.0)
    for i, x in enumerate(pieces):
        assert not _pair_masked(x, rock)
        for y in pieces[i + 1:]:
            assert not _pair_masked(x, y)


def test_separation_margin_is_beyond_the_contact_spheres():
    from engine.appc.collisions import contact_radius
    from engine.rocks import breakup, death
    assert breakup.kGhostSeparationMarginGU == 0.25
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    a, b = _majors_of(pSet, "Asteroid 5b", 4.0)[:2]
    _spread(_majors_of(pSet, "Asteroid 5b", 4.0))
    reach = contact_radius(a) + contact_radius(b)
    a.SetTranslateXYZ(500.0, 0.0, 0.0)
    b.SetTranslateXYZ(500.0 + reach + 0.2, 0.0, 0.0)
    death.advance(1.0 / 60.0)
    assert _pair_masked(a, b)                     # touching-ish: inside margin
    b.SetTranslateXYZ(500.0 + reach + 0.3, 0.0, 0.0)
    death.advance(1.0 / 60.0)
    assert not _pair_masked(a, b)


def test_ghost_cap_forces_unmask_while_still_overlapping():
    from engine.rocks import breakup, death
    assert breakup.kGhostMaxTime == 10.0
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pieces = _majors_of(pSet, "Asteroid 5b", 4.0)
    death.advance(breakup.kGhostMaxTime - 0.01)
    assert _pair_masked(pieces[0], pieces[1])
    death.advance(0.02)
    for i, x in enumerate(pieces):
        for y in pieces[i + 1:]:
            assert not _pair_masked(x, y)
    assert not death._ghosts


def test_unghost_is_safe_when_a_piece_is_gone():
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pieces = _majors_of(pSet, "Asteroid 5b", 4.0)
    pSet.DeleteObjectFromSet(pieces[0].GetName())
    death.advance(1.0 / 60.0)                     # must not raise
    assert not any(pieces[0] in (g["a"], g["b"]) for g in death._ghosts)
    _spread(pieces[1:])
    death.advance(1.0 / 60.0)
    assert not _pair_masked(pieces[1], pieces[2])





@pytest.mark.parametrize("lifetime_first", [True, False])
def test_script_lifetime_with_object_lifetime_ticking_fires_once(
        monkeypatch, lifetime_first):
    """E1M2's death script sets SetLifeTime(0.5), which also registers the
    rock with object_lifetime; with both ticking, each event fires once."""
    from engine.appc import object_lifetime
    from engine.core.loop import TICK_DELTA
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    rock.RunDeathScript = lambda: rock.SetLifeTime(0.5)
    seen = _typed_events(monkeypatch, rock)
    death.begin(rock)
    for _ in range(90):
        if lifetime_first:
            object_lifetime.advance(TICK_DELTA)
            death.advance(TICK_DELTA)
        else:
            death.advance(TICK_DELTA)
            object_lifetime.advance(TICK_DELTA)
    assert seen.count(App.ET_OBJECT_EXPLODING) == 1
    assert seen.count(App.ET_OBJECT_DESTROYED) == 1
    assert seen.count(App.ET_DELETE_OBJECT_PUBLIC) == 1


def test_effective_radius_falls_back_to_hull_radius_times_scale():
    """Headless, a hardpoint rock's GetRadius is 0 (HullProperty.SetRadius
    sets only the hull subsystem radius) and SetScale is ignored by
    GetRadius; breakup must size from base x GetScale()."""
    from engine.rocks.rock import effective_radius
    rock = _make(App.GENUS_ASTEROID)
    assert float(rock.GetRadius()) == 0.0
    rock.SetScale(5.0)
    assert abs(effective_radius(rock) - 4.0) < 1e-9


def test_effective_radius_uses_get_radius_when_set():
    from engine.rocks.rock import effective_radius
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(1.2)
    rock.SetScale(1.0)
    assert abs(effective_radius(rock) - 1.2) < 1e-9


def test_scaled_hardpoint_rock_breaks_up_at_effective_radius(monkeypatch):
    """E1M2's SetScale 3.7-8.5 rocks: GetRadius 0, hull 0.8, SetScale(5)
    plans at 4.0 GU, so at least one targetable major piece spawns."""
    from engine.rocks import breakup, death
    planned = []
    real_plan = breakup.plan
    monkeypatch.setattr(breakup, "plan",
                        lambda n, r, **k: planned.append(r) or real_plan(n, r, **k))
    rock = _make(App.GENUS_ASTEROID)
    rock.SetScale(5.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    assert planned and abs(planned[0] - 4.0) < 1e-9
    assert pSet.GetObject("Asteroid 5b-1") is not None
    assert abs(death.drain_death_vfx()[-1].radius_gu - 4.0) < 1e-9


# ── The killer (the body whose hit caused the death) ─────────────────────────
# A rock killed against Haven used to break into pieces born inside Haven and
# still moving inward: each piece's next contact was lethal too, and the
# breakup cascaded (87 rocks in 2 s). The killer joins the ghost set, and an
# immovable killer strips the inward part of every piece's velocity.


def _planet_at(x, pSet):
    from engine.appc.planet import Planet
    p = Planet(50.0)
    p.SetTranslateXYZ(x, 0.0, 0.0)
    pSet.AddObjectToSet(p, "Killer Planet")
    return p


def _big_rock(vx=5.0):
    """1.6 GU: "Asteroid 5b" then breaks into both majors AND chunks."""
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(1.6)
    pSet = _in_set(rock, "Asteroid 5b")
    rock.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return rock, pSet


def test_movable_killer_is_ghosted_against_pieces_and_chunks():
    from engine.rocks import breakup, death
    rock, pSet = _big_rock()
    ship = _make(App.GENUS_SHIP)
    _in_set(ship, "Ship", "RockTest")
    death.begin(rock, killer=ship)
    pieces = _majors_of(pSet, "Asteroid 5b", 1.6)
    assert pieces
    for p in pieces:
        assert _pair_masked(p, ship)
    specs = death.drain_chunk_specs()
    assert specs and all(ship in s.ghost_peers for s in specs)
    death.advance(1.0 / 60.0)
    for p in pieces:
        assert _pair_masked(p, ship)           # within the margin of the killer
    _spread(pieces)
    death.advance(1.0 / 60.0)
    for p in pieces:
        assert not _pair_masked(p, ship)


def test_movable_killer_leaves_piece_velocity_untouched():
    from engine.rocks import breakup, death
    rock, pSet = _big_rock()
    ship = _make(App.GENUS_SHIP)
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)     # dead ahead of the rock
    _in_set(ship, "Ship", "RockTest")
    death.begin(rock, killer=ship)
    majors = [p for p in breakup.plan("Asteroid 5b", 1.6) if p.tier == "major"]
    sp = breakup.kSeparationSpeedGU
    for i, piece in enumerate(_majors_of(pSet, "Asteroid 5b", 1.6)):
        v = piece.GetVelocityTG()
        assert abs(v.x - (5.0 + majors[i].offset[0] * sp)) < 1e-9


def test_planet_killer_is_ghosted_from_the_piece_side_only():
    """Planet is not a DamageableObject: EnableCollisionsWith on it would be a
    silent TGObject stub. The mask is read symmetrically, so the pieces'
    side alone exempts the pair."""
    from engine.rocks import breakup, death
    rock, pSet = _big_rock()
    planet = _planet_at(60.0, pSet)
    death.begin(rock, killer=planet)
    pieces = _majors_of(pSet, "Asteroid 5b", 1.6)
    for p in pieces:
        assert planet.GetObjID() in p._collision_disabled_ids
    assert "_collision_disabled_ids" not in planet.__dict__
    specs = death.drain_chunk_specs()
    assert specs and all(planet in s.ghost_peers for s in specs)
    death.advance(1.0 / 60.0)                 # 60 GU off: already clear
    for p in pieces:
        assert planet.GetObjID() not in p._collision_disabled_ids


def _inward(vel, at, centre):
    dx, dy, dz = centre[0] - at[0], centre[1] - at[1], centre[2] - at[2]
    n = (dx * dx + dy * dy + dz * dz) ** 0.5
    return (vel[0] * dx + vel[1] * dy + vel[2] * dz) / n


@pytest.mark.parametrize("kind", ["planet", "immobile_ship"])
def test_immovable_killer_strips_inward_velocity(kind):
    from engine.rocks import death
    rock, pSet = _big_rock(vx=5.0)           # flying straight at the killer
    if kind == "planet":
        killer = _planet_at(60.0, pSet)
    else:
        killer = _make(App.GENUS_SHIP)
        killer.SetStatic(1)
        killer.SetTranslateXYZ(60.0, 0.0, 0.0)
        _in_set(killer, "Ship", "RockTest")
        assert killer.IsImmobile()
    death.begin(rock, killer=killer)
    c = (60.0, 0.0, 0.0)
    pieces = _majors_of(pSet, "Asteroid 5b", 1.6)
    assert pieces
    for p in pieces:
        v, at = p.GetVelocityTG(), p.GetWorldLocation()
        assert _inward((v.x, v.y, v.z), (at.x, at.y, at.z), c) <= 1e-9
    specs = death.drain_chunk_specs()
    assert specs
    for s in specs:
        assert _inward(s.vel, s.loc, c) <= 1e-9


def test_immovable_killer_keeps_outward_velocity():
    """Only the component TOWARD the killer goes: a rock already moving away
    keeps its speed."""
    from engine.rocks import breakup, death
    rock, pSet = _big_rock(vx=-5.0)          # receding from the planet at +x
    planet = _planet_at(60.0, pSet)
    death.begin(rock, killer=planet)
    for p in _majors_of(pSet, "Asteroid 5b", 1.6):
        assert p.GetVelocityTG().x < -5.0 + breakup.kSeparationSpeedGU + 1e-9


def test_render_queues_are_bounded_and_keep_the_newest():
    """Headless nothing drains the chunk/VFX queues, so a long run of rock
    deaths must not grow them without bound: oldest dropped at the cap."""
    from engine.rocks import death
    cap = death.kMaxQueuedSpecs
    for i in range(cap + 40):
        rock = _make(App.GENUS_ASTEROID)
        rock.SetRadius(0.8)              # stock size: chunks, no majors
        _in_set(rock, "Q%d" % i)
        death.begin(rock)
    vfx = death.drain_death_vfx()
    chunks = death.drain_chunk_specs()
    assert len(vfx) == cap
    assert len(chunks) == cap
    assert chunks[-1].seed.startswith("Q%d#" % (cap + 39))   # newest kept


def test_a_set_less_dying_rock_is_logged_once(monkeypatch):
    """A rock that dies outside any set cannot break up (pieces need a set):
    say so once in dev mode rather than dropping it silently."""
    import engine.dev_mode as dm
    from engine.rocks import death
    logged = []
    monkeypatch.setattr(dm, "log_swallowed", lambda ctx, e: logged.append(ctx))
    for _ in range(3):
        death.begin(_make(App.GENUS_ASTEROID))
    assert logged.count("set-less dying rock: no breakup") == 1


def test_generation_one_rock_breaks_into_chunks_and_dust_only():
    """Tuned after live test 2026-10-01: no generation-2 rocks."""
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    rock._rock_generation = 1
    pSet = _in_set(rock, "Asteroid 5b-1")
    death.begin(rock)
    assert pSet.GetObject("Asteroid 5b-1-1") is None
    specs = death.drain_chunk_specs()
    assert 1 <= len(specs) <= breakup.kMaxChunksPerDeath


def test_generation_zero_rock_spawns_one_large_and_medium_majors():
    """Size-mix split: the large piece and every medium piece are majors,
    numbered 1..k in plan order; the small pieces are chunk specs."""
    from engine.rocks import breakup, death
    for name in ("Asteroid 5b", "Asteroid 6b", "Asteroid 7a"):
        rock = _make(App.GENUS_ASTEROID)
        rock.SetRadius(8.0)
        pSet = _in_set(rock, name)
        death.begin(rock)
        plan = breakup.plan(name, 8.0)
        majors = [p for p in plan if p.tier == "major"]
        assert [p.rank for p in majors] == \
            ["large"] + ["medium"] * (len(majors) - 1)
        for i in range(1, len(majors) + 1):
            assert pSet.GetObject("%s-%d" % (name, i)) is not None
        assert pSet.GetObject("%s-%d" % (name, len(majors) + 1)) is None
        specs = death.drain_chunk_specs()
        n_small = sum(1 for p in plan if p.rank == "small" and p.tier == "chunk")
        assert len(specs) == n_small <= breakup.kMaxChunksPerDeath


# ── Targetable rule (Mark, live tests 2026-10-01) ────────────────────────────
# Only the "large" piece may be targetable, and only when its BUILT radius is
# at least kTargetableMinRadiusGU; it then copies the parent's flag. Every
# other piece is untargetable; scannable/hailable always copy.


def _one_piece_death(monkeypatch, piece_radius, parent_targetable,
                     rank="large"):
    from engine.rocks import breakup, death
    spec = breakup.PieceSpec(radius_gu=piece_radius, offset=(1.0, 0.0, 0.0),
                             v_ratio=0.3, tier="major", rank=rank)
    monkeypatch.setattr(breakup, "plan", lambda *a, **k: [spec])
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(6.0)
    rock.SetTargetable(1 if parent_targetable else 0)
    rock.SetScannable(1)
    rock.SetHailable(1)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    return pSet.GetObject("Asteroid 5b-1")


def test_targetable_threshold_dial():
    from engine.rocks import breakup
    assert breakup.kTargetableMinRadiusGU == 2.0


def test_small_large_piece_is_not_targetable_but_copies_scan_and_hail(
        monkeypatch):
    piece = _one_piece_death(monkeypatch, 1.9, parent_targetable=True)
    assert not piece.IsTargetable()
    assert piece.IsScannable() and piece.IsHailable()
    assert piece.CanCollide()                     # still a solid rock


def test_large_piece_of_targetable_parent_is_targetable(monkeypatch):
    piece = _one_piece_death(monkeypatch, 3.0, parent_targetable=True)
    assert piece.IsTargetable()


def test_large_piece_of_untargetable_parent_is_not_targetable(monkeypatch):
    piece = _one_piece_death(monkeypatch, 3.0, parent_targetable=False)
    assert not piece.IsTargetable()


def test_large_piece_at_threshold_copies_parent(monkeypatch):
    from engine.rocks import breakup
    piece = _one_piece_death(monkeypatch, breakup.kTargetableMinRadiusGU,
                             parent_targetable=True)
    assert piece.IsTargetable()


def test_medium_piece_is_never_targetable_but_copies_scan_and_hail(
        monkeypatch):
    piece = _one_piece_death(monkeypatch, 4.0, parent_targetable=True,
                             rank="medium")
    assert not piece.IsTargetable()
    assert piece.IsScannable() and piece.IsHailable()


@pytest.mark.parametrize("planned, built, targetable",
                         [(1.96, 2.0, True), (1.94, 1.9, False)])
def test_threshold_reads_the_built_radius_not_the_planned_one(
        monkeypatch, planned, built, targetable):
    """RockClass_Create quantises to 2 s.f.: planned 1.96 is BUILT at 2.0 GU
    (targetable), planned 1.94 at 1.9 GU (not)."""
    piece = _one_piece_death(monkeypatch, planned, parent_targetable=True)
    assert piece.GetRadius() == built
    assert bool(piece.IsTargetable()) is targetable


def test_real_breakup_targets_only_the_large_piece():
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(8.0)
    rock.SetTargetable(1)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    majors = _majors_of(pSet, "Asteroid 5b", 8.0)
    assert len(majors) >= 4
    assert majors[0].GetRadius() >= breakup.kTargetableMinRadiusGU
    assert [bool(m.IsTargetable()) for m in majors] == \
        [True] + [False] * (len(majors) - 1)


def test_destroying_a_generation_one_remnant_creates_no_target():
    """The generation cap means a remnant breaks into chunks and dust only,
    so destroying the targetable large piece never spawns a new target."""
    from engine.appc.ship_iter import iter_rocks
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(8.0)
    rock.SetTargetable(1)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    large = pSet.GetObject("Asteroid 5b-1")
    assert large.IsTargetable() and large._rock_generation == 1
    before = {id(x) for x in iter_rocks()}
    death.begin(large)
    new = [x for x in iter_rocks() if id(x) not in before]
    assert new == []
    assert pSet.GetObject("Asteroid 5b-1-1") is None
    assert death.drain_chunk_specs()            # it still broke up, as chunks
