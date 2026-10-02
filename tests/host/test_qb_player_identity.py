"""Task 8 host wiring: boot installs the GenerateShips hook, the player keeps
the scenario's named ship through End Combat, and the old revert hook is gone.
Pattern: tests/host/test_qb_spawn.py."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def qb(monkeypatch):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import spawn
    yield hl, controller, QB
    spawn.set_provider(None)


def _scenario_with_player(ship, variant):
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.set_player_ship(ship)
    s.set_variant(s.player_entry().id, variant)
    s.add_ship(s.groups[1].id, "Warbird")
    return sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))


def _new_paths(reps):
    """`replacements_for` returns [(old_name, new_path), ...]."""
    return [new for _old, new in reps]


def test_boot_installs_generate_ships_hook(qb):
    _hl, _c, QB = qb
    assert getattr(QB.GenerateShips, "_dauntless_qb_spawn_orig", None) is not None


def test_end_combat_reverts_to_the_home_ship_but_keeps_the_setup(qb):
    """Mark's home-ship ruling, 2026-10-02: outside a battle the player is
    always the home ship (Galaxy USS Dauntless), even though the setup
    screen's scenario keeps naming the battle ship it was started with."""
    hl, controller, QB = qb
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert QB.g_sPlayerType == "Ambassador"
    QB.EndSimulation()                                   # End Combat
    player = App.Game_GetCurrentGame().GetPlayer()
    assert QB.g_sPlayerType == "Galaxy"                  # home ship, not the battle ship
    assert str(player.GetScript()).rsplit(".", 1)[-1] == "Galaxy"
    # Production path: the tick's runtime reconcile applies the identity to a
    # new, not-yet-realised QuickBattle player just before realising it.
    hl._reconcile_runtime_instances(hl.MissionSession(mission_name="QuickBattle"),
                                    controller.renderer)
    reps = registry_texture.replacements_for(player)
    assert all(old == registry_texture.REGISTRY_OLD_NAME for old, _new in reps)
    assert any(p.endswith("Dauntless.tga") for p in _new_paths(reps))
    assert not any(p.endswith("Excalibur.tga") for p in _new_paths(reps))
    assert player.GetDisplayName() == "USS Dauntless"
    # The setup screen's scenario / plan still name the Ambassador: it is
    # only the LIVE ship that reverted, not the panel's remembered battle.
    assert plan.player.ship_file == "Ambassador"


def test_xo_restart_puts_the_scenario_ship_back(qb):
    """RestartSimulation = EndSimulation() (home ship) then a re-post of
    ET_START_SIMULATION (battle ship again) -- the same preload dance as the
    first Start."""
    hl, controller, QB = qb
    import App
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert QB.g_sPlayerType == "Ambassador"
    evt = App.TGEvent_Create()
    evt.SetEventType(QB.ET_RESTART_SIMULATION)
    evt.SetDestination(QB.g_pXO)
    App.g_kEventManager.AddEvent(evt)
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert QB.g_sPlayerType == "Ambassador"
    player = App.Game_GetCurrentGame().GetPlayer()
    assert str(player.GetScript()).rsplit(".", 1)[-1] == "Ambassador"


def test_end_combat_after_a_renamed_galaxy_is_back_to_dauntless(qb):
    """A Galaxy named USS Venture in battle reverts to USS Dauntless after
    End Combat -- the class doesn't change, only the registry/name."""
    hl, controller, QB = qb
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Galaxy", "USS Venture")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    player = App.Game_GetCurrentGame().GetPlayer()
    hl._reconcile_runtime_instances(hl.MissionSession(mission_name="QuickBattle"),
                                    controller.renderer)
    assert player.GetDisplayName() == "USS Venture"
    QB.EndSimulation()                                   # End Combat
    assert QB.g_sPlayerType == "Galaxy"
    hl._reconcile_runtime_instances(hl.MissionSession(mission_name="QuickBattle"),
                                    controller.renderer)
    player = App.Game_GetCurrentGame().GetPlayer()
    reps = registry_texture.replacements_for(player)
    assert any(p.endswith("Dauntless.tga") for p in _new_paths(reps))
    assert player.GetDisplayName() == "USS Dauntless"


def test_death_outside_a_battle_recreates_the_home_ship(qb):
    """ShipDestroyed's player-death branch calls RecreatePlayer directly
    (not via the end-of-battle timer) only when bInSimulation is already 0
    -- the rule must apply there too."""
    hl, controller, QB = qb
    import App
    assert QB.bInSimulation == 0
    evt = App.TGEvent_Create()
    evt.SetDestination(App.Game_GetCurrentGame().GetPlayer())
    QB.ShipDestroyed(None, evt)
    assert QB.g_sPlayerType == "Galaxy"
    player = App.Game_GetCurrentGame().GetPlayer()
    assert str(player.GetScript()).rsplit(".", 1)[-1] == "Galaxy"


