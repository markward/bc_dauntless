"""Warp-in flash records (warp-in spec).

WarpFlash_Create / WarpFlash_CreateWithoutShip are the SDK's flash calls.
Each makes a plain game-time record (not a set object, not targetable); the
renderer draws it from render data. `advance(dt)` is run by GameLoop.tick.
"""
from dataclasses import dataclass


@dataclass
class WarpInFlash:
    set_name: str
    center: tuple      # set-local GU
    forward: tuple     # unit vector
    radius: float
    age: float
    lifetime: float


_active: list = []
_spawned = 0


def _xyz(p):
    if hasattr(p, "x"):
        return (float(p.x), float(p.y), float(p.z))
    return (float(p[0]), float(p[1]), float(p[2]))


def _default_lifetime():
    from engine.appc import warp_in_dials
    from engine.appc.subsystems import WarpEngineSubsystem_GetWarpEffectTime
    return WarpEngineSubsystem_GetWarpEffectTime() * warp_in_dials.get("life_frac")


def spawn(pSet, center, forward, radius, lifetime=None) -> WarpInFlash:
    global _spawned
    flash = WarpInFlash(
        set_name=pSet.GetName() if pSet is not None else "",
        center=_xyz(center),
        forward=_xyz(forward),
        radius=float(radius),
        age=0.0,
        lifetime=float(_default_lifetime() if lifetime is None else lifetime),
    )
    _active.append(flash)
    _spawned += 1
    return flash


def advance(dt: float) -> None:
    dt = float(dt)
    if dt <= 0.0 or not _active:
        return
    for f in _active:
        f.age += dt
    # 1e-9 slack: 90 ticks of 1/60 sum to 1.4999999999999996, not 1.5.
    _active[:] = [f for f in _active if f.age < f.lifetime - 1e-9]


def active() -> list:
    return list(_active)


def spawned_count() -> int:
    return _spawned


def reset() -> None:
    global _spawned
    _active.clear()
    _spawned = 0


def WarpFlash_CreateWithoutShip(pSet, pLocation, pRotation, fRadius, fTime=None):
    if pSet is None:
        return None
    radius = float(fRadius)
    if radius <= 0.0:
        from engine.appc import warp_in_dials
        radius = warp_in_dials.get("fallback_radius_gu")
    return spawn(pSet, pLocation, pRotation.GetCol(1), radius, fTime)


def WarpFlash_Create(pShip, fTime=None):
    if pShip is None:
        return None
    pSet = pShip.GetContainingSet()
    if pSet is None:
        return None
    from engine.appc import warp_state
    return spawn(pSet, pShip.GetWorldLocation(),
                 pShip.GetWorldRotation().GetCol(1),
                 warp_state.warp_in_radius(pShip), fTime)
