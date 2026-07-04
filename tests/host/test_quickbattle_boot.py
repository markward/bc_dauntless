"""Headless QuickBattle boot-entry integration test (Task 5).

When the host boots with no mission name it must run the REAL SDK QuickBattle
entry cascade (QuickBattleGame.Initialize -> QuickBattleEpisode.Initialize ->
QuickBattle.Initialize) instead of loading the single hardcoded ship-gate
mission. This test drives that cascade headlessly through _MissionLoader, using
the same fake-renderer harness the other host/realization tests use, and asserts
progressively that the cascade completes and the faithful start-simulation flow
fires.

The native _dauntless_host extension is required (the SDK Appc shim imports it
at module-load time); skip cleanly when it is not built.
"""
import pytest

pytest.importorskip("_dauntless_host")


class _FakeRenderer:
    """Minimal renderer surface the realization walk + reconciliation touch.

    Mirrors tests/unit/test_reconcile_runtime_ships.py::_FakeRenderer plus the
    handful of extra hooks _MissionLoader.load's realization walk calls.
    """

    def __init__(self):
        self._next = 1
        self.live = set()

    def load_model(self, path, search):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def _fresh_quickbattle_loader(monkeypatch):
    """Build a HostController + _MissionLoader wired to a fake renderer, with
    a fresh SDK environment. Forces ships to a fake NIF so realization never
    needs real assets."""
    from tools import mission_harness
    mission_harness.setup_sdk()

    from engine import host_loop as hl
    # Realization must not depend on real NIF files being on disk.
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    controller = hl.HostController()
    controller.renderer = _FakeRenderer()
    controller.loader = hl._MissionLoader(controller, verbose=False)
    return hl, controller


def test_quickbattle_cascade_completes_without_raising(monkeypatch):
    """load_quickbattle() runs the full Game->Episode->Mission cascade and
    returns a MissionSession without raising, building the QuickBattleRegion
    set, the XO character (g_pXO), and an initial player ship."""
    import App
    hl, controller = _fresh_quickbattle_loader(monkeypatch)

    session = controller.loader.load_quickbattle()

    assert session is not None
    # The region set the cascade built must exist.
    assert App.g_kSetManager.GetSet("QuickBattleRegion") is not None

    # The mission assigned its XO global pointer.
    import QuickBattle.QuickBattle as QB
    assert QB.g_pXO is not None

    # An initial player ship exists on the current Game.
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    assert game is not None
    assert game.GetPlayer() is not None


def test_quickbattle_player_only_defaults(monkeypatch):
    """After the cascade the player-only default state is injected: Galaxy
    player ship + GalaxyBridge, QuickBattleRegion selected, empty enemy/friend
    lists."""
    hl, controller = _fresh_quickbattle_loader(monkeypatch)

    controller.loader.load_quickbattle()

    import QuickBattle.QuickBattle as QB
    assert QB.g_sPlayerType == "Galaxy"
    assert QB.g_sBridgeType == "GalaxyBridge"
    assert QB.g_sSelectedRegion == "QuickBattleRegion"
    assert QB.g_kEnemyList == []
    assert QB.g_kFriendList == []


def test_start_simulation_event_schedules_sequence(monkeypatch):
    """Posting ET_START_SIMULATION to g_pXO runs the SDK StartSimulation
    handler, which schedules the 2s TGSequence that eventually preloads and
    posts ET_PRELOAD_DONE. Driving the timer manager past 2s runs
    StartSimulationAction which calls SetPreLoadDoneEvent; _fire_pending_preload_done
    then posts ET_PRELOAD_DONE so StartSimulation2 runs and spawns into the set.
    """
    import App
    hl, controller = _fresh_quickbattle_loader(monkeypatch)

    controller.loader.load_quickbattle()
    controller.loader.start_quickbattle()

    import QuickBattle.QuickBattle as QB
    from engine.core.game import Game_GetCurrentGame

    # StartSimulation entered the simulation-loading path: the 2s preload
    # sequence sets the game's pre-load-done event when it fires.
    game = Game_GetCurrentGame()
    assert game._preload_done_event is None  # not yet — sequence still pending

    # Advance the game clock past the 2s TGSequence delay and pump timers so
    # StartSimulationAction runs (-> Game.SetPreLoadDoneEvent).
    App.g_kTimerManager.tick(3.0)

    assert game._preload_done_event is not None  # StartSimulationAction ran

    # The host's per-tick hook posts + clears the pre-load-done event, which
    # the SDK broadcast handler routes to StartSimulation2.
    hl._fire_pending_preload_done()

    assert QB.bInSimulation == 1  # StartSimulation2 ran
    # StartSimulation2 -> RecreatePlayer left a live player on the Game.
    assert game.GetPlayer() is not None


