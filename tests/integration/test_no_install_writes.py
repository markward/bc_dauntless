"""Dynamic guard: running the game writes nothing into the install folder or
the player's BC install (spec: per-user data dirs; Ruling 12).

The static guard (tests/unit/test_install_write_guard.py) reads source, so a
path that reaches a writer through another module, an SDK script or the
working directory is invisible to it. Here an audit hook
(tests/helpers/write_audit.py) records every write while real code runs:
every campaign mission loaded and warped exactly as the warp-button sweep
does, and the QuickBattle boot.

Allowed: anything under the test's own temp user-data dir (each test sets
DAUNTLESS_DATA_DIR to a tmp_path dir, so a developer's own setting cannot
widen the exemption), pytest's temp dirs and `__pycache__`.
"""
import sys

import pytest

from engine import paths
from engine.appc import save_load
from tests.helpers import headless_mission as hm
from tests.helpers import write_audit
from tests.integration.test_warp_button_handler_sweep import MISSIONS


# Campaign missions whose autosave this run does not reach: E1M1 saves from
# a later tutorial action (SaveTheGame), E4M6 only on arrival at a system.
# Every other mission autosaves (MissionLib.SaveGame) during this run.
NO_AUTOSAVE_IN_THIS_RUN = {
    "Maelstrom.Episode1.E1M1.E1M1",
    "Maelstrom.Episode4.E4M6.E4M6",
}


def _install_writes(records):
    return write_audit.stray_writes(records, paths.PROJECT_ROOT,
                                    paths.game_root())


@pytest.fixture
def autosaves(monkeypatch):
    """The save names the SDK wrote successfully through SaveToFile."""
    written = []
    real = save_load.SaveLoadManager.SaveToFile

    def _spy(self, filename):
        ok = real(self, filename)
        if ok:
            written.append(filename)
        return ok
    monkeypatch.setattr(save_load.SaveLoadManager, "SaveToFile", _spy)
    return written


@pytest.fixture
def fresh_mission_module(request):
    """Run the mission from a fresh import, and leave none behind.

    Works around a KNOWN ENGINE ISSUE (tracked as a follow-up): a second
    host_loop._init_mission of the same mission in one process reuses the
    cached module and its stale globals. This sweep repeats
    test_warp_button_handler_sweep's missions, and E3M4 breaks on the
    second run (g_iPartOneProgress / g_bItari still set, so
    UncloakWarbirds finds no "Soryak"). Evict the mission's package modules
    before and after, whichever sweep runs first. Remove this fixture once
    the engine re-imports a mission on load.
    """
    package = request.getfixturevalue("name").rsplit(".", 1)[0]

    def _evict():
        for mod in [m for m in sys.modules
                    if m == package or m.startswith(package + ".")]:
            del sys.modules[mod]
    _evict()
    yield
    _evict()


@pytest.mark.parametrize("name", MISSIONS)
def test_campaign_missions_write_nothing_into_install_or_game(
        name, autosaves, fresh_mission_module, monkeypatch, tmp_path):
    # This test's own data dir: the exemption covers only it, never a
    # developer's DAUNTLESS_DATA_DIR (which might sit inside the checkout).
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    with write_audit.recording() as records:
        hm.drive_warp(name)  # the warp-button sweep's own body

    assert _install_writes(records) == []
    if name in NO_AUTOSAVE_IN_THIS_RUN:
        return
    # The hook saw the autosave land where it should: proof it was watching
    # while the SDK wrote, not blind.
    assert autosaves, "%s no longer autosaves in this run; update the list" % name
    assert write_audit.under(records, paths.saves_dir()), (autosaves, records)


def test_quickbattle_boot_writes_nothing_into_install(monkeypatch, tmp_path):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader

    # A fresh data dir, so no earlier test's Options.cfg is already there.
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    options = paths.config_dir() / "Options.cfg"
    assert not options.exists()

    with write_audit.recording() as records:
        hl, controller = _fresh_quickbattle_loader(monkeypatch)
        controller.loader.load_quickbattle()

    assert _install_writes(records) == []
    assert options.is_file()
    assert any(event == "open" and path == str(options)
               for event, path, _ in records), records
