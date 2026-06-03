"""Integration test for the TopWindow input gate.

Verifies that g_kEventManager broadcast dispatch consults
TopWindow.AllowKeyboardInput so SDK handlers registered for
ET_KEYBOARD_EVENT don't fire during a scripted cutscene.
"""


def test_keyboard_event_skipped_when_top_window_gate_off():
    import App
    from engine.appc import top_window
    from engine.appc.events import TGKeyboardEvent, ET_KEYBOARD_EVENT

    top_window.reset_for_tests()
    # Wipe broadcast handlers from any prior test so only the engine's
    # registered keyboard trampoline is in play.
    App.g_kEventManager._broadcast_handlers.clear()
    from engine.appc.input import register_input_handlers
    register_input_handlers(App.g_kEventManager)

    # Stub the keyboard binding so we can observe whether OnKeyboardEvent
    # was reached.
    from engine.appc import input as appc_input
    received = []

    class RecordingBinding:
        def OnKeyboardEvent(self, obj, evt):
            received.append(evt)

    saved = appc_input.g_kKeyboardBinding
    appc_input.g_kKeyboardBinding = RecordingBinding()
    try:
        # AddEvent dispatches synchronously (events.py:256-275): the
        # broadcast handlers fire inline. No ProcessEvents() needed.

        # Push one event with the gate OPEN — handler should fire.
        evt1 = TGKeyboardEvent()
        evt1.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt1)
        assert len(received) == 1

        # Close the gate; push another event — handler must NOT fire.
        App.TopWindow_GetTopWindow().AllowKeyboardInput(0)
        evt2 = TGKeyboardEvent()
        evt2.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt2)
        assert len(received) == 1  # unchanged

        # Re-open the gate; events flow again.
        App.TopWindow_GetTopWindow().AllowKeyboardInput(1)
        evt3 = TGKeyboardEvent()
        evt3.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt3)
        assert len(received) == 2
    finally:
        appc_input.g_kKeyboardBinding = saved
