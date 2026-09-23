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
    star_class: str = ""
    color: tuple | None = None


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
    nebula: dict | None = None


@dataclass
class Volume:
    shape: str                      # "sphere" | "lobe"
    geometry: dict = field(default_factory=dict)
    profile: str = ""               # "debris" | "nebula" | "mist"
    params: dict = field(default_factory=dict)
    origin_region: str | None = None


@dataclass
class Cloud:
    name: str
    display_name: str
    kind: str                       # "debris_shell" | "nebula_field"
    color: tuple = (0.0, 0.0, 0.0)
    volumes: list = field(default_factory=list)
    regions: list = field(default_factory=list)


@dataclass
class SystemMap:
    system: str
    bodies: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    generated: dict = field(default_factory=dict)
    clouds: list = field(default_factory=list)

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

    def cloud(self, name: str):
        for c in self.clouds:
            if c.name == name:
                return c
        return None


def to_json(m: SystemMap) -> str:
    return json.dumps(asdict(m), indent=2, sort_keys=False) + "\n"


def _appearance_from_json(raw: dict) -> Appearance:
    kwargs = dict(raw)
    if kwargs.get("color") is not None:
        kwargs["color"] = tuple(kwargs["color"])
    return Appearance(**kwargs)


def _nebula_from_json(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    out = dict(raw)
    out["color"] = tuple(raw["color"])
    out["spheres"] = [tuple(sphere) for sphere in raw.get("spheres", [])]
    return out


def _volume_from_json(raw: dict) -> Volume:
    return Volume(
        shape=raw["shape"],
        geometry=dict(raw.get("geometry", {})),
        profile=raw.get("profile", ""),
        params=dict(raw.get("params", {})),
        origin_region=raw.get("origin_region"),
    )


def _cloud_from_json(raw: dict) -> Cloud:
    return Cloud(
        name=raw["name"],
        display_name=raw["display_name"],
        kind=raw["kind"],
        color=tuple(raw.get("color", (0.0, 0.0, 0.0))),
        volumes=[_volume_from_json(v) for v in raw.get("volumes", [])],
        regions=list(raw.get("regions", [])),
    )


def from_json(text: str) -> SystemMap:
    raw = json.loads(text)
    bodies = [
        Body(
            name=b["name"],
            display_name=b["display_name"],
            radius_gu=float(b["radius_gu"]),
            position_gu=tuple(b["position_gu"]),
            orbits=b.get("orbits"),
            appearance=_appearance_from_json(b.get("appearance", {})),
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
            nebula=_nebula_from_json(r.get("nebula")),
        )
        for r in raw.get("regions", [])
    ]
    clouds = [_cloud_from_json(c) for c in raw.get("clouds", [])]
    return SystemMap(
        system=raw["system"],
        bodies=bodies,
        regions=regions,
        overrides=raw.get("overrides", {}),
        generated=raw.get("generated", {}),
        clouds=clouds,
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
