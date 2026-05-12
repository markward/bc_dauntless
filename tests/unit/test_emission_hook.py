import tools.mission_harness as mh


def test_install_hook_is_idempotent():
    """Calling install_launch_object_hook() twice replaces the same slot,
    never composes."""
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook, _launch_object
    install_launch_object_hook()
    install_launch_object_hook()
    import Actions.ShipScriptActions as ssa
    assert ssa.LaunchObject is _launch_object
