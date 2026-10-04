"""Tests for pause menu "Quit and Manage Mods" row."""

from engine.ui.pause_menu import default_pause_menu


def _ids(m):
    return [it.action_id for it in m._items]


def test_row_sits_just_above_exit_when_wired():
    fired = []
    m = default_pause_menu(on_exit=lambda: None, on_configuration=lambda: None,
                           on_resume=lambda: None, on_quit_manage_mods=lambda: fired.append(1))
    ids = _ids(m)
    assert ids[-2:] == ["quit-manage-mods", "exit"]
    labels = [it.label for it in m._items]
    assert labels[-2] == "Quit and Manage Mods"
    assert m.dispatch_event("quit-manage-mods") is True and fired == [1]


def test_row_absent_without_a_handler():
    m = default_pause_menu(on_exit=lambda: None, on_configuration=lambda: None, on_resume=lambda: None)
    assert "quit-manage-mods" not in _ids(m)
