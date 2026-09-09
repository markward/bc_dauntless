"""Foundation's ship-definition objects.

Surface recovered from the call sites of real mods, not from Foundation's
source -- see docs/engine/foundation-api-surface.md for why, and
docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md for
which names and how they were measured.
"""
from __future__ import annotations

# Attributes a ship definition is known to carry. Anything else a mod sets
# is recorded in `unknown_attributes` rather than rejected: our corpus is
# two mods, and a third will set something neither of them does.
_KNOWN = frozenset({
    "race", "abbrev", "species", "name", "iconName", "shipFile", "desc",
    "SubMenu", "SubSubMenu", "hasTGLName", "hasTGLDesc", "dTechs",
    "friendlyDetails", "enemyDetails", "menuGroup", "playerMenuGroup",
})


_ALL_DEFINITIONS: list = []


def all_definitions() -> list:
    return list(_ALL_DEFINITIONS)


class ShipDefinition:
    """One registered ship. Attribute-set is how mods configure it."""

    def __init__(self, race, abbrev, species, details=None, dict=None):
        # `dict` shadows the builtin deliberately: Foundation's own keyword
        # is spelled that way and mods pass it positionally or by name.
        object.__setattr__(self, "unknown_attributes", {})
        # Every definition ever built, so describe() can report declared
        # techs without the caller having to hand them over. Registration
        # into ShipDef is a mod's choice; existing is not.
        _ALL_DEFINITIONS.append(self)
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
