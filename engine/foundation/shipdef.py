"""Foundation's ship-definition objects.

Surface recovered from the call sites of real mods, not from Foundation's
source -- see docs/engine/foundation-api-surface.md for why, and
docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md for
which names and how they were measured.
"""
from __future__ import annotations

import contextlib

# Attributes a ship definition is known to carry. Anything else a mod sets
# is recorded in `unknown_attributes` rather than rejected: our corpus is
# two mods, and a third will set something neither of them does.
_KNOWN = frozenset({
    "race", "abbrev", "species", "name", "iconName", "shipFile", "desc",
    "SubMenu", "SubSubMenu", "hasTGLName", "hasTGLDesc", "dTechs",
    "friendlyDetails", "enemyDetails", "menuGroup", "playerMenuGroup",
    "dauntless",
})


_ALL_DEFINITIONS: list = []

# (mod_name, folded index key) of the Custom/ plugin script currently being
# run by engine.foundation.loader, else None. Copied into each definition's
# `_origin` so the ship catalog knows WHICH mod declared it -- the metadata
# gate writes its answers into that mod (spec 2026-10-01 ship metadata §2.2).
_CURRENT_ORIGIN = None


@contextlib.contextmanager
def plugin_origin(mod_name, key):
    global _CURRENT_ORIGIN
    previous = _CURRENT_ORIGIN
    _CURRENT_ORIGIN = (mod_name, key)
    try:
        yield
    finally:
        _CURRENT_ORIGIN = previous


def all_definitions() -> list:
    return list(_ALL_DEFINITIONS)


def icon_name_for_script(script):
    """The authored `iconName` of the ShipDef whose `shipFile` is `script`.

    `script` is what `ObjectClass.GetScript()` returns -- the dotted module
    `loadspacehelper.CreateShip` stores via `pShip.SetScript("ships." +
    pcScript)` -- so only the last segment is compared.

    This exists because a mod ship's SPECIES is not its artwork. Mods
    routinely reuse a stock species id (the LC Intrepid's hardpoint calls
    `SetSpecies(103)`, which is Akira) since species drives faction/AI
    behaviour and networking; `iconName` is the separate, authored icon,
    and the pack ships the matching TGA. See `engine/ui/species_icons.py`.

    Matching is case-insensitive: mod authors spell the module and
    `shipFile` inconsistently, and the LC pack itself declares iconName
    'LCintrepid' against a file named LCIntrepid.tga.
    """
    if not script:
        return None
    leaf = str(script).rsplit(".", 1)[-1].lower()
    if not leaf:
        return None
    for definition in _ALL_DEFINITIONS:
        ship_file = getattr(definition, "shipFile", None)
        if ship_file and str(ship_file).lower() == leaf:
            icon = getattr(definition, "iconName", None)
            if icon:
                return str(icon)
    return None


class ShipDefinition:
    """One registered ship. Attribute-set is how mods configure it."""

    def __init__(self, race, abbrev, species, details=None, dict=None, *,
                 _listed=True):
        # `dict` shadows the builtin deliberately: Foundation's own keyword
        # is spelled that way and mods pass it positionally or by name.
        object.__setattr__(self, "unknown_attributes", {})
        # Every definition ever built, so describe() can report declared
        # techs without the caller having to hand them over. Registration
        # into ShipDef is a mod's choice; existing is not. The one exception
        # is _listed=False: engine/foundation/shipdef_overrides.py's STOCK
        # definitions, which carry metadata only and must not change what
        # all_definitions()'s readers (bridge_selection, icon_name_for_script,
        # describe) see.
        if _listed:
            _ALL_DEFINITIONS.append(self)
        self._origin = _CURRENT_ORIGIN
        self.race = race
        self.abbrev = abbrev
        self.species = species
        details = details or {}
        self.name = details.get("name", abbrev)
        self.iconName = details.get("iconName", abbrev)
        self.shipFile = details.get("shipFile", abbrev)
        self.desc = ""
        self.SubMenu = None
        self.SubSubMenu = None
        self.hasTGLName = 0
        self.hasTGLDesc = 0
        self.dTechs = {}
        self.menuGroup = None
        self.playerMenuGroup = None
        # Generated scripts subscript index 2 unconditionally.
        self.friendlyDetails = [None, None, None]
        self.enemyDetails = [None, None, None]
        self.modes = (dict or {}).get("modes", [])

    def __setattr__(self, key, value):
        if key not in _KNOWN and not key.startswith("_") \
                and key not in ("modes", "unknown_attributes"):
            self.unknown_attributes[key] = value
        object.__setattr__(self, key, value)

    def RegisterQBShipMenu(self, group=None, **kw):
        # **kw so an omitted qb stays omitted and reaches register()'s own
        # _UNSET default; passing qb=None explicitly must mean "no module".
        from engine.foundation import quickbattle
        self.menuGroup = group
        return quickbattle.register(self, group, player=False, **kw)

    def RegisterQBPlayerShipMenu(self, group=None, **kw):
        from engine.foundation import quickbattle
        self.playerMenuGroup = group
        return quickbattle.register(self, group, player=True, **kw)


class _ShipDefNamespace:
    """`Foundation.ShipDef` -- mods assign onto it and read __dict__ back."""


class ShipList:
    """Dict-like, with the `_keyList` generated scripts reach into.

    Every Bridge Commander Universal Tool script ends with
    `if Foundation.shipList._keyList.has_key(longName):`, so _keyList is
    required surface rather than an implementation detail.
    """

    def __init__(self):
        self._items = {}
        self._keyList = self

    def has_key(self, k):
        return k in self._items

    def __contains__(self, k):
        return k in self._items

    def __getitem__(self, k):
        return self._items[k]

    def __setitem__(self, k, v):
        self._items[k] = v

    def keys(self):
        return list(self._items.keys())

    def __len__(self):
        return len(self._items)
