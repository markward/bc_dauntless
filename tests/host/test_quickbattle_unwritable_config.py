"""H1: QuickBattle with an unwritable config folder and no Options.cfg.

The SDK's QuickBattle.BuildDialog early-returns, skipping the Start button,
when LoadConfigFile("Options.cfg") returns 0, and StartSimulation later calls
g_pStartButton.SetDisabled() unconditionally. The boot writes Options.cfg into
config_dir() first so the load succeeds (host_loop.load_quickbattle).

Observed before the fix (2026-10-16): with config_dir() unwritable the boot
itself returned, with QB.g_pStartButton None and one "could not write
.../Options.cfg: PermissionError" line on stderr; the player's Start then
raised AttributeError: 'NoneType' object has no attribute 'SetDisabled' in
DisableSimulationMenus, so Quick Battle could never start.

Decision: the boot completes. A player whose settings folder is read-only
loses their options for the session (reported once), not Quick Battle. The
in-memory mapping is exactly what a successful write would have read back,
so the cascade's one load of Options.cfg answers from memory.
"""
import os
import stat

import pytest

pytest.importorskip("_dauntless_host")


def test_quickbattle_boot_with_unwritable_config_dir(monkeypatch, tmp_path,
                                                     capsys):
    import App
    from engine import paths
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(data))
    assert paths.config_dir() == data
    options = data / "Options.cfg"
    data.chmod(0o500)
    try:
        if os.access(data, os.W_OK):
            pytest.skip("chmod 0o500 does not stop this user writing")
        hl, controller = _fresh_quickbattle_loader(monkeypatch)

        controller.loader.load_quickbattle()
        import QuickBattle.QuickBattle as QB
        assert QB.g_pStartButton is not None

        # The player's Start runs the real flow through StartSimulation2.
        controller.loader.start_quickbattle()
        App.g_kTimerManager.tick(3.0)
        hl._fire_pending_preload_done()
        assert QB.bInSimulation == 1

        # Nothing landed on disk, the failure was said once, and the
        # answer-from-memory did not outlive the cascade.
        assert not options.exists()
        err = capsys.readouterr().err
        assert err.count("could not write %s" % options) == 1, err
        assert App.g_kConfigMapping.LoadConfigFile("Options.cfg") == 0
    finally:
        data.chmod(stat.S_IRWXU)
