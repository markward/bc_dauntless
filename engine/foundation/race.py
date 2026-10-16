# engine/foundation/race.py
"""ShipDef.race: the factory's short label, plus Foundation's long `.name`
(spec 2026-10-16 §8.6). Only "Fed" is evidenced in the corpus (FedShipDef);
every other synthesised race label is already its long name."""
from __future__ import annotations

_LONG = {"Fed": "Federation"}


class Race(str):
    @property
    def name(self) -> str:
        return _LONG.get(str(self), str(self))
