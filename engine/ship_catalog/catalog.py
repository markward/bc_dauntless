"""Build the ship catalog from ShipDefs: stock first, then mods, per key.

Membership, merge and provenance follow spec §3; records and functions §4.
Memoised against the identity of mods.current() (the bridge_selection
pattern) and dropped by invalidate(). Entries are SNAPSHOTS: a ShipDef
mutated after the build is invisible until invalidate(). Never raises.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from engine import mods
from engine.ship_catalog.schema import parse_dauntless
from engine.ship_catalog.tables import ALL_ERAS, ERA_IDS


@dataclass(frozen=True)
class CatalogEntry:
    ship_id: str            # script stem, display spelling (stock's first)
    icon: str               # data/Icons/Ships/<icon>.tga stem
    source: str             # "stock" | "mod"
    origins: tuple          # ((mod_name, shipdef_attr | None), ...) load order
    title: Optional[str]
    species: Optional[str]
    era: Optional[tuple]    # (from_id, to_id) or ("all",)
    role: Optional[str]
    playable: Optional[bool]
    variants: tuple         # of schema.Variant; [0] is the class default
    missing: tuple          # mandatory keys absent or invalid, MANDATORY order
    errors: tuple           # readable, one per invalid value or variant
    raw_name: str           # ShipDef.name -- a suggestion source for the gate
    raw_race: Optional[str] # ShipDef.race -- a suggestion source for the gate

    @property
    def complete(self) -> bool:
        return not self.missing

    def in_eras(self, era_ids) -> bool:
        if self.era is None:
            return False
        if self.era == (ALL_ERAS,):
            return True
        lo, hi = ERA_IDS.index(self.era[0]), ERA_IDS.index(self.era[1])
        return any(e in ERA_IDS and lo <= ERA_IDS.index(e) <= hi
                   for e in era_ids)


@dataclass
class _Built:
    entries: list
    unresolved: list        # (ship_file, mod_name)
    shared: list            # (ship_id, [mod_name, ...]) -- mod-over-mod only
    stock_error: Optional[str]


_memo: dict = {"index": None, "built": None}


def invalidate() -> None:
    _memo["index"] = None
    _memo["built"] = None


def _built() -> _Built:
    index = mods.current()
    if _memo["built"] is None or _memo["index"] is not index:
        _memo["built"] = _build()
        _memo["index"] = index
    return _memo["built"]


def entries() -> list:
    return list(_built().entries)


def entry(ship_id) -> Optional[CatalogEntry]:
    key = str(ship_id).lower()
    for e in _built().entries:
        if e.ship_id.lower() == key:
            return e
    return None


def incomplete() -> list:
    return [e for e in _built().entries if not e.complete]


# ── build ──────────────────────────────────────────────────────────────────

def _stock_definitions() -> list:
    """Test seam: the stock ShipDefs (engine/foundation/shipdef_overrides.py)."""
    from engine.foundation import shipdef_overrides
    return shipdef_overrides.stock_definitions()


def _installed_scripts() -> set:
    """Folded stems of every ships/*.py, stock tree or mod overlay. Reuses
    bridge_selection's scanners so both features agree on 'installed'."""
    from engine import bridge_selection
    return (set(bridge_selection._stock_ship_stems())
            | set(bridge_selection._mod_ship_stems()))


def _on_qb_menu(d) -> bool:
    return (getattr(d, "menuGroup", None) is not None
            or getattr(d, "playerMenuGroup", None) is not None)


def _mod_name(d) -> Optional[str]:
    origin = getattr(d, "_origin", None)
    return origin[0] if origin else None


def _shipdef_attr(d) -> Optional[str]:
    """The Foundation.ShipDef attribute name a mod assigned `d` to -- the
    name the gate's generated file must address (spec §6)."""
    from engine import foundation
    for name, value in vars(foundation.ShipDef).items():
        if value is d:
            return name
    return None


def _build() -> _Built:
    from engine.foundation.shipdef import all_definitions

    stock_error = None
    try:
        stock = list(_stock_definitions())
    except Exception as exc:  # noqa: BLE001 -- never raise (spec §4.3)
        stock, stock_error = [], "%s: %s" % (type(exc).__name__, exc)

    try:
        installed = _installed_scripts()
    except Exception:  # noqa: BLE001 -- paths unresolved: nothing is installed
        installed = set()

    groups: dict = {}       # folded stem -> [stock_def | None, [mod defs]]
    for d in stock:
        groups[str(d.shipFile).lower()] = [d, []]

    unresolved: list = []
    for d in all_definitions():
        ship_file = getattr(d, "shipFile", None)
        if not ship_file or not _on_qb_menu(d):
            continue
        key = str(ship_file).lower()
        if key not in installed:
            unresolved.append((str(ship_file), _mod_name(d)))
            continue
        groups.setdefault(key, [None, []])[1].append(d)

    built = []
    shared = []
    for stock_d, mod_ds in groups.values():
        e = _entry(stock_d, mod_ds, installed)
        built.append(e)
        names = [_mod_name(d) for d in mod_ds]
        if len(set(names)) >= 2:
            shared.append((e.ship_id, names))
    built.sort(key=lambda e: ((e.title or e.ship_id).lower(), e.ship_id))
    return _Built(built, unresolved, shared, stock_error)


def _entry(stock_d, mod_ds, installed) -> CatalogEntry:
    errors: list = []
    merged = None
    layers = ([stock_d] if stock_d is not None else []) + list(mod_ds)
    for d in layers:
        raw = getattr(d, "dauntless", None)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            errors.append("dauntless on %s: must be a dict (got %r)"
                          % (_mod_name(d) or "stock", raw))
            continue
        merged = dict(merged or {})
        merged.update(raw)

    parsed = parse_dauntless(merged)
    errors.extend(parsed.errors)
    variants = []
    for v in parsed.variants:
        if v.script is not None and v.script.lower() not in installed:
            errors.append("variant %r: ships/%s.py not found" % (v.name, v.script))
            continue
        variants.append(v)

    first = layers[0]
    last = layers[-1]
    values = parsed.values
    return CatalogEntry(
        ship_id=str(first.shipFile),
        icon=str(getattr(first, "iconName", None) or first.shipFile),
        source="mod" if mod_ds else "stock",
        origins=tuple((_mod_name(d), _shipdef_attr(d)) for d in mod_ds),
        title=values.get("title"),
        species=values.get("species"),
        era=values.get("era"),
        role=values.get("role"),
        playable=values.get("playable"),
        variants=tuple(variants),
        missing=parsed.missing,
        errors=tuple(errors),
        raw_name=str(getattr(last, "name", "") or ""),
        raw_race=getattr(last, "race", None),
    )


# ── species ────────────────────────────────────────────────────────────────

_INSIGNIA_EXTS = (".svg", ".png", ".tga")


def insignia_path(species):
    """The species' emblem, first that exists (spec §4.4):
    1. the committed <project assets>/insignias/<lowercased>.svg
    2. data/Icons/Species/<Species>.{svg,png,tga} via the asset overlay,
       which is how a mod that introduces a species ships its emblem
    3. None -- the screen shows the flagship's icon.
    Resolved at call time, never cached (paths rule)."""
    from pathlib import Path
    from engine import paths
    if not isinstance(species, str) or not species.strip():
        return None
    name = species.strip()
    committed = paths.project_asset_root() / "insignias" / ("%s.svg" % name.lower())
    if committed.is_file():
        return committed
    for ext in _INSIGNIA_EXTS:
        try:
            p = Path(paths.game_asset("data/Icons/Species/%s%s" % (name, ext)))
        except Exception:  # noqa: BLE001 -- unresolved game root
            return None
        if p.is_file():
            return p
    return None


def species() -> list:
    """STOCK_SPECIES in pill order, then any species an entry uses that the
    table does not know, alphabetically, flagship None. Insignia resolved."""
    from engine.ship_catalog.tables import STOCK_SPECIES, Species
    known = {s.name.lower() for s in STOCK_SPECIES}
    extra = sorted({e.species for e in _built().entries
                    if e.species and e.species.lower() not in known},
                   key=str.lower)
    out = [s._replace(insignia=insignia_path(s.name)) for s in STOCK_SPECIES]
    out += [Species(name, None, insignia_path(name)) for name in extra]
    return out
