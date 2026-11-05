"""Static guard: no engine class outside weapon_subsystems overrides a method
K0 (charging / reloading) stands in for (spec Part A, phase 6 A3).

K0's run-time override guard (`_K0_METHODS` / `_K0_LEAF_METHODS` in
engine/appc/native_combat.py, recoverable from commit 614ce6059) was removed:
a patch of a method K0 stands in for is no longer obeyed (BC's per-tick
update was internal C++ no script could override). Nothing at run time would
notice an ENGINE class overriding one, so this guard closes that hole
statically, as the K2 / K3 twins do (test_native_k2_override_guard.py,
test_native_k3_override_guard.py).

For every engine subclass of a weapon-kind class, ShipClass or
TorpedoAmmoType defined outside engine.appc.weapon_subsystems, none of the
names below may appear in its own `vars`, unless ALLOWED argues why the
kernel's stock answer is still right.
"""
import importlib
import pkgutil

#: WSM §7(a) A6, every weapon role, plus the walk's own names.
WEAPON_NAMES = (
    "UpdateCharge", "UpdateReload", "_discharge_rate_per_second",
    "GetParentSubsystem", "IsOn", "GetNormalPowerPercentage",
    "GetPowerPercentage", "GetNormalPowerWanted", "GetConditionPercentage",
    "GetMaxCondition", "GetPowerLevel", "GetChargePercentage",
    "_passive_at_rest", "_ensure_slots", "ReloadTorpedo",
    "_reload_denied_by_ammo", "_parent_ammo", "GetCurrentAmmoType",
    "GetCurrentAmmoSlot", "GetAvailable", "_rounds_loaded_systemwide",
    "GetNumReady", "GetNumWeapons", "GetWeapon", "GetNumChildSubsystems",
    "GetChildSubsystem",
    # the leaves K0 logs the stop / reload event for
    "StopFiring", "_broadcast_reload")
SHIP_NAMES = ("GetPhaserSystem", "GetPulseWeaponSystem",
              "GetTractorBeamSystem", "GetTorpedoSystem")
AMMO_NAMES = ("GetAvailable",)

#: (module, stock class, names) of every role.
ROLES = tuple(("engine.appc.weapon_subsystems", c, WEAPON_NAMES) for c in (
    "PhaserBank", "PulseWeapon", "TractorBeam", "TorpedoTube",
    "PhaserSystem", "PulseWeaponSystem", "TractorBeamSystem",
    "TorpedoSystem")) + (
    ("engine.appc.ships", "ShipClass", SHIP_NAMES),
    ("engine.appc.weapon_subsystems", "TorpedoAmmoType", AMMO_NAMES))

#: "<module>.<class>.<name>" -> why the kernel's stock answer is still right.
ALLOWED: dict = {}


def _import_engine():
    import engine.appc
    import engine.rocks
    failures = []
    for pkg in (engine.appc, engine.rocks):
        for info in pkgutil.iter_modules(pkg.__path__):
            name = pkg.__name__ + "." + info.name
            try:
                importlib.import_module(name)
            except Exception as e:  # noqa: BLE001 - collected, asserted
                failures.append((name, repr(e)))
    assert failures == [], failures


def _all_subclasses(base):
    out, todo = set(), [base]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in out:
                out.add(sub)
                todo.append(sub)
    return out


def _overrides():
    _import_engine()
    found = {}
    for module, cls_name, names in ROLES:
        stock = getattr(importlib.import_module(module), cls_name)
        for cls in _all_subclasses(stock):
            if not cls.__module__.startswith("engine") \
                    or cls.__module__ == "engine.appc.weapon_subsystems":
                continue            # a test's own subclass, or a stock class
            for name in names:
                if name in vars(cls):
                    found["%s.%s.%s" % (cls.__module__, cls.__qualname__,
                                        name)] = cls
    return sorted(found)


def test_no_engine_class_overrides_a_k0_stood_in_method():
    unexplained = [o for o in _overrides() if o not in ALLOWED]
    assert unexplained == [], (
        "an engine class overrides a method K0 computes from the mirror; port "
        "the override in the kernel (or prove it unreachable) and add it to "
        "ALLOWED with the reason:\n  " + "\n  ".join(unexplained))


def test_every_allowance_is_still_needed():
    assert set(ALLOWED) <= set(_overrides()), sorted(
        set(ALLOWED) - set(_overrides()))