def test_boot_does_not_auto_start_or_auto_open(monkeypatch):
    """The boot seam loads the QuickBattle cascade WITHOUT auto-posting
    ET_START_SIMULATION and WITHOUT auto-opening the setup panel.

    Boot leaves g_bDialogUp == 0 (config dialog not up), so
    _sync_quick_battle_panel keeps the panel closed; the player opens it from
    the XO menu (OpenConfigDialog -> g_bDialogUp = 1). This test drives that
    sync directly against the real QuickBattle flag.
    """
    from types import SimpleNamespace
    import QuickBattle.QuickBattle as QB
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.session = controller.loader.load_quickbattle()

    # No ET_START_SIMULATION at boot; SDK never entered the sim-loading path.
    assert QB.bInSimulation == 0
    # And the config dialog is not up after boot.
    assert getattr(QB, "g_bDialogUp", 0) == 0

    panel = QuickBattleSetupPanel()
    fake_controller = SimpleNamespace(quick_battle_setup_panel=panel)
    saved = QB.g_bDialogUp
    try:
        # Boot state (flag 0): sync leaves the panel closed.
        hl._sync_quick_battle_panel(fake_controller)
        assert panel.is_open() is False
        # Player clicks the XO config button -> OpenConfigDialog sets the flag.
        QB.g_bDialogUp = 1
        hl._sync_quick_battle_panel(fake_controller)
        assert panel.is_open() is True
        # Close/Start clears it -> sync hides the panel.
        QB.g_bDialogUp = 0
        hl._sync_quick_battle_panel(fake_controller)
        assert panel.is_open() is False
    finally:
        QB.g_bDialogUp = saved


def test_open_config_dialog_sets_dialog_up(monkeypatch):
    """Firing the XO config button's event (ET_OPEN_DIALOG -> OpenConfigDialog)
    runs to completion through the shims and sets g_bDialogUp = 1, which is what
    _sync_quick_battle_panel mirrors to open the CEF panel. Guards the
    _TopWindow focus/z-order surface (GetFocus/SetFocus/MoveToFront) that
    OpenConfigDialog walks."""
    import App
    import QuickBattle.QuickBattle as QB

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.session = controller.loader.load_quickbattle()
    assert QB.g_bDialogUp == 0

    evt = App.TGEvent_Create()
    evt.SetEventType(QB.ET_OPEN_DIALOG)
    evt.SetDestination(QB.g_pXO)
    App.g_kEventManager.AddEvent(evt)

    assert QB.g_bDialogUp == 1


def test_generate_ships_with_enemy_roster_completes(monkeypatch):
    """GenerateShips runs its per-ship body for the first time once a roster is
    non-empty (SP1 was player-only). Add one enemy and assert the spawn loop
    completes without raising and records the ship — surfaces any missing Appc
    surface in the per-ship path (e.g. _TGString.Append, SetDisplayName, the
    placement/proximity calls)."""
    import QuickBattle.QuickBattle as QB
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.session = controller.loader.load_quickbattle()

    # (sShipType, sShipName, sDestroyedMessage, sWhichAI, sWhichSide, sAINumber)
    QB.g_kEnemyList = [
        ("Galaxy", "Galaxy", "msg", "QuickBattle.QuickBattleAI", "Enemy", 0.5),
    ]
    QB.GenerateShips()

    # The enemy ship was created and recorded in the global ship map.
    assert len(QB.g_kShips) >= 1

    # Its rotation must be non-degenerate: GenerateShips aligns the enemy to the
    # player's backward/up via GetWorldBackwardTG/GetWorldUpTG, which must return
    # real vectors (not _Stubs) so the forward column isn't zero — a zero column
    # later crashes render interpolation.
    import App
    for iShipID in QB.g_kShips:
        pShip = App.ShipClass_Cast(App.TGObject_GetTGObjectPtr(iShipID))
        if pShip is None:
            continue
        fwd = pShip.GetWorldRotation().GetCol(1)
        assert fwd.x * fwd.x + fwd.y * fwd.y + fwd.z * fwd.z > 1e-6, \
            "enemy forward column is degenerate"


def test_full_start_with_enemy_runs_ai_assignment(monkeypatch):
    """End-to-end Start with a non-empty enemy roster: drives the real
    StartSimulation -> 2s sequence -> StartSimulation2, which runs GenerateShips
    AND the per-ship AI assignment (import sWhichAI -> CreateAI -> pShip.SetAI)
    and the red-alert/tactical switch. Mirrors the live flow after the player
    clicks Add As Enemy then Start; surfaces AI/ChangeRegion shim gaps."""
    import App
    import QuickBattle.QuickBattle as QB
    from engine.core.game import Game_GetCurrentGame

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()

    # The player adds one enemy via the panel before Start.
    QB.g_kEnemyList = [
        ("Galaxy", "Galaxy", "msg", "QuickBattle.QuickBattleAI", "Enemy", 0.5),
    ]

    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)          # past the 2s preload sequence
    hl._fire_pending_preload_done()        # -> StartSimulation2

    assert QB.bInSimulation == 1           # StartSimulation2 completed
    assert len(QB.g_kShips) >= 1           # enemy spawned + recorded
    assert Game_GetCurrentGame().GetPlayer() is not None