def test_no_provider_leaves_g_sPlayerType_untouched(monkeypatch):
    """With no provider registered at all, player_type_for_recreate must not
    write g_sPlayerType -- BC's own RecreatePlayer flow is unchanged. Marks
    g_sPlayerType with a value the home-ship rule would never itself choose
    (Sovereign, not Galaxy) so a silent "always Galaxy" bug would be caught,
    not accidentally match."""
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    from engine.quickbattle import spawn
    assert spawn._provider is None
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    assert spawn.player_type_for_recreate(QB) is None
    QB.g_sPlayerType = "Sovereign"
    QB.RecreatePlayer()
    assert QB.g_sPlayerType == "Sovereign"


def test_no_plan_falls_back_to_class_default(qb):
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    spawn.set_provider(None)
    player = App.Game_GetCurrentGame().GetPlayer()
    registry_texture.clear_for(player)
    spawn.apply_player_identity(player)
    reps = registry_texture.replacements_for(player)
    assert reps
    assert any(p.endswith("Dauntless.tga") for p in _new_paths(reps))


def test_revert_hook_is_gone():
    from engine import host_loop
    assert not hasattr(host_loop, "_sync_quickbattle_player_revert")


def test_battle_ships_and_player_have_radius_when_placement_runs(qb, monkeypatch):
    """GenerateShips runs before any realisation, so without the host's radius
    seeder every ship (and the just-recreated player) reports GetRadius() == 0
    and placement spacing collapses to MARGIN_GU. Boot must register a seeder
    that gives them their realisation radius first."""
    hl, controller, QB = qb
    import App
    from engine.quickbattle import spawn
    seen = []
    orig_place = spawn._place

    def _spy(qb_, ship, pos, lateral, placed):
        player = App.Game_GetCurrentGame().GetPlayer()
        seen.append((ship.GetName(), ship.GetRadius(), player.GetRadius()))
        return orig_place(qb_, ship, pos, lateral, placed)

    monkeypatch.setattr(spawn, "_place", _spy)
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert seen, "placement never ran"
    # Fake renderer's unit-box AABB -> the same radius realisation would seed.
    expected = hl._model_extent_from_aabb((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)) \
        * hl.BC_MODEL_SCALE
    for name, r, player_r in seen:
        assert r == pytest.approx(expected), name
        assert player_r == pytest.approx(expected), name


def test_radius_seeder_reuses_the_realisation_model_handle(qb, monkeypatch):
    """The seeder must load with exactly the args realize_set_objects will use
    (so the native load_model dedupes it), and populate the controller's
    extent cache so a second ship of the class does not load at all."""
    hl, controller, QB = qb
    import App
    calls = []
    r_ = controller.renderer
    orig = r_.load_model

    def _rec(path, search, reps=None, decals=None, **kw):
        calls.append((path, tuple(search), tuple(map(tuple, reps or ())),
                      repr(decals), tuple(kw.items())))
        return orig(path, search, reps, decals)

    monkeypatch.setattr(r_, "load_model", _rec)
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fresh.nif")
    controller.nif_to_extent.pop("fresh.nif", None)
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    seeded = list(calls)
    assert seeded, "seeder never loaded a model"
    assert "fresh.nif" in controller.nif_to_extent
    # Every seeder load is one realisation makes anyway (identical args ->
    # the native load_model dedupe returns the same handle): no wasted load.
    hl._reconcile_scene(hl.MissionSession(mission_name="QuickBattle"), r_)
    realised = calls[len(seeded):]
    assert realised
    assert set(seeded) <= set(realised)


def test_identity_falls_back_when_live_player_class_differs_from_plan(qb):
    """A live player whose class is not the plan's player ship (e.g. the boot
    Galaxy while the plan names an Ambassador) must not be stamped with the
    plan's registry or name: BC's class default applies instead."""
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    player = App.Game_GetCurrentGame().GetPlayer()
    assert registry_texture._class_of(player) == "Galaxy"
    registry_texture.clear_for(player)
    spawn.apply_player_identity(player)
    paths = _new_paths(registry_texture.replacements_for(player))
    assert any(p.endswith("Dauntless.tga") for p in paths)
    assert not any(p.endswith("Excalibur.tga") for p in paths)
    assert player.GetDisplayName() != "USS Excalibur"


def test_identity_uses_the_plan_it_is_given(qb):
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    spawn.set_provider(None)
    plan = _scenario_with_player("Galaxy", None)
    player = App.Game_GetCurrentGame().GetPlayer()
    registry_texture.clear_for(player)
    assert spawn.apply_player_identity(player, plan=plan)
    assert registry_texture.has_replacements(player)
