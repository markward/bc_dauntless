"""Foundation's bridge definitions: BridgeDef, bridgeList and the officer
locations a bridge pack declares.

A bridge pack ships a bridge config script (scripts/Bridge/<name>.py, the
shape of stock GalaxyBridge.py) and registers it from Custom/Autoload:

    Foundation.BridgeDef('Defiant', 'defiantbridge', dict = {
        'modes': [Foundation.MutatorDef.Stock],
        'locations': {'DFHelm': ['data/animations/DF_stand_h_m.nif',
                                 'DF_stand_h_m'], ...},
        ...})

`locations` is what the pack's officers need: BC's own officer placement
(Bridge/Characters/CommonAnimations.SetPosition) knows only the stock
bridges' location names. Foundation consulted the CURRENT bridge's
BridgeDef first; engine/bridge_positions.py does that for us.

Names and behaviour from Foundation's interface as mods call it (its
Registry, MutatorElementDef and BridgeDef); spec
docs/superpowers/specs/2026-11-11-foundation-bridge-starbase-defs-design.md.
"""
from __future__ import annotations

import sys


class Registry:
    """Foundation's Registry: objects by name, plus the order they arrived.

    `_keyList` (name -> object) and `_arrayList` (names, in order) are read
    directly by real plugins, so they are surface, not internals."""

    def __init__(self):
        self._keyList = {}
        self._arrayList = []

    def Register(self, obj, name):
        """Store `obj` under `name`; its index in the order (unchanged when
        `name` was registered before)."""
        self._keyList[name] = obj
        if name in self._arrayList:
            return self._arrayList.index(name)
        self._arrayList.append(name)
        return len(self._arrayList) - 1

    def Remove(self, what):
        if what in self._keyList:
            if what in self._arrayList:
                self._arrayList.remove(what)
            del self._keyList[what]

    def __len__(self):
        return len(self._arrayList)

    def __getitem__(self, i):
        if isinstance(i, int):
            return self._keyList[self._arrayList[i]]
        return self._keyList[i]

    def __contains__(self, key):
        return key in self._keyList

    def has_key(self, key):
        return key in self._keyList

    def GetName(self, i):
        return self._keyList.get(i)

    def clear(self):
        self._keyList.clear()
        del self._arrayList[:]


class MutatorElementDef:
    """Foundation's base for anything a mutator (mod mode) owns. Dauntless
    has no mutator menu -- every installed mod is on -- so this records the
    element on its modes and nothing more."""

    def __init__(self, name, dict=None):
        self.name = name
        from engine.foundation.mutator import MutatorDef
        modes = [MutatorDef.QuickBattle]
        if dict and "modes" in dict:
            modes = dict["modes"]
        for mode in modes:
            self.AddToMutator(mode)

    def CheckForErrors(self):
        return None

    def AddToMutator(self, toMode):
        elements = getattr(toMode, "elements", None)
        if elements is not None:
            elements.append(self)


bridgeList = Registry()

# BridgeDef dict keys other plugins read in BC (bridge lighting maps, bridge
# sounds, loading screens). Stored on the definition; not used by Dauntless.
_USED_KEYS = frozenset({"modes", "locations"})
_ignored: set = set()
_noted_errors: set = set()


