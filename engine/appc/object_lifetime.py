# engine/appc/object_lifetime.py
"""Object lifetime countdown — faithful BC m_lifeTime (+0x14c) timed removal.

A DamageableObject whose SetLifeTime(N) is called with a finite value is
registered here. advance(dt) counts the object's lifetime down every frame and,
when it reaches zero, RETIRES the object: applies its faithful death splash
(BC m_splashDamage) then removes it from the world.

Mission scripts depend on this: E7M1 sets a doomed freighter's lifetime to 4.0
and plays only its own explosion VFX — nothing in the script removes the hull,
so without the engine countdown the wreck would linger forever.

This is a bounded, script-driven subset of the DEFERRED
DamageableObject::update() (DamageableObject.md sec 4.4); the full per-frame
damage-pool servicing is not reconstructed.
"""
import engine.dev_mode as dev_mode

# Objects with a finite lifetime, ticked every frame. Holds the objects
# themselves (not id()) so identity/strong-ref semantics match ship_death /
# warp_core_breach and CPython id-reuse cannot skip a recycled address.
_timed: list = []


def register(obj) -> None:
    """Register `obj` for lifetime countdown. Idempotent — a re-issued
    SetLifeTime just refreshes the object's own _life_time, not the list."""
    if obj is None:
        return
    if any(o is obj for o in _timed):
        return
    _timed.append(obj)


def advance(dt: float) -> None:
    """Tick every registered object's lifetime down by `dt`. Objects that reach
    zero are retired and dropped from the registry."""
    if not _timed:
        return
    survivors = []
    for obj in _timed:
        life = getattr(obj, "_life_time", None)
        if life is None:
            continue  # object lost its lifetime field somehow — drop it
        life -= dt
        obj._life_time = life
        if life > 0.0:
            survivors.append(obj)
        else:
            _expire(obj)
    _timed[:] = survivors


def _expire(obj) -> None:
    """Retire an object whose lifetime ran out: faithful death splash, then
    removal from the world. Raise-safe; a no-op on an already-dead object."""
    try:
        if hasattr(obj, "IsDead") and obj.IsDead():
            return
        from engine.appc import splash_damage
        splash_damage.apply(obj)
        from engine.appc import ship_death
        ship_death.retire(obj)
    except Exception as _e:
        dev_mode.log_swallowed("expire lifetime object", _e)


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _timed.clear()
