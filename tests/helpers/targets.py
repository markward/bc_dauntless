"""A real target for weapon tests (fire control native only, Task 6, M3):
the native kernel aims only at objects the mirror names, so a duck-typed
stand-in with GetWorldLocation/IsDead is a counted no-fire (unnamed_target,
stale_row) where fire control's deleted Python copy accepted it."""
import itertools

_names = itertools.count()


def real_target(x, y, z, like=None, name=None):
    """A live ship at (x, y, z); in `like`'s set when `like` (the shooter)
    is in one (the phaser's same-set gate)."""
    from engine.appc.ships import ShipClass_Create
    target = ShipClass_Create(name or "Target %d" % next(_names))
    target.SetTranslateXYZ(float(x), float(y), float(z))
    pset = like.GetContainingSet() if like is not None and hasattr(
        like, "GetContainingSet") else None
    if pset is not None:
        pset.AddObjectToSet(target, target.GetName())
    return target