class BridgeDef(MutatorElementDef):
    """Foundation's `BridgeDef(name, bridgeString, dict)`.

    `bridgeString` is the bridge config script's module name under Bridge/
    (what LoadBridge.Load takes). Registered under both names, as Foundation
    does: by display name in order, and by config script in `_keyList`."""

    def __init__(self, name, bridgeString, dict=None):
        dict = dict or {}
        self.bridgeString = bridgeString
        self.num = bridgeList.Register(self, name)
        bridgeList._keyList[bridgeString] = self
        self.locations = dict.get("locations")
        self.dict = dict
        _ignored.update(k for k in dict if k not in _USED_KEYS)
        MutatorElementDef.__init__(self, name, dict)

    def AddToMutator(self, toMode):
        registry = getattr(toMode, "bridgeList", None)
        if registry is not None:
            registry.Register(self, self.name)
        MutatorElementDef.AddToMutator(self, toMode)

    def SetLocation(self, locationName, kAM, pSequence, pAnimNode,
                    pCharacter=None):
        """Place an officer at `locationName` if this bridge declares it:
        load the location's animation, append its TGAnimPosition, run its
        extra statements. 1 when handled, None when not.

        Extra statements (`'pCharacter.SetHidden(1)'` on the lift locations)
        are Python 1.5 source run with `pCharacter` bound. Foundation exec'd
        them where no `pCharacter` existed, so the NameError was swallowed
        and the officer stayed visible; BC's own lift locations hide the
        officer, which is what the statement says. A failing statement is
        reported once and the officer is still placed."""
        if not self.locations or locationName not in self.locations:
            return None
        loc = self.locations[locationName]
        import App
        kAM.LoadAnimation(loc[0], loc[1])
        pSequence.AppendAction(App.TGAnimPosition_Create(pAnimNode, loc[1]))
        for statement in loc[2:]:
            _run_extra(self, locationName, statement, {
                "App": App, "self": self, "locationName": locationName,
                "kAM": kAM, "pSequence": pSequence, "pAnimNode": pAnimNode,
                "pCharacter": pCharacter, "loc": loc})
        return 1


def _run_extra(definition, location, statement, namespace):
    from engine.py15.source import fix_source
    try:
        exec(compile(fix_source(str(statement)), "<BridgeDef %s %s>"
                     % (definition.bridgeString, location), "exec"), namespace)
    except Exception as exc:
        key = (definition.bridgeString, location, str(statement))
        if key not in _noted_errors:
            _noted_errors.add(key)
            print("[foundation] bridge %s location %s: %r failed: %s: %s"
                  % (definition.bridgeString, location, statement,
                     type(exc).__name__, exc), file=sys.stderr)


def by_config_script(script):
    """The BridgeDef registered for bridge config script `script`, or None.
    Case-folded, like the mod index (authors spell 'defiantbridge' and
    'DefiantBridge' interchangeably)."""
    if not script:
        return None
    found = bridgeList._keyList.get(script)
    if isinstance(found, BridgeDef) and found.bridgeString == script:
        return found
    folded = str(script).lower()
    for d in bridgeList._keyList.values():
        if isinstance(d, BridgeDef) and str(d.bridgeString).lower() == folded:
            return d
    return None


def _current_config():
    """The config script of the bridge the "bridge" set has loaded, or None.
    LoadBridge.Load stores it with SetConfig after building the bridge."""
    try:
        import App
        bridge_set = App.g_kSetManager.GetSet("bridge")
        return bridge_set.GetConfig() if bridge_set is not None else None
    except Exception:
        return None


def current_bridge():
    """Foundation.pCurrentBridge: the loaded bridge's BridgeDef, or None
    (a stock bridge no pack registered, or no bridge yet)."""
    return by_config_script(_current_config())


def BridgeSetLocation(locationName, kAM, pSequence, pAnimNode, pCharacter=None):
    """Foundation.BridgeSetLocation: let the current bridge place an officer."""
    current = current_bridge()
    if current is None:
        return None
    return current.SetLocation(locationName, kAM, pSequence, pAnimNode,
                               pCharacter=pCharacter)


def ignored_settings() -> list:
    """BridgeDef dict keys some pack set that Dauntless does not use."""
    return sorted(_ignored)


def reset():
    bridgeList.clear()
    _ignored.clear()
    _noted_errors.clear()
    from engine.foundation.mutator import MutatorDef
    for mode in (MutatorDef.Stock, MutatorDef.StockSounds,
                 MutatorDef.StockShips, MutatorDef.QuickBattle):
        del mode.elements[:]
        mode.bridgeList.clear()
