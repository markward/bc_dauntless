"""Quick Battle late groups (warp-in spec §6.5/§6.6), headless against the
real SDK QuickBattle: a delayed group is absent at the start, pre-counted for
the win, and warps in on its game-time delay through BC's own warp-in
routine (`loadspacehelper.CreateShip(..., placement, 1)`).

Time is advanced two ways. Before an arrival only the timer manager is
jumped: no AI or combat runs, so a now-group cannot kill the player while the
test waits a whole minute. From the arrival on, the real GameLoop runs, which
is what drives the 2 s warp-in slide."""
import math
import random

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_qb_spawn import _start, qb  # noqa: E402,F401  (fixture)


def _plan(groups):
    """groups: (allegiance, direction, distance, difficulty, [ship ids], warp_in_min)."""
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.delete_group(s.groups[1].id)
    for alleg, d, dist, diff, ships, warp_in in groups:
        g = s.add_group()
        assert s.update_details(g.id, alleg, d, dist, diff, warp_in_min=warp_in)
        for ship in ships:
            s.add_ship(g.id, ship)
    return sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))


def _now():
    import App
    return App.g_kUtopiaModule.GetGameTime()


def _jump_to(t):
    """Timers only: no AI, motion or combat."""
    import App
    dt = t - App.g_kTimerManager.get_time()
    if dt > 0:
        App.g_kTimerManager.tick(dt)


def _sim_until(pred, bound_s=5.0):
    from engine.core.loop import TICK_DELTA, GameLoop
    loop = GameLoop()
    for _ in range(int(round(bound_s / TICK_DELTA))):
        if pred():
            return
        loop.tick()
    assert pred(), "condition not met within %.1f s" % bound_s


def _ships(QB):
    import App
    return {s.GetName(): s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)
            if s.GetName() != "Player"}


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _destroy(QB, ship):
    import App
    evt = App.TGEvent_Create()
    evt.SetDestination(ship)
    QB.ShipDestroyed(None, evt)


def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _our_timers():
    import App
    from engine.quickbattle import late_arrivals
    return [t for t in App.g_kTimerManager._timers.values()
            if t.GetEvent() is not None
            and t.GetEvent().GetEventType() == late_arrivals._ET]


def _landed(names, QB):
    from engine.appc import warp_state

    def pred():
        ships = _ships(QB)
        return all(n in ships and not warp_state.is_arriving(ships[n]) for n in names)
    return pred


_ENEMY_A = ("enemy", "fore", "standard", "medium", ["Warbird"], 0)
_ENEMY_B = ("enemy", "aft", "standard", "high", ["Galor", "Keldon"], 1)


def test_no_delay_spawn_unchanged(qb):
    """A plan with no delays: the now path, exactly as test_qb_spawn pins it
    -- names, anchor positions, g_kShips -- and nothing scheduled."""
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, placement, spawn
    plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird", "Galor"], 0)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    ships = _ships(QB)
    assert sorted(ships) == ["Galor-2", "Warbird-1"]
    p = _player()
    pp = (p.GetWorldLocation().x, p.GetWorldLocation().y, p.GetWorldLocation().z)
    cols = spawn._cols(p.GetWorldRotation())
    radii = [ships[n].GetRadius() for n in ("Warbird-1", "Galor-2")]
    anchor, slot = placement.group_positions(pp, cols, "fore",
                                             plan.orders[0].distance_gu, radii)
    w = ships["Warbird-1"].GetWorldLocation()
    assert (w.x, w.y, w.z) == pytest.approx(anchor, abs=1e-6)
    # Slot 1 sits EXACTLY r0 + r1 + MARGIN_GU from slot 0, which is also the
    # overlap test's boundary, so float rounding (the player's start point
    # varies) may nudge it one step further along starboard. Either is the
    # now path's own answer.
    step = 2.0 * radii[1] + placement.MARGIN_GU
    g = ships["Galor-2"].GetWorldLocation()
    off = tuple(c - a for c, a in zip((g.x, g.y, g.z), slot))
    k = sum(o * c for o, c in zip(off, cols[0])) / step
    assert off == pytest.approx(tuple(k * step * c for c in cols[0]), abs=1e-6)
    assert min(abs(k), abs(k - 1.0)) < 1e-6
    assert sorted(QB.g_kShips) == sorted(s.GetObjID() for s in ships.values())
    assert all(v[2] == "Enemy" for v in QB.g_kShips.values())
    assert QB.g_iNumEnemies == 2 and QB.bWonOrLost == 0
    assert late_arrivals.pending_enemy_count() == 0
    assert _our_timers() == []


