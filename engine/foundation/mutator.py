# engine/foundation/mutator.py
"""Foundation's MutatorDef, inert and always on (spec 2026-10-16 §6.1).

Dauntless has no mutator menu: every installed mod is on. A mutator is a named
label mods hang definitions on ({'modes': [mode]}) and attach attributes to
(Foundation.MutatorDef.NanoFX = mode; mode.bBase = 1). Enable/Disable/
Activate/Deactivate are accepted and ignored, logged once each, so the many
Autoload scripts that open with `mode = Foundation.MutatorDef("My Mod")` load.

Names from call sites and Foundation's own interface; no Foundation code.
"""
from __future__ import annotations

import sys

_noted: set = set()


def _note(op: str) -> None:
    if op in _noted:
        return
    _noted.add(op)
    print("[foundation] MutatorDef.%s ignored: every installed mod is always on"
          % op, file=sys.stderr)


class MutatorDef:
    def __init__(self, name=None, dict=None):   # `dict` is Foundation's keyword
        self.name = name

    def IsEnabled(self):
        return 1

    def Enable(self):
        _note("Enable")

    def Disable(self):
        _note("Disable")

    def Activate(self):
        _note("Activate")

    def Deactivate(self):
        _note("Deactivate")


# Foundation's four standard instances.
MutatorDef.Stock = MutatorDef("Stock Systems")
MutatorDef.StockSounds = MutatorDef(None)
MutatorDef.StockShips = MutatorDef("Stock Ships")
MutatorDef.QuickBattle = MutatorDef("Extra Ships and Mods")
