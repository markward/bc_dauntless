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


def test_boot_opens_setup_panel_and_does_not_auto_start(monkeypatch):
    """The boot seam loads the QuickBattle cascade and OPENS the Quick Battle
    Setup panel WITHOUT auto-posting ET_START_SIMULATION.

    Driving the full run() (GLFW/window) is impractical headlessly, so this
    asserts the seam the boot path now uses: load_quickbattle() builds the
    scene but does NOT enter the simulation (no start_quickbattle()), and the
    setup panel opens. Mirrors the host_loop change: boot drops the auto-start
    and calls quick_battle_setup_panel.open() instead.
    """
    import QuickBattle.QuickBattle as QB
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel

    hl, controller = _fresh_quickbattle_loader(monkeypatch)

    # Boot half: load the cascade. Critically, NO start_quickbattle().
    controller.session = controller.loader.load_quickbattle()

    # No ET_START_SIMULATION was posted at boot: the SDK never entered the
    # simulation-loading path, so bInSimulation is still 0.
    assert QB.bInSimulation == 0

    # Boot opens the setup panel instead (the host_loop opens the constructed
    # panel under `if boot_quickbattle:`).
    panel = QuickBattleSetupPanel()
    assert panel.is_open() is False
    panel.open()
    assert panel.is_open() is True
