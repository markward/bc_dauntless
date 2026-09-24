"""Put test objects in ONE set, so they share a FRAME and can interact.

Collision pairing, splash damage and torpedo hit/homing only let two objects
interact when they compare in the same FRAME (`engine.systems.frames`,
system-frames spec Sec1/Sec6) -- objects in the same set are always the same
frame (`offset_between` returns zero). An object in no set has no frame and
interacts with nothing. Tests that exercise those paths on bare objects --
hand-rolled doubles, or real ObjectClasses never added to a set -- put them in
one set with `share_one_set`; what the test then asserts is unchanged.

The set is a real SetClass that is NOT registered with g_kSetManager, so no
set walk (iter_ships, iter_collidables) starts seeing objects it did not see
before -- membership is only visible through GetContainingSet().
"""
import App


class InSet:
    """Mixin for hand-rolled doubles: the containing-set surface ObjectClass
    has. `engine.systems.frames.containing_set` probes it with `implements`,
    so it must be a real method on the class."""
    _containing_set = None

    def GetContainingSet(self):
        return self._containing_set


def share_one_set(*objs):
    """Put every object in one fresh, unregistered SetClass; return the set."""
    pSet = App.SetClass_Create()
    for obj in objs:
        obj._containing_set = pSet
    return pSet


def one_set_for(*double_classes, monkeypatch):
    """Put every instance of the given double classes (InSet subclasses) in
    one fresh set for the duration of a test, and return the set.

    A torpedo fired from such a double joins that set through the production
    path (projectiles._join_source_set), so shooter, victims and torpedo all
    meet without any per-test wiring."""
    pSet = App.SetClass_Create()
    for cls in double_classes:
        monkeypatch.setattr(cls, "_containing_set", pSet)
    return pSet
