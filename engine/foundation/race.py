# engine/foundation/race.py
"""ShipDef.race: the factory's short label, plus Foundation's long `.name`
(spec 2026-10-16 §8.6). Foundation abbreviates three races (Fed, Card, Dom);
every other label is already its long name."""
from __future__ import annotations

_LONG = {"Fed": "Federation", "Card": "Cardassian", "Dom": "Dominion"}


class Race(str):
    @property
    def name(self) -> str:
        return _LONG.get(str(self), str(self))

    @property
    def abbrev(self) -> str:
        return str(self)


# Foundation's nine RaceDef instances (Foundation.Federation, ...), by the
# abbreviation Foundation gives each. Mods set `dict['race'] = Foundation.X`.
RACES = {long: Race(abbrev) for long, abbrev in (
    ("Federation", "Fed"), ("Cardassian", "Card"), ("Klingon", "Klingon"),
    ("Romulan", "Romulan"), ("Ferengi", "Ferengi"), ("Kessok", "Kessok"),
    ("Dominion", "Dom"), ("Breen", "Breen"), ("Borg", "Borg"))}
