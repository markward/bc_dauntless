"""host_loop.run() uninstalls the warp, warp-VFX and warp-gate hooks and the
bridge controllers it installed, as it does mission_change's. Left installed they close over a dead
controller: the starbase line-of-sight hook read a stale session and refused
every later warp near Starbase 12 (found by the Task 8 campaign E2E tests)."""
import pytest

from tests.helpers import bc_assets


def test_run_leaves_no_warp_hooks_installed(monkeypatch):
    GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships"
                  / "Galaxy" / "Galaxy.nif")
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from engine import host_loop
    from engine.appc import warp, warp_gates
    from engine.core import mission_change
    assert host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic",
                         max_ticks=2) == 0
    assert (warp._realize_hook, warp._teardown_hook, warp._player_hook) == \
        (None, None, None)
    assert (warp._vfx_start, warp._vfx_stop, warp._vfx_enabled,
            warp._vfx_vantage_of) == (None, None, None, None)
    assert warp_gates._ray_collide_hook is None
    assert mission_change._on_changed is None


def test_run_leaves_no_bridge_controllers_registered(monkeypatch):
    """The bridge walk controller leaked from run() made every later headless
    MoveTo wait on a renderer that no longer exists: E4M4's briefing (a
    Tactical walk to "T") never finished, so a warp held on WaitForQueued
    forever."""
    GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships"
                  / "Galaxy" / "Galaxy.nif")
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from engine import (host_loop, bridge_camera_watch, bridge_character_anim,
                        bridge_character_walk, bridge_cutscene)
    assert host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic",
                         max_ticks=2) == 0
    assert bridge_cutscene.get_controller() is None
    assert bridge_character_anim.get_controller() is None
    assert bridge_character_walk.get_controller() is None
    assert bridge_camera_watch.get_controller() is None


def test_run_leaves_no_quickbattle_spawn_provider_registered(monkeypatch):
    """engine.quickbattle.spawn._provider (the setup panel) is process-global.
    Left registered after run() returns it closes over a dead panel -- the same
    leaked-hook class as the warp and bridge-controller hooks above. The panel
    is built for EVERY mission, so a mission run is a real test of it.
    (_radius_fn is only set by the QuickBattle boot; its check lives in the
    QuickBattle-boot test below, where it is actually installed.)"""
    GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships"
                  / "Galaxy" / "Galaxy.nif")
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from engine import host_loop
    from engine.quickbattle import spawn as qb_spawn
    assert host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic",
                         max_ticks=2) == 0
    assert qb_spawn._provider is None


def test_run_leaves_no_quickbattle_hooks_registered_after_qb_boot(monkeypatch):
    """The QuickBattle boot installs three process-global hooks:
    bridge_selection._player_type_resolver (the home-ship rule) and
    spawn._radius_fn (the loader's radius seed) in load_quickbattle, plus
    spawn._provider (the setup panel). Left registered after run() returns
    they close over a dead controller. Only load_quickbattle (mission_name=
    None -- the no-mission-name QuickBattle boot) sets the first two, so this
    drives THAT boot path rather than the M1Basic mission the sibling tests
    use -- an M1Basic run never installs _radius_fn, so asserting it there
    proved nothing (post-merge review)."""
    GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships"
                  / "Galaxy" / "Galaxy.nif")
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from engine import host_loop
    from engine import bridge_selection
    from engine.quickbattle import spawn as qb_spawn
    assert host_loop.run(max_ticks=2) == 0
    assert bridge_selection._player_type_resolver is None
    assert qb_spawn._radius_fn is None
    assert qb_spawn._provider is None