def test_end_combat_removes_simulated_ships(monkeypatch):
    """EndSimulation ("End Combat") flags every non-player ship with
    SetDeleteMe(1); the host's _process_object_deletions then removes them from
    the set (and reconciliation tears down their render instances). Verifies the
    targets actually leave the scene when combat ends."""
    import App
    import QuickBattle.QuickBattle as QB

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    QB.g_kEnemyList = [
        ("Galaxy", "Galaxy", "msg", "QuickBattle.QuickBattleAI", "Enemy", 0.5),
    ]
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()          # StartSimulation2 spawns the enemy
    assert QB.bInSimulation == 1

    def _non_player_ships():
        return [s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)
                if s.GetName() != "Player"]

    assert len(_non_player_ships()) >= 1

    QB.EndSimulation()                       # End Combat
    assert QB.bInSimulation == 0
    hl._process_object_deletions()           # host removes flagged objects

    assert _non_player_ships() == []         # simulated targets gone


def test_player_ship_reverts_to_original_on_end_combat(monkeypatch):
    """_sync_quickbattle_player_revert captures the original (pre-pick) ship ONCE
    and, on End Combat (1->0), reverts to it — so a ship picked for QuickBattle
    (config OR combat) never leaves the player stuck on it."""
    from types import SimpleNamespace
    import QuickBattle.QuickBattle as QB

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()

    recreated = []
    monkeypatch.setattr(QB, "RecreatePlayer", lambda: recreated.append(QB.g_sPlayerType))
    saved_type, saved_sim = QB.g_sPlayerType, QB.bInSimulation
    ctrl = SimpleNamespace()
    try:
        QB.g_sPlayerType = "Galaxy"
        QB.bInSimulation = 0
        hl._sync_quickbattle_player_revert(ctrl)        # first tick: capture original
        assert ctrl._qb_original_player_type == "Galaxy"

        QB.bInSimulation = 1                            # combat starts
        hl._sync_quickbattle_player_revert(ctrl)
        QB.g_sPlayerType = "Sovereign"                 # picked a ship for the sim
        QB.bInSimulation = 0                           # End Combat
        hl._sync_quickbattle_player_revert(ctrl)       # -> revert to original

        assert QB.g_sPlayerType == "Galaxy"            # back to the original ship
        assert recreated == ["Galaxy"]
    finally:
        QB.g_sPlayerType, QB.bInSimulation = saved_type, saved_sim


def test_no_revert_when_player_ship_unchanged(monkeypatch):
    """If the player never picked a different ship, End Combat does not fire an
    extra RecreatePlayer."""
    from types import SimpleNamespace
    import QuickBattle.QuickBattle as QB

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()

    recreated = []
    monkeypatch.setattr(QB, "RecreatePlayer", lambda: recreated.append(QB.g_sPlayerType))
    saved_type, saved_sim = QB.g_sPlayerType, QB.bInSimulation
    ctrl = SimpleNamespace()
    try:
        QB.g_sPlayerType = "Galaxy"
        QB.bInSimulation = 0
        hl._sync_quickbattle_player_revert(ctrl)        # capture original
        QB.bInSimulation = 1
        hl._sync_quickbattle_player_revert(ctrl)
        QB.bInSimulation = 0                            # end, no pick
        hl._sync_quickbattle_player_revert(ctrl)
        assert QB.g_sPlayerType == "Galaxy"
        assert recreated == []                          # no extra recreate
    finally:
        QB.g_sPlayerType, QB.bInSimulation = saved_type, saved_sim


def test_player_ship_reverts_through_real_end_combat(monkeypatch):
    """Drive the REAL flow (no mocks): start combat as Galaxy, swap to Sovereign
    mid-combat, run the real EndSimulation, then the revert sync — the live
    player ship must come back as Galaxy (a fresh player object recreated)."""
    import App
    import QuickBattle.QuickBattle as QB
    from engine.core.game import Game_GetCurrentGame

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    hl._sync_quickbattle_player_revert(controller)  # boot tick: capture original
    assert controller._qb_original_player_type == "Galaxy"

    QB.g_kEnemyList = [
        ("Galaxy", "Galaxy", "msg", "QuickBattle.QuickBattleAI", "Enemy", 0.5),
    ]
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()                 # StartSimulation2: in sim, Galaxy
    hl._sync_quickbattle_player_revert(controller)
    assert QB.bInSimulation == 1

    # Pick Sovereign for the sim (real RecreatePlayer).
    QB.g_sPlayerType = "Sovereign"
    QB.RecreatePlayer()
    assert QB.g_sPlayerType == "Sovereign"

    # End Combat (real EndSimulation -> bInSimulation=0, recreates as Sovereign).
    QB.EndSimulation()
    assert QB.bInSimulation == 0
    player_after_end = Game_GetCurrentGame().GetPlayer()

    hl._sync_quickbattle_player_revert(controller)  # revert to original
    assert QB.g_sPlayerType == "Galaxy"
    player_after_revert = Game_GetCurrentGame().GetPlayer()
    assert player_after_revert is not None
    assert player_after_revert is not player_after_end   # revert recreated the player
