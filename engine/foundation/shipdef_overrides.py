"""Dauntless metadata for BC's stock ships -- HAND-EDITED, reviewed.

One section per stock ship, written exactly like a Foundation Custom/Ships
script so a mod author can copy one as a template. Stock values change only
by editing this file (there is no in-game editor for stock metadata).
Mods declare the same `dauntless` dict on their own ShipDef; per key, a mod
wins over the section here (engine/ship_catalog, spec §3).

The definitions are UNLISTED (_listed=False): they are not in
shipdef.all_definitions(), not registered into QuickBattle's tables (BC's
already hold every stock ship) and not assigned onto Foundation.ShipDef.

Keep every dauntless literal Python 1.5-safe: 1/0, never True/False.
Era ids: ENT TOS MOV TNG DS9 PIC DISC, or 'all'. Roles: tactical auxiliary
station automated. variants[0] is the class default and never has a
'script'. Registries are BC's own ReplaceTexture(..., "ID") stems.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md §2.1, §7
"""
from engine.foundation.shipdef import ShipDefinition

_STOCK = []


def _stock(ship_id, title, species, iconName=None):
    d = ShipDefinition(species, ship_id, None,
                       {"name": title, "iconName": iconName or ship_id,
                        "shipFile": ship_id},
                       _listed=False)
    _STOCK.append(d)
    return d


def stock_definitions():
    return list(_STOCK)


# ---- Federation -------------------------------------------------------------

Akira = _stock("Akira", "Akira", "Federation")
Akira.dauntless = {
    'title': 'Akira', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Geronimo', 'registry': 'Geronimo'},
        {'name': 'USS Devore', 'registry': 'Devore'},
    ],
}

Ambassador = _stock("Ambassador", "Ambassador", "Federation")
Ambassador.dauntless = {
    'title': 'Ambassador', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Zhukov', 'registry': 'Zhukov'},
        {'name': 'USS Excalibur', 'registry': 'Excalibur'},
    ],
}

Galaxy = _stock("Galaxy", "Galaxy", "Federation")
Galaxy.dauntless = {
    'title': 'Galaxy', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Dauntless', 'registry': 'Dauntless'},
        {'name': 'USS San Francisco', 'registry': 'SanFrancisco'},
        {'name': 'USS Venture', 'registry': 'Venture'},
    ],
}

Nebula = _stock("Nebula", "Nebula", "Federation")
Nebula.dauntless = {
    'title': 'Nebula', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Berkeley', 'registry': 'Berkeley'},
        {'name': 'USS Prometheus', 'registry': 'Prometheus'},
        {'name': 'USS Khitomer', 'registry': 'Khitomer'},
        {'name': 'USS Nightingale', 'registry': 'Nightingale'},
    ],
}

Sovereign = _stock("Sovereign", "Sovereign", "Federation")
Sovereign.dauntless = {
    'title': 'Sovereign', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Sovereign', 'registry': 'Sovereign'},
        # A separate SDK script with its own hardpoints (spec D5).
        {'name': 'USS Enterprise', 'script': 'Enterprise', 'registry': 'Enterprise'},
    ],
}

Shuttle = _stock("Shuttle", "Shuttle", "Federation", iconName="FedShuttle")
Shuttle.dauntless = {
    'title': 'Shuttle', 'species': 'Federation', 'era': 'DS9',
    'role': 'auxiliary', 'playable': 1,
}

# SDK SpeciesToShip says Neutral; Dauntless says Federation (roadmap).
EscapePod = _stock("EscapePod", "Escape Pod", "Federation", iconName="LifeBoat")
EscapePod.dauntless = {
    'title': 'Escape Pod', 'species': 'Federation', 'era': 'DS9',
    'role': 'auxiliary', 'playable': 0,
}

