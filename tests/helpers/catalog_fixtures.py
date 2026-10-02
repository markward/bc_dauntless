"""Shared ShipDef builders for the ship-catalog tests (sub-project 3)."""
from engine import foundation, ship_catalog
from engine.foundation.shipdef import ShipDefinition, plugin_origin

FULL = {"title": "Galaxy", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}


def _stock_def(ship_id, **d):
    s = ShipDefinition("Federation", ship_id, None, {"shipFile": ship_id, "name": ship_id}, _listed=False)
    s.dauntless = dict(d)
    return s


def _mod_def(ship_file, mod="M", attr=None, dauntless=None, details=None, player=False):
    with plugin_origin(mod, "custom/ships/%s.py" % ship_file.lower()):
        d = ShipDefinition("Fed", ship_file, 103,
                           dict({"shipFile": ship_file, "name": "Mod " + ship_file}, **(details or {})))
    if dauntless is not None:
        d.dauntless = dauntless
    if player:
        d.RegisterQBPlayerShipMenu("Fed Ships", qb=None)
    else:
        d.RegisterQBShipMenu("Fed Ships", qb=None)
    if attr:
        setattr(foundation.ShipDef, attr, d)
    ship_catalog.invalidate()
    return d
