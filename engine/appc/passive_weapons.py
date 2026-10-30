"""The passive weapons walk: host_loop._advance_weapons without the weapons
whose update would do nothing.

A full idle energy bank and a fully loaded torpedo tube return at the top of
UpdateCharge / UpdateReload. Measured at 100 ships, 709 of 790 UpdateCharge
calls per tick were that early-out (EnergyWeapon.UpdateCharge's comment), and
reaching them was most of `sim.weapons`. Here such a weapon is put to sleep
after its step and not visited again until a field that early-out reads is
written (passive_state.WakeField on the weapon classes). Skipping it is exact
because its update, run, would have changed nothing; the sleep audit
(DAUNTLESS_PASSIVE_AUDIT=1) runs it anyway and reports any field it changed.
Spec: docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md
§6.1, §6.3.

Each ship carries a registry: its weapons in today's walk order (phaser,
pulse, tractor, torpedo systems, then GetWeapon(i)) and the sorted indices of
the awake ones. The registry is cached on the ship, so anything that changes
which weapons a ship has must call invalidate(ship): ShipClass._attach_subsystem
(every Set*System) and ShipSubsystem.AddChildSubsystem do.
"""
from bisect import bisect_left, bisect_right, insort

from engine.appc import passive_state

# Bound on first use: weapon_subsystems imports this module.
_classes = None


def _weapon_classes():
    global _classes
    if _classes is None:
        from engine.appc.ships import ShipClass
        from engine.appc.weapon_subsystems import (
            TorpedoTube, WeaponSystem, _EnergyWeaponFireMixin,
        )
        _classes = (ShipClass, WeaponSystem, TorpedoTube, _EnergyWeaponFireMixin)
    return _classes


class _Registry:
    __slots__ = ("entries", "awake", "live")

    def __init__(self, entries):
        self.entries = entries                      # [(weapon, is_tube)]
        self.awake = list(range(len(entries)))      # sorted entry indices
        self.live = True                            # False once invalidated


def invalidate(ship) -> None:
    """Mark `ship`'s registry stale; the next advance rebuilds it with every
    weapon awake. Tolerates any ship-like object (test doubles included)."""
    d = getattr(ship, "__dict__", None)
    if d is None:
        return
    old = d.get("_passive_weapons")
    if old is not None:
        old.live = False
        d["_passive_weapons"] = None


def _groups(ship):
    """The weapon systems, in the walk's order. The one copy of that order:
    both walks below read it."""
    return (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
            ship.GetTractorBeamSystem(), ship.GetTorpedoSystem())


def _is_tube(emitter):
    """True for a torpedo tube (stepped with UpdateReload), False for an
    energy weapon (UpdateCharge), None for anything the walk skips.

    isinstance, NOT hasattr: TGObject.__getattr__ returns a truthy _Stub for
    any missing attribute, so hasattr() is vacuously True on every subsystem.
    The old hasattr(emitter, "UpdateCharge") guard therefore CALLED a no-op
    stub on every torpedo tube, every frame -- ranks 1 and 2 of
    docs/stub_heatmap.md, 4.5M hits. Charge is an EnergyWeapon concept
    (App.py:6426-6440); a TorpedoTube cannot have it."""
    _ship_cls, _system_cls, tube_cls, energy_cls = _weapon_classes()
    if isinstance(emitter, tube_cls):
        return True
    if isinstance(emitter, energy_cls):
        return False
    return None


def _build(ship):
    """A fresh registry for `ship`, or None when it cannot be cached: only a
    real ShipClass with real weapon systems has the invalidation hooks that
    keep a cached weapon list true."""
    ship_cls, system_cls = _weapon_classes()[:2]
    if not isinstance(ship, ship_cls):
        return None
    entries = []
    for group in _groups(ship):
        if group is None:
            continue
        if not isinstance(group, system_cls):
            return None
        for i in range(group.GetNumWeapons()):
            weapon = group.GetWeapon(i)
            is_tube = _is_tube(weapon)
            if is_tube is not None:
                entries.append((weapon, is_tube))
    registry = _Registry(entries)
    for index, (weapon, _) in enumerate(entries):
        weapon.__dict__["_passive_asleep"] = False
        weapon.__dict__["_passive_slot"] = (registry, index)
    ship.__dict__["_passive_weapons"] = registry
    return registry


def step_every_weapon(ship, dt: float) -> None:
    """The per-tick walk for one ship: every weapon, every tick. What
    host_loop._advance_weapons runs with passive state off, and what advance
    runs for a ship that cannot hold a registry."""
    for group in _groups(ship):
        if group is None:
            continue
        for i in range(group.GetNumWeapons()):
            emitter = group.GetWeapon(i)
            if emitter is None:
                continue
            is_tube = _is_tube(emitter)
            if is_tube:
                emitter.UpdateReload(dt)
            elif is_tube is False:
                emitter.UpdateCharge(dt)


def advance(ships, dt: float) -> None:
    """Step every awake weapon of every ship, in today's order, and put each
    to sleep after its step if it is at rest.

    The walk finds each next awake index by value (bisect past the last one
    stepped), not from a copy of the list, so a weapon woken DURING this walk
    -- its update posts an event, and the handlers run synchronously -- is
    stepped this tick if its turn has not come yet and from the next tick if
    it has. That is exactly when the per-tick model first steps it with the
    write visible (spec §6.3 "Ordering within a tick")."""
    audit = passive_state.audit_enabled()
    for ship in ships:
        d = getattr(ship, "__dict__", None)
        registry = d.get("_passive_weapons") if d is not None else None
        if registry is None:
            registry = _build(ship)
            if registry is None:
                step_every_weapon(ship, dt)
                continue
        entries = registry.entries
        awake = registry.awake
        last = -1
        while True:
            pos = bisect_right(awake, last)
            if pos == len(awake):
                break
            last = index = awake[pos]
            weapon, is_tube = entries[index]
            if is_tube:
                weapon.UpdateReload(dt)
            else:
                weapon.UpdateCharge(dt)
            if weapon._passive_at_rest():
                passive_state.put_to_sleep(weapon)
        if audit:
            for weapon, is_tube in entries:
                if passive_state.is_asleep(weapon):
                    update = weapon.UpdateReload if is_tube else weapon.UpdateCharge
                    passive_state.audit_step(weapon, lambda: update(dt))


def on_sleep(weapon) -> None:
    """passive_state.put_to_sleep's hook: drop the weapon from the awake list."""
    registry, index = weapon.__dict__["_passive_slot"]
    awake = registry.awake
    pos = bisect_left(awake, index)
    if pos < len(awake) and awake[pos] == index:
        del awake[pos]


def on_wake(weapon) -> None:
    """passive_state.wake's hook: back into the awake list, if the registry it
    slept in is still its ship's current one. A stale registry is never walked
    again; its rebuild starts every weapon awake."""
    slot = weapon.__dict__.get("_passive_slot")
    if slot is None:
        return
    registry, index = slot
    if registry.live:
        insort(registry.awake, index)
