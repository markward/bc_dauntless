"""ObjectClass_GetObjectByID must tolerate a None object id.

Regression: SDK Conditions/ConditionIncomingTorps.py:172
(CheckTorpedo) calls App.ObjectClass_GetObjectByID(None, self.iTargetID)
while iTargetID is still None (it is set only later, at line 246). Real
Appc returns null for a null id; our shim did int(obj_id) -> int(None) ->
TypeError, which spammed the event dispatcher every time a torpedo entered
a set. The SDK caller already handles a falsy return (`if pTarget:`), so the
faithful fix is to return None for a None id.
"""
import App
from engine.appc.objects import ObjectClass_GetObjectByID


def test_get_object_by_id_none_returns_none():
    assert ObjectClass_GetObjectByID(None, None) is None


def test_app_get_object_by_id_none_returns_none():
    # Same via the App surface the SDK actually calls.
    assert App.ObjectClass_GetObjectByID(None, None) is None
