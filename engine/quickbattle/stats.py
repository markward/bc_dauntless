"""Hull and shield totals for the scale bars, read from LOADED properties.

Runs BC's own loader sequence (loadspacehelper.py:88-91) into a scratch set:
ClearLocalTemplates -> reload the hardpoint module (our override pass fires in
the SDK loader here) -> LoadPropertySet. So the values are mod- and
override-aware, never parsed from hardpoint text. The primary hull is the FIRST
HullProperty (engine/appc/ships.py:1238). The manager's local templates are
snapshotted and restored in a finally: a live mission must never notice. Spec §5.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShipStats:
    hull: float
    shields: float


def probe(ship_file) -> Optional[ShipStats]:
    import App
    from engine.appc.properties import HullProperty, ShieldProperty, TGModelPropertySet
    mgr = App.g_kModelPropertyManager
    snapshot = dict(mgr._local)
    try:
        ship_mod = importlib.import_module("ships." + ship_file)
        hp_file = ship_mod.GetShipStats()["HardpointFile"]
        mgr.ClearLocalTemplates()
        hp_mod = importlib.reload(importlib.import_module("ships.Hardpoints." + hp_file))
        pset = TGModelPropertySet()
        hp_mod.LoadPropertySet(pset)
        props = [p for _n, p in pset._entries]
        hull = next((p for p in props if isinstance(p, HullProperty)), None)
        shield = next((p for p in props if isinstance(p, ShieldProperty)), None)
        if hull is None:
            return None
        total = sum(float(shield.GetMaxShields(f) or 0.0) for f in range(6)) if shield else 0.0
        return ShipStats(hull=float(hull.GetMaxCondition() or 0.0), shields=total)
    except Exception as e:                       # one bad ship costs only itself
        _log.info("quickbattle stats probe failed for %s: %s", ship_file, e)
        return None
    finally:
        mgr._local.clear()
        mgr._local.update(snapshot)


class StatsCache:
    def __init__(self):
        self._memo: dict = {}

    def reset(self) -> None:
        self._memo.clear()

    def get(self, ship_file):
        if ship_file not in self._memo:
            self._memo[ship_file] = probe(ship_file)
        return self._memo[ship_file]

    def maxima(self, entries):
        hull = shields = 0.0
        for ce in entries:
            if not ce.playable:
                continue
            st = self.get(ce.ship_id)
            if st is not None:
                hull, shields = max(hull, st.hull), max(shields, st.shields)
        return hull, shields