FedStarbase = _stock("FedStarbase", "Fed Starbase", "Federation")
FedStarbase.dauntless = {
    'title': 'Fed Starbase', 'species': 'Federation', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

FedOutpost = _stock("FedOutpost", "Fed Outpost", "Federation")
FedOutpost.dauntless = {
    'title': 'Fed Outpost', 'species': 'Federation', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

SpaceFacility = _stock("SpaceFacility", "Space Facility", "Federation")
SpaceFacility.dauntless = {
    'title': 'Space Facility', 'species': 'Federation', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

DryDock = _stock("DryDock", "Dry Dock", "Federation")
DryDock.dauntless = {
    'title': 'Dry Dock', 'species': 'Federation', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

CommArray = _stock("CommArray", "Comm Array", "Federation")
CommArray.dauntless = {
    'title': 'Comm Array', 'species': 'Federation', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

Probe = _stock("Probe", "Probe", "Federation")
Probe.dauntless = {
    'title': 'Probe', 'species': 'Federation', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

Decoy = _stock("Decoy", "Decoy", "Federation", iconName="ProbeType2")
Decoy.dauntless = {
    'title': 'Decoy', 'species': 'Federation', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

# ---- Klingon ----------------------------------------------------------------

BirdOfPrey = _stock("BirdOfPrey", "Bird of Prey", "Klingon")
BirdOfPrey.dauntless = {
    'title': 'Bird of Prey', 'species': 'Klingon', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

Vorcha = _stock("Vorcha", "Vor'cha", "Klingon")
Vorcha.dauntless = {
    'title': "Vor'cha", 'species': 'Klingon', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

# ---- Romulan ----------------------------------------------------------------

Warbird = _stock("Warbird", "Warbird", "Romulan")
Warbird.dauntless = {
    'title': 'Warbird', 'species': 'Romulan', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

# ---- Cardassian -------------------------------------------------------------

Galor = _stock("Galor", "Galor", "Cardassian")
Galor.dauntless = {
    'title': 'Galor', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

Keldon = _stock("Keldon", "Keldon", "Cardassian")
Keldon.dauntless = {
    'title': 'Keldon', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

# Ships.tgl says "Card Hybrid"; ours is "Hybrid" (roadmap).
CardHybrid = _stock("CardHybrid", "Hybrid", "Cardassian", iconName="Hybrid")
CardHybrid.dauntless = {
    'title': 'Hybrid', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

CardFreighter = _stock("CardFreighter", "Card Freighter", "Cardassian")
CardFreighter.dauntless = {
    'title': 'Card Freighter', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'auxiliary', 'playable': 0,
}

CardStarbase = _stock("CardStarbase", "Card Starbase", "Cardassian")
CardStarbase.dauntless = {
    'title': 'Card Starbase', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

CardStation = _stock("CardStation", "Card Station", "Cardassian")
CardStation.dauntless = {
    'title': 'Card Station', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

CardOutpost = _stock("CardOutpost", "Card Outpost", "Cardassian")
CardOutpost.dauntless = {
    'title': 'Card Outpost', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'station', 'playable': 0,
}

CommLight = _stock("CommLight", "Comm Light", "Cardassian")
CommLight.dauntless = {
    'title': 'Comm Light', 'species': 'Cardassian', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

# ---- Ferengi ----------------------------------------------------------------

Marauder = _stock("Marauder", "Marauder", "Ferengi")
Marauder.dauntless = {
    'title': 'Marauder', 'species': 'Ferengi', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

# ---- Kessok -----------------------------------------------------------------

KessokLight = _stock("KessokLight", "Kessok Light", "Kessok")
KessokLight.dauntless = {
    'title': 'Kessok Light', 'species': 'Kessok', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

KessokHeavy = _stock("KessokHeavy", "Kessok Heavy", "Kessok")
KessokHeavy.dauntless = {
    'title': 'Kessok Heavy', 'species': 'Kessok', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
}

KessokMine = _stock("KessokMine", "Kessok Mine", "Kessok")
KessokMine.dauntless = {
    'title': 'Kessok Mine', 'species': 'Kessok', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

Sunbuster = _stock("Sunbuster", "Sun Buster", "Kessok")
Sunbuster.dauntless = {
    'title': 'Sun Buster', 'species': 'Kessok', 'era': 'DS9',
    'role': 'automated', 'playable': 0,
}

# ---- Civilian (SDK says Federation; Dauntless says Civilian -- roadmap) ------

Transport = _stock("Transport", "Transport", "Civilian")
Transport.dauntless = {
    'title': 'Transport', 'species': 'Civilian', 'era': 'DS9',
    'role': 'auxiliary', 'playable': 1,
}

Freighter = _stock("Freighter", "Freighter", "Civilian")
Freighter.dauntless = {
    'title': 'Freighter', 'species': 'Civilian', 'era': 'DS9',
    'role': 'auxiliary', 'playable': 0,
}

# ---- Neutral ----------------------------------------------------------------

# Role is a placeholder: none of the four fits a rock (roadmap appendix).
Asteroid = _stock("Asteroid", "Asteroid", "Neutral")
Asteroid.dauntless = {
    'title': 'Asteroid', 'species': 'Neutral', 'era': 'all',
    'role': 'automated', 'playable': 0,
}
