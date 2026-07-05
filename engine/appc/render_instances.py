"""Object → renderer InstanceId registry.

Mirror of ``session.ship_instances`` (engine.host_loop) so SDK-invoked
ObjectClass methods — which receive no session — can reach the object's
render instance. First consumer: ``ObjectClass.GetRandomPointOnModel``,
which samples the instance's hull surface points for death-effect scatter.

host_loop registers in the same two loops that populate
``session.ship_instances`` and clears via ``reset_sdk_globals()`` on every
mission load/swap. Keys are held weakly, so a dead ship never pins its
entry; a stale iid (instance destroyed while the object lives) is harmless —
renderer lookups on it return nothing and callers fall back.
"""

import weakref

_instances = weakref.WeakKeyDictionary()


def register(obj, iid) -> None:
    _instances[obj] = iid


def instance_for(obj):
    """Renderer InstanceId for obj, or None when it has no render instance."""
    try:
        return _instances.get(obj)
    except TypeError:  # unhashable/non-weakrefable test double
        return None


def reset() -> None:
    _instances.clear()
