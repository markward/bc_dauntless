"""Static guard: no engine class overrides a method K3 stands in for unless the
kernel ports that override (native combat phase 3, Task 5; spec
docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md §7; the K2
twin is test_native_k2_override_guard.py, controller Ruling C2).

At run time no patch or override sends the step to Python (spec Part A,
phase 6 A3): the kernel computes the stock answer from the mirror. So an
ENGINE class overriding a stood-in method would go unnoticed. This guard
closes that hole statically, for every class the kernel reads natively:

- SHIPS: the step scan admits only ShipClass rows (step_scan.h, `not_ship`),
  and a torpedo's target or source outside the scan is an ASK guide (Python's
  own _guide), so every engine ShipClass subclass must resolve the ship
  names below to ShipClass's own definition.
- TORPEDOES: every engine Torpedo subclass (and Torpedo itself) must resolve
  the torpedo names to ObjectClass's definition: the kernel reads and writes
  the position in the TransformStore and reads the set from the row.

A new override fails here until its port (or its unreachability) is argued
in ALLOWED.
"""
import importlib
import pkgutil

import pytest

#: Every ship method the K3 kernel computes from the mirror: the ship cache
#: (IsDead, GetWorldLocation, GetRadius, GetScale via bubble_bound_radius,
#: GetContainingSet via frames.containing_set), the guide (the target's
#: IsDead, GetWorldLocation, GetVelocityTG) and the narrow test
#: (shields_block: GetShields, GetCloakingSubsystem).
SHIP_NAMES = ("IsDead", "GetWorldLocation", "GetContainingSet", "GetRadius",
              "GetScale", "GetVelocityTG", "GetShields",
              "GetCloakingSubsystem")
#: The torpedo methods: the position's store read and write, and the set.
TORPEDO_NAMES = ("GetTranslate", "SetTranslateXYZ", "GetContainingSet")

# "<defining module>.<defining class>.<name>" -> why the kernel's stock
# answer is still right for every class resolving the name to it.
ALLOWED: dict = {}


def _import_engine():
    """Import every engine.appc / engine.rocks module, so every engine class
    exists to be enumerated (a failing import would hide its classes)."""
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
    out, todo = {base}, [base]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in out:
                out.add(sub)
                todo.append(sub)
    return out


def _owner(cls, name):
    for klass in cls.__mro__:
        if name in vars(klass):
            return "%s.%s.%s" % (klass.__module__, klass.__qualname__, name)
    return None


def _overrides():
    """[(class, name, owner)] for every engine ship or torpedo class whose
    stood-in name resolves to something other than the stock one."""
    _import_engine()
    from engine.appc.objects import ObjectClass
    from engine.appc.projectiles import Torpedo
    from engine.appc.ships import ShipClass
    found = []
    for base, stock, names in ((ShipClass, ShipClass, SHIP_NAMES),
                               (Torpedo, ObjectClass, TORPEDO_NAMES)):
        for cls in _all_subclasses(base):
            if not cls.__module__.startswith("engine"):
                continue            # a test's own subclass
            for name in names:
                if getattr(cls, name, None) is not getattr(stock, name, None):
                    found.append((cls, name, _owner(cls, name)))
    return found


def test_no_engine_class_overrides_a_stood_in_method():
    unexplained = sorted(
        "%s.%s: %s resolves to %s" % (cls.__module__, cls.__qualname__,
                                      name, owner)
        for cls, name, owner in _overrides() if owner not in ALLOWED)
    assert unexplained == [], (
        "an engine class overrides a method K3 computes from the mirror; port "
        "the override in the kernel (or prove it unreachable) and add it to "
        "ALLOWED with the reason:\n  " + "\n  ".join(unexplained))


def test_every_allowance_is_still_needed():
    used = {owner for _cls, _name, owner in _overrides()}
    assert set(ALLOWED) <= used, sorted(set(ALLOWED) - used)


def test_step_scan_admits_only_ships():
    """The premise of checking ShipClass subclasses only: an engine object
    that is not a ShipClass (a DamageableObject, here) in ships_list makes
    the step unrepresentable (`not_ship`), so K3 and K4 never read it."""
    try:
        import _dauntless_host as _h
    except ImportError:
        pytest.skip("native combat bindings not built")
    import engine.host_loop  # noqa: F401  (K2's class snapshot)
    from engine.appc import native_combat as nc
    from engine.appc.objects import DamageableObject
    nc.reset()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    try:
        assert nc.enabled()
        rock = DamageableObject()
        st = nc.step_scan([rock])
        assert not st.ok and st.reason == "not_ship", st.reason
        # ... and the native step state is emptied: nothing representable.
        assert not _h.combat_step_dump()["representable"]
    finally:
        nc.reset()
