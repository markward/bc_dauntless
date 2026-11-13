"""release_ids scans the id registry once per deletion. A garbage
collection during that scan runs finalizers (SDK conditions tear down in
__del__), and a finalizer may register or unregister an id: snapshotting
with list(d.items()) allocated a tuple per entry, any of which could start
that collection, and the dict changed size mid-copy (RuntimeError). A
Quick Battle whose lone ship fought with its stock AI hit it on End."""
import gc

from engine.appc.objects import release_ids
from engine.core import ids


def test_registry_scan_survives_a_collection_mid_snapshot():
    """Every collection registers a fresh object (standing in for a
    finalizer that does), and the threshold makes the snapshot's own
    allocations collect: the scan must not see the dict change."""
    victim = ids.TGObject()
    for _ in range(50):
        ids.TGObject()               # entries for the snapshot to walk

    def _finalizer_stand_in(phase, _info):
        if phase == "start":
            ids.TGObject()

    old = gc.get_threshold()
    gc.callbacks.append(_finalizer_stand_in)
    try:
        gc.set_threshold(1)          # collect on (nearly) every tracked alloc
        release_ids(victim)
    finally:
        gc.set_threshold(*old)
        gc.callbacks.remove(_finalizer_stand_in)
    assert ids.get_object_by_id(victim.GetObjID()) is None
