"""The native picker's guards, driven against a fake `_dauntless_host` -- no
dialog is ever shown.

The blocking-loop flow this module used to test (`prompt_for_missing`) is
gone: that loop is now `engine.ui.first_run_panel.FirstRunPanel`'s job, and
its tests live in tests/unit/test_first_run_panel.py. What remains here is
_default_picker itself, which nothing else exercises.
"""

from engine import first_run


def test_a_raising_binding_is_treated_as_no_picker(monkeypatch):
    """FINDING 3: signature drift, a non-UTF-8 path, anything the binding
    itself raises must collapse to the same "no picker" answer as a
    cancel or a missing binding -- not an unhandled traceback out of
    run(). Exercise _default_picker directly against a fake
    _dauntless_host so the real native module is never touched.
    """
    import sys
    import types

    fake_module = types.ModuleType("_dauntless_host")

    def _raising_pick_folder(title, message):
        raise RuntimeError("boom")

    fake_module.pick_folder = _raising_pick_folder
    monkeypatch.setitem(sys.modules, "_dauntless_host", fake_module)

    assert first_run._default_picker("title", "message") is None
