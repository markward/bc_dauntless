"""App.ShipClass_GetObjectByID tolerates interpreter shutdown.

Reachable path: SDK Conditions/ConditionPulseReady.py:46 (__del__) ->
`App.ShipClass_GetObjectByID(None, self.iObjectID)` -> the lazy
`from engine.core.ids import get_object_by_id` in
engine/appc/ships.py:ShipClass_GetObjectByID. During interpreter shutdown,
`sys.meta_path` is None and that import raises ImportError; without a guard
the exception propagates out of __del__, which CPython reports as
"Exception ignored in: ..." on stderr (see
tests/unit/test_pulse_weapon_property_cast.py's
test_condition_pulse_ready_sees_a_charged_forward_cannon, which exercises the
real shutdown timing for this path via GC).

This test forces the same ImportError deterministically -- independent of
GC/shutdown timing -- by making `engine.core.ids` unimportable for the
duration of one call, and asserts the function degrades to None instead of
raising.
"""
import sys

import App


def test_get_object_by_id_returns_none_when_ids_module_unimportable(monkeypatch):
    # sys.modules[name] = None is the documented way to make a bare `import`
    # statement raise ImportError for that exact module name (see the import
    # system docs); pytest's monkeypatch fixture restores sys.modules
    # afterwards regardless of test outcome.
    monkeypatch.setitem(sys.modules, "engine.core.ids", None)
    assert App.ShipClass_GetObjectByID(None, 12345) is None
