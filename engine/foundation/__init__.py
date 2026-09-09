"""Foundation compatibility -- the surface real BC ship mods call.

Ours always wins over a mod-supplied Foundation.py: `Foundation.py` at the
project root is checked by _SDKFinder BEFORE the mod index, an ordering the
mod overlay chose deliberately so our own replacements cannot be overridden.

Spec: docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md
"""
from __future__ import annotations

import re

from engine.foundation.shipdef import ShipDefinition, ShipList, _ShipDefNamespace

ShipDef = _ShipDefNamespace()
shipList = ShipList()

_RACE_FACTORY = re.compile(r"^([A-Z][A-Za-z0-9]*)ShipDef$")
_synthesised: set = set()


def synthesised_races():
    """Race factories a mod asked for that we had not anticipated."""
    return set(_synthesised)


def __getattr__(attr):
    """Synthesise `<Race>ShipDef` on demand.

    Foundation has race variants we have never seen in a mod -- Klingon,
    Romulan, Cardassian and more. Hardcoding only the two our corpus uses
    would make an unseen one an AttributeError at import, taking the whole
    mod down for a name we could have handled. The race is only a label
    plus a default side/AI, so synthesising is safe.

    Deliberately narrow: anything not matching <Race>ShipDef still raises,
    so a genuine typo is not swallowed.
    """
    m = _RACE_FACTORY.match(attr)
    if not m:
        raise AttributeError(attr)
    race = m.group(1)
    _synthesised.add(attr)

    def factory(abbrev, species, details=None, dict=None):
        return ShipDefinition(race, abbrev, species, details, dict)

    factory.__name__ = attr
    return factory


def reset():
    """Drop all registered state. Tests only."""
    global ShipDef, shipList
    for k in [k for k in ShipDef.__dict__ if not k.startswith("_")]:
        delattr(ShipDef, k)
    shipList._items.clear()
    _synthesised.clear()
    # Definitions accumulate on construction, so this must be cleared too
    # or they leak between tests and inflate describe()'s tech list.
    from engine.foundation.shipdef import _ALL_DEFINITIONS
    _ALL_DEFINITIONS.clear()
