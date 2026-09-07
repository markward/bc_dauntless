"""DamageableObject_GetObjectByID must be real surface, not an App stub.

Regression: Effects.DeathExplosionDamage (sdk/Build/scripts/Effects.py:689) —
the action BC's death cascade schedules ~30% of the time — resolves its victim
with::

    pObject = App.DamageableObject_GetObjectByID(None, iObjectID)
    if (pObject):
        pObject.AddDamage(pEmitPos, fRadius, fDamage)

`ObjectClass_GetObjectByID` and `ShipClass_GetObjectByID` were both defined, but
the DamageableObject sibling was not, so it resolved to a truthy `App._NamedStub`.
The `if (pObject)` guard passed, `.AddDamage` landed on the stub, and every hull
carve BC's death sequence makes was silently discarded — the exact
truthiness-risk class the stub heatmap exists to catch (docs/stub_heatmap.md).
"""
import App
from engine.appc.objects import DamageableObject, DamageableObject_GetObjectByID


def test_app_surface_is_not_a_stub():
    """The bug: a _NamedStub is truthy, so the SDK's `if (pObject)` guard
    passes and AddDamage no-ops against the stub."""
    assert not isinstance(App.DamageableObject_GetObjectByID, App._NamedStub)


def test_resolves_a_damageable_object_by_id():
    obj = DamageableObject()
    assert DamageableObject_GetObjectByID(None, obj.GetObjID()) is obj


def test_none_id_returns_none():
    """SDK callers pass an unset id and rely on a falsy return; must not raise."""
    assert DamageableObject_GetObjectByID(None, None) is None


def test_non_damageable_id_returns_none():
    """A Waypoint is an ObjectClass but not damageable — the DamageableObject
    lookup must not hand it back, or AddDamage would land on something with no
    hull."""
    from engine.appc.placement import Waypoint
    waypoint = Waypoint()
    assert DamageableObject_GetObjectByID(None, waypoint.GetObjID()) is None
