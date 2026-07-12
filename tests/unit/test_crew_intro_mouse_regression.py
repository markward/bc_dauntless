"""Regression: E1M1's crew-intro sequence halts after the XO's "condition
green set for departure" line.

Root cause: the crew-intro TGSequence's MoveMouseToCenter / HoldMouseAtCenter
script actions (sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py:5050/5069)
call MissionLib.MoveMouseCursorToUIObject(App.g_kRootWindow, ...)
(MissionLib.py:2863), which calls pObject.GetScreenOffset(kOffset).
App.g_kRootWindow is a plain TGPane that nothing ever lays out, so
_abs_rect stays None. TGPane.GetScreenOffset used to raise
LayoutNotResolved in that case, which killed the TGScriptAction, which
meant the sequence's AddCompletedEvent (E1M1.py:2382-2387, commented "so
the calling sequence continues") never fired, which halted the calling
sequence — no more dialogue played.

BC's own script-action convention is that these must not throw ("Return: 0
- Return 0 to keep calling sequence from crashing"), so GetScreenOffset must
never raise onto an SDK call path — see engine/appc/tg_ui/widgets.py.
"""
import tools.mission_harness as mh


def test_movemousecursor_to_root_window_does_not_raise():
    mh.setup_sdk()
    import App
    import MissionLib

    # Must not raise LayoutNotResolved (or anything else) — this is the
    # exact call that killed E1M1's crew-intro sequence.
    MissionLib.MoveMouseCursorToUIObject(App.g_kRootWindow, 0)
