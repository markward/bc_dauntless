import sys

import pytest

import tools.mission_harness as mh


@pytest.fixture
def restore_launch_object(monkeypatch):
    """Undo any hook install at teardown so the recorder never leaks into a
    later test that runs the real SDK LaunchObject."""
    mh.setup_sdk()
    import Actions.ShipScriptActions as ssa
    monkeypatch.setattr(ssa, "LaunchObject", ssa.LaunchObject)
    return ssa


def test_install_hook_is_idempotent(restore_launch_object):
    """Calling install_launch_object_hook() twice replaces the same slot,
    never composes."""
    from engine.appc.emission import install_launch_object_hook, _launch_object
    install_launch_object_hook()
    install_launch_object_hook()
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject is _launch_object


def _fresh_ship_script_actions(monkeypatch):
    # Re-import Actions.ShipScriptActions fresh (restored at teardown) so the
    # assertion sees what the setup path itself leaves behind.
    monkeypatch.delitem(sys.modules, "Actions.ShipScriptActions", raising=False)


def test_setup_sdk_leaves_the_sdk_launch_object(monkeypatch):
    """setup_sdk() is shared with the live host (host_loop._setup_sdk), so it
    must NOT install the recording hook: the recorder spawns nothing, and in
    the game Launch Probe / shuttles / decoys must spawn for real. Harness
    entry points that want the recorder install it themselves."""
    _fresh_ship_script_actions(monkeypatch)
    mh.setup_sdk()
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject.__module__ == "Actions.ShipScriptActions"


def test_host_sdk_setup_leaves_the_sdk_launch_object(monkeypatch):
    """The live game's real SDK setup path keeps the SDK's own LaunchObject."""
    from engine import host_loop
    _fresh_ship_script_actions(monkeypatch)
    host_loop._setup_sdk()
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject.__module__ == "Actions.ShipScriptActions"
