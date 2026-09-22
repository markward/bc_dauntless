"""The system-map data format and its JSON I/O.

A map describes ONE star system: its bodies (sun, planets, moons) at positions
in system coordinates, and its regions -- the original BC sets -- each anchored
at a position in that same space.

Body IDENTITY (name, radius, position, what it orbits) is deliberately held
apart from APPEARANCE. Today every appearance is a BC NIF; a procedurally
generated body later is a different Appearance on an unchanged Body, so nothing
but the renderer and one field has to move.

Files live beside this module in maps/, like engine/appc/sector_model.json.
The directory is computed per call, never captured at import: engine/paths.py
is re-configurable at runtime and module-level path constants go stale.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Appearance:
    kind: str = "nif"
    model: str = ""


@dataclass
class Body:
    name: str
    display_name: str
    radius_gu: float
    position_gu: tuple
    orbits: str | None = None
    appearance: Appearance = field(default_factory=Appearance)
    owner_region: str | None = None


@dataclass
class Region:
    set_name: str
    anchor_gu: tuple
    radius_gu: float
    body_names: list = field(default_factory=list)


@dataclass
class SystemMap:
    system: str
    bodies: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    generated: dict = field(default_factory=dict)

    def body(self, name: str):
        for b in self.bodies:
            if b.name == name:
                return b
        return None

    def region(self, set_name: str):
        for r in self.regions:
            if r.set_name == set_name:
                return r
        return None


def to_json(m: SystemMap) -> str:
    return json.dumps(asdict(m), indent=2, sort_keys=False) + "\n"


def from_json(text: str) -> SystemMap:
    raw = json.loads(text)
    bodies = [
        Body(
            name=b["name"],
            display_name=b["display_name"],
            radius_gu=float(b["radius_gu"]),
            position_gu=tuple(b["position_gu"]),
            orbits=b.get("orbits"),
            appearance=Appearance(**b.get("appearance", {})),
            owner_region=b.get("owner_region"),
        )
        for b in raw.get("bodies", [])
    ]
    regions = [
        Region(
            set_name=r["set_name"],
            anchor_gu=tuple(r["anchor_gu"]),
            radius_gu=float(r["radius_gu"]),
            body_names=list(r.get("body_names", [])),
        )
        for r in raw.get("regions", [])
    ]
    return SystemMap(
        system=raw["system"],
        bodies=bodies,
        regions=regions,
        overrides=raw.get("overrides", {}),
        generated=raw.get("generated", {}),
    )


def map_dir() -> Path:
    """Where checked-in system maps live. Computed per call, never cached."""
    return Path(__file__).parent / "maps"


def load(system: str) -> SystemMap:
    path = map_dir() / f"{system.lower()}.json"
    return from_json(path.read_text(encoding="utf-8"))


def save(m: SystemMap) -> Path:
    d = map_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{m.system.lower()}.json"
    path.write_text(to_json(m), encoding="utf-8")
    return path


def available() -> list:
    d = map_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