def test_late_group_absent_then_arrives(qb):
    hl, controller, QB = qb
    import App
    from engine.appc import warp_in_flash
    from engine.quickbattle import spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert sorted(_ships(QB)) == ["Warbird-1"]
    assert QB.g_iNumEnemies == 3 and QB.bWonOrLost == 0
    # The model-warm probe never joins a set: nothing but the battle is in it.
    from engine.appc.ship_iter import iter_ships
    assert sorted(s.GetName() for s in iter_ships()) == ["Player", "Warbird-1"]

    _jump_to(t0 + 59.0)
    assert sorted(_ships(QB)) == ["Warbird-1"]
    p = _player()
    p_at_60 = p.GetWorldLocation()
    flashes = warp_in_flash.spawned_count()
    _jump_to(t0 + 61.0)
    ships = _ships(QB)
    assert sorted(ships) == ["Galor-2", "Keldon-3", "Warbird-1"]
    assert warp_in_flash.spawned_count() == flashes + 2
    for name in ("Galor-2", "Keldon-3"):
        s = ships[name]
        assert s.GetObjID() in QB.g_kShips
        assert QB.g_kShips[s.GetObjID()][2:] == ("Enemy", 1.0)
        assert s.GetAI() is not None, name
        assert QB.pEnemies.IsNameInGroup(name)
    assert QB.g_iNumEnemies == 3                     # counted once, at the start

    _sim_until(_landed(["Galor-2", "Keldon-3"], QB))
    for name in ("Galor-2", "Keldon-3"):
        d = _dist(_ships(QB)[name].GetWorldLocation(), p_at_60)
        assert d == pytest.approx(plan.orders[1].distance_gu, abs=1.0), name


