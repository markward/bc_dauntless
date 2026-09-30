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
        assert piece.IsTargetable()


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
    rock.SetRadius(4.0)
    _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    n_chunks = sum(1 for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "chunk")
    assert len(death.drain_chunk_specs()) == n_chunks
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


def test_parent_collisions_off_and_pieces_ghosted_then_unmasked():
    from engine.rocks import breakup, death
    assert breakup.kPieceGhostTime == 1.0
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
    death.advance(breakup.kPieceGhostTime - 0.01)
    assert _pair_masked(pieces[0], pieces[1])     # still ghosted
    death.advance(0.02)
    for i, x in enumerate(pieces):
        for y in pieces[i + 1:]:
            assert not _pair_masked(x, y)


def test_unghost_is_safe_when_a_piece_is_gone():
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pieces = _majors_of(pSet, "Asteroid 5b", 4.0)
    pSet.DeleteObjectFromSet(pieces[0].GetName())
    death.advance(breakup.kPieceGhostTime + 0.01)   # must not raise
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
