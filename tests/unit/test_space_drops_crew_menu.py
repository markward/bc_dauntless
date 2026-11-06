"""Space from the bridge to the outside view closes the open crew menu.

The original game shows no officer's menu over the tactical view; Dauntless
kept the clicked officer's menu up after Space (user report 2026-10-16, Brex).
ToggleBridgeAndTactical now closes it exactly as Escape does
(CrewMenuPanel.close_open_menu) on the way out, and leaves it alone on the
way back. BridgeHandlers.DropMenusTurnBack is NOT used: it is stubbed here,
which is why the first attempt did nothing.
"""


class _Panel:
    def __init__(self):
        self.closed = 0

    def close_open_menu(self):
        self.closed += 1
        return True

    def get_open_menu(self):
        return None


def test_space_to_tactical_closes_the_open_menu_like_escape(monkeypatch):
    from engine.ui import crew_menu_hotkeys
    panel = _Panel()
    monkeypatch.setattr(crew_menu_hotkeys, "get_panel", lambda: panel)
    from engine.appc.top_window import TopWindow_GetTopWindow
    top = TopWindow_GetTopWindow()
    top.ForceBridgeVisible()
    top.ToggleBridgeAndTactical()            # bridge -> tactical
    assert panel.closed == 1
    top.ToggleBridgeAndTactical()            # tactical -> bridge: nothing closed
    assert panel.closed == 1