def test_killing_first_group_does_not_win(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert QB.g_iNumEnemies == 2 and QB.bWonOrLost == 0
    _jump_to(t0 + 61.0)
    ships = _ships(QB)
    _destroy(QB, ships["Galor-2"])
    assert QB.bWonOrLost == 0
    _destroy(QB, ships["Keldon-3"])
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1


def test_all_groups_late_battle_arms_and_waits(qb):
    """Review Focus 1: nothing present at the start. The battle must arm
    (bWonOrLost 0), must not be won instantly, and must spawn later."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    plan = _plan([_ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert QB.bInSimulation == 1
    assert _ships(QB) == {}
    assert QB.g_iNumEnemies == 2 and QB.bWonOrLost == 0
    _jump_to(t0 + 61.0)
    ships = _ships(QB)
    assert sorted(ships) == ["Galor-1", "Keldon-2"]
    assert QB.bWonOrLost == 0
    _destroy(QB, ships["Galor-1"])
    _destroy(QB, ships["Keldon-2"])
    assert QB.bWonOrLost == 1


def _restart(hl, QB):
    import App
    QB.RestartSimulation(QB.g_pXO, App.TGEvent_Create())
    hl._process_object_deletions()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()


def test_restart_before_arrival_spawns_only_new_battle(qb):
    """Review Focus 2: the old battle's timer never spawns into the new
    battle; the new battle's own arrival still fires on its delay."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    _jump_to(t0 + 30.0)
    _restart(hl, QB)
    t1 = _now()
    assert QB.bInSimulation == 1 and QB.g_iNumEnemies == 3
    assert len(_our_timers()) == 1
    _jump_to(t0 + 61.0)                              # the OLD battle's arrival time
    assert sorted(_ships(QB)) == ["Warbird-1"]
    _jump_to(t1 + 59.0)
    assert sorted(_ships(QB)) == ["Warbird-1"]
    _jump_to(t1 + 61.0)
    assert sorted(_ships(QB)) == ["Galor-2", "Keldon-3", "Warbird-1"]
    assert QB.g_iNumEnemies == 3


def test_end_simulation_cancels_pending(qb):
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert len(_our_timers()) == 1
    assert late_arrivals.pending_enemy_count() == 2
    QB.EndSimulation()
    hl._process_object_deletions()
    assert _our_timers() == []
    assert late_arrivals.pending_enemy_count() == 0
    _jump_to(t0 + 61.0)
    assert _ships(QB) == {}


def test_install_end_simulation_hook_is_idempotent(qb):
    _hl, _c, QB = qb
    from engine.quickbattle import spawn
    spawn.install_end_simulation_hook(QB)
    first = QB.EndSimulation
    assert not spawn.install_end_simulation_hook(QB)
    assert QB.EndSimulation is first


def test_failed_late_spawn_is_uncounted(qb, monkeypatch):
    hl, controller, QB = qb
    import loadspacehelper
    from engine.quickbattle import spawn
    real = loadspacehelper.CreateShip

    def broken(ship_file, pSet, *a, **k):
        if ship_file == "Galor" and pSet is not None:
            return None                              # the arrival, not the probe
        return real(ship_file, pSet, *a, **k)

    monkeypatch.setattr(loadspacehelper, "CreateShip", broken)
    plan = _plan([_ENEMY_A, ("enemy", "aft", "standard", "high", ["Galor"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert QB.g_iNumEnemies == 2
    _jump_to(t0 + 61.0)
    assert sorted(_ships(QB)) == ["Warbird-1"]
    assert QB.g_iNumEnemies == 1 and QB.bWonOrLost == 0
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert QB.bWonOrLost == 1


def test_failed_last_enemy_arrival_wins_the_battle(qb, monkeypatch):
    """Every live enemy already dead and the only reinforcement fails to
    spawn: un-counting it reaches 0, so the win path runs at the arrival."""
    hl, controller, QB = qb
    import loadspacehelper
    from engine.quickbattle import spawn
    real = loadspacehelper.CreateShip

    def broken(ship_file, pSet, *a, **k):
        if ship_file == "Galor" and pSet is not None:
            return None
        return real(ship_file, pSet, *a, **k)

    monkeypatch.setattr(loadspacehelper, "CreateShip", broken)
    plan = _plan([_ENEMY_A, ("enemy", "aft", "standard", "high", ["Galor"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert QB.bWonOrLost == 0
    _jump_to(t0 + 61.0)
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1


def _arrival_faces(hl, controller, QB, seed):
    """Which of the player's six faces each late ship arrived on. The face,
    not the exact spot: a ship packed exactly r + r + MARGIN_GU from its
    neighbour sits on the overlap test's boundary, so float rounding (the
    player's start point varies run to run) may nudge it one step."""
    from engine.quickbattle import late_arrivals
    late_arrivals.set_rng(random.Random(seed))
    _start(hl, controller)
    t0 = _now()
    _jump_to(t0 + 61.0)
    p = _player()
    pl, rot = p.GetWorldLocation(), p.GetWorldRotation()
    out = {}
    for name in ("Galor-2", "Keldon-3"):
        w = _ships(QB)[name].GetWorldLocation()
        off = (w.x - pl.x, w.y - pl.y, w.z - pl.z)
        dots = []
        for i in range(3):
            c = rot.GetCol(i)
            dots.append(off[0] * c.x + off[1] * c.y + off[2] * c.z)
        i = max(range(3), key=lambda j: abs(dots[j]))
        out[name] = (i, dots[i] > 0)
    QB.EndSimulation()
    hl._process_object_deletions()
    return out


def test_random_direction_is_seeded(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    first = _arrival_faces(hl, controller, QB, 1)
    assert first == _arrival_faces(hl, controller, QB, 1)
    assert first["Galor-2"] == first["Keldon-3"]          # one face per group
    # ...and the face really comes from the RNG, not a fixed direction.
    faces = {_arrival_faces(hl, controller, QB, seed)["Galor-2"] for seed in range(2, 8)}
    assert len(faces | {first["Galor-2"]}) > 1


@pytest.mark.parametrize("kill_first", [False, True])
def test_callout_gets_the_arrival_counts(qb, monkeypatch, kill_first):
    """One callout per arrival tick, after every group of that tick is in:
    two late groups sharing a delay (2 enemies + 1 friendly) give ONE call.
    `enemies_already` is whether any enemy was live before the arrival."""
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, spawn
    calls = []
    monkeypatch.setattr(late_arrivals, "callout",
                        lambda qb_, arrived, already: calls.append((qb_, arrived, already)))
    plan = _plan([_ENEMY_A, _ENEMY_B,
                  ("friendly", "port", "close", "medium", ["Akira"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    if kill_first:
        _destroy(QB, _ships(QB)["Warbird-1"])
    _jump_to(t0 + 61.0)
    assert calls == [(QB, {"enemy": 2, "other": 1}, not kill_first)]


def test_probe_warms_each_late_model_outside_every_set(qb):
    """Spec §6.6: at the start each late ship's model is warmed through the
    radius seeder (which loads and caches it) on a probe that is in NO set,
    and that radius spaces the group when it arrives."""
    hl, controller, QB = qb
    from engine.quickbattle import placement, spawn
    seeded = []

    def seeder(ship):
        seeded.append((str(ship.GetScript()), ship.GetContainingSet()))
        if ship.GetRadius() <= 0.0:
            ship.SetRadius(5.0)

    spawn.set_radius_fn(seeder)
    plan = _plan([_ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    probes = [(script, s) for script, s in seeded if s is None]
    assert sorted(script.rsplit(".", 1)[-1] for script, _s in probes) == ["Galor", "Keldon"]
    _jump_to(t0 + 61.0)
    ships = _ships(QB)
    d = _dist(ships["Galor-1"].GetWorldLocation(), ships["Keldon-2"].GetWorldLocation())
    assert d >= 5.0 + 5.0 + placement.MARGIN_GU - 1e-6


# ── fix round 1: no failure path may leave a pre-counted ship counted ──────

_ENEMY_C = ("enemy", "port", "standard", "medium", ["Ambassador"], 1)


def test_group_setup_failure_uncounts_that_group_and_others_still_arrive(qb, monkeypatch):
    """A group whose setup raises (here group_positions) before its per-ship
    loop is un-counted; a later group in the same tick still arrives, and the
    tick's callout and win check still run."""
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, placement, spawn
    plan = _plan([_ENEMY_A, _ENEMY_B, _ENEMY_C])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert QB.g_iNumEnemies == 4
    real = placement.group_positions
    calls = []

    def first_raises(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("placement exploded")
        return real(*a, **k)

    monkeypatch.setattr(placement, "group_positions", first_raises)
    callouts = []
    monkeypatch.setattr(late_arrivals, "callout",
                        lambda qb_, arrived, already: callouts.append(arrived))
    _jump_to(t0 + 61.0)
    assert sorted(_ships(QB)) == ["Ambassador-4", "Warbird-1"]
    assert QB.g_iNumEnemies == 2
    assert callouts == [{"enemy": 1, "other": 0}]
    ships = _ships(QB)
    _destroy(QB, ships["Warbird-1"])
    assert QB.bWonOrLost == 0
    _destroy(QB, ships["Ambassador-4"])
    assert QB.bWonOrLost == 1


def test_whole_tick_setup_failure_still_wins(qb, monkeypatch):
    """Every group of the tick fails in setup and no live enemy is left: the
    win check still runs for the tick."""
    hl, controller, QB = qb
    from engine.quickbattle import placement, spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    _destroy(QB, _ships(QB)["Warbird-1"])

    def boom(*_a, **_k):
        raise RuntimeError("placement exploded")

    monkeypatch.setattr(placement, "group_positions", boom)
    _jump_to(t0 + 61.0)
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1


def test_schedule_failure_leaves_late_ships_uncounted(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, spawn
    real = late_arrivals.schedule

    def half_then_raise(qb_, late, radii):
        real(qb_, late, radii)                       # timers created...
        raise RuntimeError("schedule exploded")      # ...then it fails

    monkeypatch.setattr(late_arrivals, "schedule", half_then_raise)
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    assert QB.g_iNumEnemies == 1
    assert _our_timers() == [] and late_arrivals.pending_enemy_count() == 0
    _jump_to(t0 + 61.0)
    assert sorted(_ships(QB)) == ["Warbird-1"]
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert QB.bWonOrLost == 1


def test_member_without_a_position_is_uncounted(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import placement, spawn
    plan = _plan([_ENEMY_A, _ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    real = placement.group_positions
    monkeypatch.setattr(placement, "group_positions",
                        lambda *a, **k: real(*a, **k)[:1])
    _jump_to(t0 + 61.0)
    ships = _ships(QB)
    assert sorted(ships) == ["Galor-2", "Warbird-1"]
    assert QB.g_iNumEnemies == 2
    _destroy(QB, ships["Warbird-1"])
    _destroy(QB, ships["Galor-2"])
    assert QB.bWonOrLost == 1


def test_details_failure_still_records_the_arrived_ship(qb, monkeypatch):
    """A ship that exists stays counted: if the AI/message lookup raises, the
    g_kShips row still goes in (BC's fallback AI), so its death un-counts it."""
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    plan = _plan([("enemy", "aft", "standard", "high", ["Galor"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()

    def boom(*_a, **_k):
        raise RuntimeError("details table broken")

    monkeypatch.setattr(spawn, "_details", boom)
    _jump_to(t0 + 61.0)
    galor = _ships(QB)["Galor-1"]
    assert QB.g_kShips[galor.GetObjID()][0] == spawn._FALLBACK["Enemy"][0]
    _destroy(QB, galor)
    assert QB.bWonOrLost == 1


def test_reset_drops_the_event_type_and_the_next_schedule_allocates_afresh(qb):
    """App._next_event_type_id restarts at 1200 on every mission swap, so a
    cached type could collide with an SDK one: reset() forgets it, and the
    next battle allocates a new one (and registers it on the XO) at schedule
    time -- and that battle's arrival still fires."""
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals, spawn
    plan = _plan([_ENEMY_B])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    first = late_arrivals._ET
    assert first is not None
    QB.EndSimulation()
    hl._process_object_deletions()
    late_arrivals.reset()
    assert late_arrivals._ET is None
    _start(hl, controller)
    t1 = _now()
    assert late_arrivals._ET is not None and late_arrivals._ET != first
    _jump_to(t1 + 61.0)
    assert sorted(_ships(QB)) == ["Galor-1", "Keldon-2"]


def test_mission_swap_resets_late_arrivals():
    import engine.host_loop as hl
    from engine.quickbattle import late_arrivals
    late_arrivals._ET = 4321
    late_arrivals._qb = object()

    class _StubLoader:
        def load(self, name):
            return None

    hc = hl.HostController()
    hc.loader = _StubLoader()
    hc.pending_swap = "SomeMission"
    hc._drain_pending_swap()
    assert late_arrivals._ET is None and late_arrivals._qb is None


def _spoken(monkeypatch):
    import App
    said = []
    real = App.CharacterAction_Create

    def fake(char, kind, key="", *rest):
        said.append((char, key, rest))
        return real(char, kind, key, *rest)
    monkeypatch.setattr(App, "CharacterAction_Create", fake)
    return said


def _late_enemies(qb, monkeypatch, n, kill_now):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    said = _spoken(monkeypatch)
    ships = ["Galor", "Keldon", "Warbird"][:n]
    plan = _plan([_ENEMY_A, ("enemy", "aft", "standard", "high", ships, 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    t0 = _now()
    if kill_now:
        _destroy(QB, _ships(QB)["Warbird-1"])
    _jump_to(t0 + 61.0)
    return QB, said


def test_late_enemies_into_quiet_battle_say_count_line(qb, monkeypatch):
    QB, said = _late_enemies(qb, monkeypatch, 2, True)
    lines = [(c, k) for c, k, _ in said if k.startswith("Incoming")]
    assert lines == [(QB.g_pTact, "Incoming2")]


def test_late_enemies_while_fighting_say_incoming6(qb, monkeypatch):
    QB, said = _late_enemies(qb, monkeypatch, 2, False)
    lines = [(c, k) for c, k, _ in said if k.startswith("Incoming")]
    assert lines == [(QB.g_pTact, "Incoming6")]


def test_late_friendly_says_gs025_by_science(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    said = _spoken(monkeypatch)
    plan = _plan([_ENEMY_A, ("friendly", "port", "close", "medium", ["Akira"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    _jump_to(_now() + 61.0)
    lines = [(c, k) for c, k, _ in said if k.startswith("gs025") or k.startswith("Incoming")]
    assert lines == [(QB.g_pSci, "gs025")]


def test_mixed_arrival_one_line_per_side(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    said = _spoken(monkeypatch)
    plan = _plan([_ENEMY_A, ("enemy", "aft", "standard", "high", ["Galor"], 1),
                  ("friendly", "port", "close", "medium", ["Akira", "Akira"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    _jump_to(_now() + 61.0)
    lines = [(c, k) for c, k, _ in said if k.startswith("gs025") or k.startswith("Incoming")]
    assert lines == [(QB.g_pTact, "Incoming6"), (QB.g_pSci, "gs025")]


def test_missing_character_skips_quietly(qb, monkeypatch, caplog):
    hl, controller, QB = qb
    from engine.quickbattle import late_arrivals
    late_arrivals._callout_warned.clear()
    from engine.quickbattle import spawn
    said = _spoken(monkeypatch)
    plan = _plan([_ENEMY_A, ("enemy", "aft", "standard", "high", ["Galor"], 1)])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    monkeypatch.setattr(QB, "g_pTact", None)
    _jump_to(_now() + 61.0)
    assert "Galor-2" in _ships(QB)
    assert not [1 for _, k, _ in said if k.startswith("Incoming")]
    assert "no g_pTact" in caplog.text
