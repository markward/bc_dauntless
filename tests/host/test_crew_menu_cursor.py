"""Crew-menu cursor freeing on the bridge.

Opening a crew menu (F1-F5) on the bridge must free the mouse cursor from
mouse-look mode so the menu is clickable, and re-lock it on close. The world
keeps running (no pause) — only the cursor lock + camera mouse-look change.

See engine/host_loop.py:_apply_crew_menu_side_effects.
"""


class _RecordingRenderer:
    def __init__(self):
        self.cursor_lock_calls = []   # list of bool

    def set_cursor_locked(self, locked):
        self.cursor_lock_calls.append(locked)

    # _apply_view_mode_side_effects also touches these on re-lock.
    def bridge_pass_set_enabled(self, enabled):
        pass


class _FakeCrewMenu:
    def __init__(self, open_):
        self._open = open_

    def has_open_menu(self) -> bool:
        return self._open


def _bridge_vm():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()           # constructs in BRIDGE mode
    assert vm.is_bridge
    vm._last_synced_is_bridge = True     # cursor already locked for bridge
    return vm


def _unpaused():
    from engine.host_loop import _PauseMenuController
    return _PauseMenuController()        # closed by default


def test_opening_crew_menu_frees_cursor():
    from engine.host_loop import _apply_crew_menu_side_effects
    vm, h, pause = _bridge_vm(), _RecordingRenderer(), _unpaused()
    menu = _FakeCrewMenu(True)
    _apply_crew_menu_side_effects(menu, vm, pause, h)
    assert h.cursor_lock_calls == [False]


def test_open_crew_menu_is_idempotent():
    from engine.host_loop import _apply_crew_menu_side_effects
    vm, h, pause = _bridge_vm(), _RecordingRenderer(), _unpaused()
    menu = _FakeCrewMenu(True)
    _apply_crew_menu_side_effects(menu, vm, pause, h)
    _apply_crew_menu_side_effects(menu, vm, pause, h)   # no state change
    assert h.cursor_lock_calls == [False]


def test_closing_crew_menu_invalidates_view_latch_so_cursor_relocks():
    from engine.host_loop import (_apply_crew_menu_side_effects,
                                  _apply_view_mode_side_effects)
    vm, h, pause = _bridge_vm(), _RecordingRenderer(), _unpaused()
    menu = _FakeCrewMenu(True)
    _apply_crew_menu_side_effects(menu, vm, pause, h)   # free cursor
    menu._open = False
    _apply_crew_menu_side_effects(menu, vm, pause, h)   # close -> invalidate latch
    assert vm._last_synced_is_bridge is None
    _apply_view_mode_side_effects(vm, h)                # view applier re-locks
    assert h.cursor_lock_calls == [False, True]


def test_no_unlock_when_no_menu_open():
    from engine.host_loop import _apply_crew_menu_side_effects
    vm, h, pause = _bridge_vm(), _RecordingRenderer(), _unpaused()
    menu = _FakeCrewMenu(False)
    _apply_crew_menu_side_effects(menu, vm, pause, h)
    assert h.cursor_lock_calls == []


def test_no_unlock_when_paused():
    """Paused already frees the cursor via the pause applier; the crew
    applier must not also drive it (avoids two writers fighting)."""
    from engine.host_loop import _apply_crew_menu_side_effects
    vm, h = _bridge_vm(), _RecordingRenderer()
    pause = _unpaused()
    pause.toggle()                       # paused
    menu = _FakeCrewMenu(True)
    _apply_crew_menu_side_effects(menu, vm, pause, h)
    assert h.cursor_lock_calls == []


class _FakeModal:
    def __init__(self, open_):
        self._open = open_

    def is_open(self) -> bool:
        return self._open


def test_open_quick_battle_setup_frees_cursor():
    """The Quick Battle Setup modal (opened from the XO menu) frees the cursor
    even with no crew menu open, so its buttons are clickable."""
    from engine.host_loop import _apply_crew_menu_side_effects
    vm, h, pause = _bridge_vm(), _RecordingRenderer(), _unpaused()
    menu = _FakeCrewMenu(False)        # no crew menu open
    qbs = _FakeModal(True)             # QB setup panel open
    _apply_crew_menu_side_effects(menu, vm, pause, h,
                                  quick_battle_setup_panel=qbs)
    assert h.cursor_lock_calls == [False]


def test_close_crew_menu_during_cutscene_closes_open_menu():
    """A cutscene must not leave the Helm/crew UI over the letterbox — an open
    crew menu is auto-closed once IsCutsceneMode() is True (BC's StartCutscene
    calls DropMenusTurnBack). Idempotent, and a no-op outside a cutscene."""
    from engine.host_loop import _close_crew_menu_during_cutscene

    class _FakeMenu:
        def __init__(self, open_):
            self._open = open_
            self.closed = 0

        def has_open_menu(self):
            return self._open

        def close_open_menu(self):
            self._open = False
            self.closed += 1
            return True

    # Cutscene active + menu open -> close it.
    m = _FakeMenu(True)
    _close_crew_menu_during_cutscene(m, cutscene_active=True)
    assert m.has_open_menu() is False and m.closed == 1
    # Idempotent — already closed, no second close.
    _close_crew_menu_during_cutscene(m, cutscene_active=True)
    assert m.closed == 1
    # Not a cutscene -> the open menu is left alone.
    m2 = _FakeMenu(True)
    _close_crew_menu_during_cutscene(m2, cutscene_active=False)
    assert m2.has_open_menu() is True and m2.closed == 0
