"""Static guard: no engine class overrides a method K2 stands in for unless
the kernel ports that override (native combat phase 2, Task 6; controller
Ruling C2).

The K2 driver (engine/appc/native_combat.py, `_k2_flag`) flags a class only
when one of its role's names resolves to a method from OUTSIDE the engine
package, or to something other than what it resolved to when K2 first saw
the class. An engine class that overrides a stood-in method (a new
`ShipClass.GetScale`, a `Planet.GetRadius`) is therefore trusted: the
kernel computes the stock role's answer from the mirror, and nothing at run
time would notice the engine's own override. This guard closes that hole
statically.

For every subclass of ObjectClass and ShipSubsystem defined in `engine/`
(PhaserBank, PhaserSystem, ShieldSubsystem and CloakingSubsystem are
ShipSubsystems), every name its role stands in for (the role lists of
native/src/combat/include/dauntless/combat/k2_beams.h, "WHAT THE DRIVER
CHECKS BEFORE begin", written out again below and checked against the
header) must resolve to the stock role class's own definition, or to an
entry of ALLOWED, which says why the kernel is still right. A new override
fails here until its port (or its unreachability) is argued in ALLOWED.
"""
import importlib
import pathlib
import pkgutil
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HEADER = (ROOT / "native" / "src" / "combat" / "include" / "dauntless"
          / "combat" / "k2_beams.h")

SUBSYSTEM_NAMES = ("GetWorldLocation", "GetPosition", "_climb_to_ship")

# (module, role stock class, the names it stands in for besides
# SUBSYSTEM_NAMES, which every SUBSYSTEM role -- the first five -- also
# watches). In isinstance order: a class takes the FIRST role whose stock
# class it subclasses (a bank is a WeaponSystem, a ShipClass an ObjectClass).
ROLES = (
    ("engine.appc.weapon_subsystems", "PhaserBank", (
        "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
        "_strip_emit_position", "_emitter_world_position", "GetLength",
        "GetDirection", "GetUp", "GetArcWidthAngles", "GetArcHeightAngles",
        "IsDisabled", "IsDestroyed", "GetMaxDamage", "GetMaxDamageDistance",
        "GetDamageRadiusFactor")),
    ("engine.appc.weapon_subsystems", "PhaserSystem", (
        "GetNumWeapons", "GetWeapon", "GetNumChildSubsystems",
        "GetChildSubsystem", "IsOn", "IsDisabled", "IsDestroyed",
        "GetPowerLevel", "PP_LOW")),
    ("engine.appc.subsystems", "ShieldSubsystem", (
        "HasShields", "IsOn", "IsDisabled", "IsDestroyed")),
    ("engine.appc.subsystems", "CloakingSubsystem", (
        "IsCloaking", "IsDecloaking")),
    ("engine.appc.subsystems", "ShipSubsystem", ()),
    ("engine.appc.ships", "ShipClass", (
        "IsDead", "GetWorldLocation", "GetWorldRotation", "GetContainingSet",
        "GetScale", "GetRadius", "GetBaseRadius", "GetShields",
        "GetPhaserSystem",
        "GetTargetSubsystem", "is_using_target_offset", "GetTargetOffsetTG",
        "GetCloakingSubsystem")),
    ("engine.appc.objects", "ObjectClass", (
        "IsDead", "GetWorldLocation", "GetWorldRotation", "GetContainingSet",
        "GetScale", "GetRadius", "GetBaseRadius", "GetShields")),
)

# "<defining module>.<defining class>.<name>" -> why the kernel's stock
# answer is still the right one for every class that resolves the name to
# this definition.
ALLOWED = {
    "engine.appc.objects.DamageableObject.IsDead":
        "ported: the mirror's per-object has_real_is_dead flag "
        "(implements(obj, 'IsDead')) makes the kernel read the row's "
        "`_dead` exactly as DamageableObject.IsDead does, and ASK is_dead "
        "for a target without it",
    "engine.appc.ai.ProximityCheck.GetRadius":
        "unreachable: GetRadius is read only for a bank's TARGET (the sphere "
        "tier's world_radius). A ProximityCheck has no real IsDead "
        "(has_real_is_dead 0), so the kernel ASKs is_dead, the stub reads "
        "dead and the bank stops before any trace; a ProximityCheck is never "
        "a ship, a bank, a system or a locked subsystem",
}


def _import_engine():
    """Import every engine.appc / engine.rocks module, so every engine
    class exists to be enumerated. A module that fails to import would hide
    its classes from the guard: the failures are asserted empty."""
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


def _stock(module, name):
    return getattr(importlib.import_module(module), name)


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


def _header_roles():
    """{stock class name: names} as the k2_beams.h comment lists them."""
    text = HEADER.read_text()
    start = text.index("a STOCK CLASS resolves")
    end = text.index("- any class with a row", start)
    block = " ".join(line.strip().lstrip("/").strip()
                     for line in text[start:end].splitlines())
    common = re.search(r"also watches the subsystem names ([^;]*);",
                       block).group(1)
    common = tuple(n.strip() for n in common.split(","))
    body = block[block.index("):") + 2:]
    roles = {}
    for entry in body.split(";"):
        if ":" not in entry:
            continue
        cls, names = entry.split(":", 1)
        names = names.strip()
        roles[cls.strip()] = (() if names == "the subsystem names"
                              else tuple(n.strip() for n in names.split(",")))
    return common, roles


def test_role_table_is_the_headers():
    """The table above IS the header's list (both written out by hand, so a
    name added to one and not the other fails here)."""
    common, roles = _header_roles()
    assert common == SUBSYSTEM_NAMES
    assert roles == {cls: names for _m, cls, names in ROLES}


def test_role_table_is_the_drivers():
    """... and the driver's (native_combat._K2_ROLES), so the guard checks
    what the driver snapshots."""
    from engine.appc import native_combat as nc
    driver = {cls: tuple(names) for _r, _m, cls, names in nc._K2_ROLES}
    assert driver == {cls: _names(i) for i, (_m, cls, _n) in enumerate(ROLES)}


SUBSYSTEM_ROLES = 5


def _names(i):
    """Every name role `i` stands in for."""
    names = ROLES[i][2]
    return SUBSYSTEM_NAMES + names if i < SUBSYSTEM_ROLES else names


def _overrides():
    """[(class, name, defining owner)] for every engine class whose role's
    name resolves to something other than the stock role class's."""
    _import_engine()
    from engine.appc.objects import ObjectClass
    from engine.appc.subsystems import ShipSubsystem
    roles = [(_stock(m, c), _names(i)) for i, (m, c, _n) in enumerate(ROLES)]
    found = []
    for base in (ObjectClass, ShipSubsystem):
        for cls in _all_subclasses(base):
            if not cls.__module__.startswith("engine"):
                continue            # a test's own subclass
            stock, names = next((s, n) for s, n in roles
                                if issubclass(cls, s))
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
        "an engine class overrides a method K2 computes from the mirror; port "
        "the override in the kernel (or prove it unreachable) and add it to "
        "ALLOWED with the reason:\n  " + "\n  ".join(unexplained))


def test_every_allowance_is_still_needed():
    """An ALLOWED entry nothing resolves to any more is stale: remove it."""
    used = {owner for _cls, _name, owner in _overrides()}
    assert set(ALLOWED) <= used, sorted(set(ALLOWED) - used)
