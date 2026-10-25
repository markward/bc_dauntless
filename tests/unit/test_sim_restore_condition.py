"""A ship's condition (subsystems, shields, ammunition) reads back and writes
back exactly: the Quick Battle restore puts a rebuilt object back into its
pre-battle condition through these two functions."""
import App


def _galaxy():
    import loadspacehelper
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "sim_restore_condition")
    return loadspacehelper.CreateShip("Galaxy", pSet, "G", "")


def test_apply_condition_puts_back_what_condition_of_read():
    from engine.appc.subsystems import iter_subsystems
    from engine.quickbattle.sim_restore import apply_condition, condition_of
    ship = _galaxy()
    before = condition_of(ship)
    subs = list(iter_subsystems(ship))
    assert subs[0] is ship.GetHull()
    assert len(before["subsystems"]) == len(subs) > 1
    assert len(before["shields"]) == 6
    assert before["ammo"]

    ship.GetHull().SetCondition(ship.GetHull().GetCondition() * 0.5)
    subs[1].SetCondition(subs[1].GetCondition() * 0.25)
    ship.GetShields().SetCurShields(0, 0.0)
    ship.GetTorpedoSystem().GetAmmoType(0).SetAvailable(0)
    assert condition_of(ship) != before

    apply_condition(ship, before)
    assert condition_of(ship) == before


def test_iter_subsystems_yields_hull_then_top_level_each_followed_by_children():
    from engine.appc.subsystems import iter_subsystems
    ship = _galaxy()
    subs = list(iter_subsystems(ship))
    phasers = ship.GetPhaserSystem()
    i = subs.index(phasers)
    n = phasers.GetNumChildSubsystems()
    assert n > 0
    assert subs[i + 1:i + 1 + n] == [phasers.GetChildSubsystem(k)
                                     for k in range(n)]


def test_iter_subsystems_of_none_is_empty():
    from engine.appc.subsystems import iter_subsystems
    assert list(iter_subsystems(None)) == []


def test_build_bypasses_the_reuse_wrapper():
    """R9: a rebuild must never get the old (scarred) station back from the
    CreateShip reuse wrapper, so _build calls BC's unwrapped CreateShip."""
    import loadspacehelper
    from engine.systems import home_stations as hs
    hs.install_create_ship_hook(loadspacehelper)
    calls = []
    wrapped = loadspacehelper.CreateShip
    orig = wrapped._dauntless_home_station_orig

    def spy(*a):
        calls.append(a)
        return orig(*a)

    wrapped._dauntless_home_station_orig = spy
    try:
        row = hs.table()[0]
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "sim_restore_build")
        hs._build(row, pSet, App.TGPoint3(), App.TGMatrix3())
    finally:
        wrapped._dauntless_home_station_orig = orig
    assert len(calls) == 1


def test_a_mission_swap_forgets_the_battle_snapshot():
    """A swap drops the running battle's snapshot, so a later EndSimulation
    never rebuilds an object of a mission that is gone (drives the REAL
    HostController._drain_pending_swap, test_minor_rocks_mission_swap's
    pattern)."""
    from engine.host_loop import HostController, MissionSession
    from engine.quickbattle import sim_restore

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

        def minors_clear(self):
            pass

    sim_restore._snapshot.append(object())
    sim_restore._pre_sim[1] = object()
    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    assert sim_restore._snapshot == []
    assert sim_restore._pre_sim == {}
