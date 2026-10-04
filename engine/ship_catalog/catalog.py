"""Build the ship catalog from ShipDefs: stock first, then mods, per key.

Membership, merge and provenance follow spec §3; records and functions §4.
Memoised against the identity of mods.current() (the bridge_selection
pattern) and dropped by invalidate(). Entries are SNAPSHOTS: a ShipDef
mutated after the build is invisible until invalidate(). Never raises.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from engine import mods
from engine.ship_catalog.schema import Variant, parse_dauntless
from engine.ship_catalog.tables import ALL_ERAS, ERA_IDS, MANDATORY


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


@dataclass(frozen=True)
class ShipRecord:
    """One ship definition in the catalog: sub-project 1's per-key merge of
    the stock section and every mod ShipDef for the same stem, BEFORE class
    formation. The gate edits these; consumers read class entries."""
    ship_id: str             # shipFile, display spelling (stock's first)
    source: str              # "stock" | "mod"
    mod: Optional[str]       # owning mod = the last contributing mod; None = stock
    shipdef_attr: Optional[str]
    icon: str
    values: dict = field(compare=False)   # parsed own values (MANDATORY keys present)
    variant_of: Optional[str] = None      # class name as written; None = own class
    class_default: bool = False
    missing: tuple = ()
    errors: tuple = ()
    raw_name: str = ""
    raw_race: Optional[str] = None
    sub_menu: Optional[str] = None
    player_menu: bool = False
    origins: tuple = ()                   # ((mod_name, shipdef_attr), ...) load order
    declared_variants: tuple = ()         # schema.Variant from its own `variants` key


@dataclass
class _Built:
    ships: list
    members: dict           # entry ship_id.lower() -> [ShipRecord, ...]
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

    records = []
    shared = []
    for stock_d, mod_ds in groups.values():
        r = _record(stock_d, mod_ds, installed)
        records.append(r)
        names = [_mod_name(d) for d in mod_ds]
        if len(set(names)) >= 2:
            shared.append((r.ship_id, names))
    records = [r for r in records if r.ship_id.lower() not in _skipped]
    built, members = _classes(records)
    built.sort(key=lambda e: ((e.title or e.ship_id).lower(), e.ship_id))
    return _Built(records, members, built, unresolved, shared, stock_error)


def _record(stock_d, mod_ds, installed) -> ShipRecord:
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

    first, last = layers[0], layers[-1]
    last_mod = mod_ds[-1] if mod_ds else None
    return ShipRecord(
        ship_id=str(first.shipFile),
        source="mod" if mod_ds else "stock",
        mod=_mod_name(last_mod) if last_mod is not None else None,
        shipdef_attr=_shipdef_attr(last_mod) if last_mod is not None else None,
        icon=str(getattr(first, "iconName", None) or first.shipFile),
        values=dict(parsed.values),
        variant_of=parsed.variant_of,
        class_default=parsed.class_default,
        missing=parsed.missing,
        errors=tuple(errors),
        raw_name=str(getattr(last, "name", "") or ""),
        raw_race=getattr(last, "race", None),
        sub_menu=getattr(last, "SubMenu", None),
        player_menu=any(getattr(d, "playerMenuGroup", None) is not None for d in mod_ds),
        origins=tuple((_mod_name(d), _shipdef_attr(d)) for d in mod_ds),
        declared_variants=tuple(variants),
    )


# ── classes (sub-project 3 §2) ─────────────────────────────────────────────

def resolve_class_default(members, class_name: str = "") -> int:
    """Index of the class default among `members` [(title, class_default)].

    Marked members win; among several marked, a title match wins, else the
    first marked. With none marked: title equals the class name, else the
    title contains it as a whole word, else the first member."""
    key = (class_name or "").strip().lower()
    marked = [i for i, (_t, flag) in enumerate(members) if flag]
    pool = marked or list(range(len(members)))
    if key:
        for i in pool:
            if (members[i][0] or "").strip().lower() == key:
                return i
        word = re.compile(r"\b%s\b" % re.escape(key), re.IGNORECASE)
        for i in pool:
            if word.search(members[i][0] or ""):
                return i
    return pool[0]


def combine_class(members):
    """Combine members [(label, values, missing)] into the class's
    (values, missing, errors). Era: the covering span ('all' wins). Role and
    species must agree; a disagreement is MISSING plus a readable error.
    Playable: any member playable. A key missing on any member is missing."""
    values: dict = {}
    missing = []
    errors = []
    for key in MANDATORY:
        if any(key in m[2] for m in members):
            missing.append(key)
    eras = [m[1]["era"] for m in members if "era" in m[1]]
    if eras:
        if any(e == (ALL_ERAS,) for e in eras):
            values["era"] = (ALL_ERAS,)
        else:
            lo = min(ERA_IDS.index(e[0]) for e in eras)
            hi = max(ERA_IDS.index(e[1]) for e in eras)
            values["era"] = (ERA_IDS[lo], ERA_IDS[hi])
    for key in ("role", "species"):
        seen: dict = {}
        for label, v, _miss in members:
            if key in v:
                seen.setdefault(v[key], []).append(label)
        if len(seen) > 1:
            if key not in missing:
                missing.append(key)
            errors.append("%s: %s" % (key, " vs ".join(
                "%s (%s)" % (val, ", ".join(labels)) for val, labels in seen.items())))
        elif seen:
            values[key] = next(iter(seen))
    plays = [m[1]["playable"] for m in members if "playable" in m[1]]
    if plays:
        values["playable"] = any(plays)
    order = {k: i for i, k in enumerate(MANDATORY)}
    missing.sort(key=lambda k: order[k])
    return values, tuple(missing), tuple(errors)


def _title_of(r: ShipRecord) -> str:
    return r.values.get("title") or r.raw_name or r.ship_id


def _member(r: ShipRecord):
    return (_title_of(r), r.values, r.missing)


def _own_entry(r: ShipRecord, joiners: list) -> CatalogEntry:
    """A ship that is its own class; stock entries gain any mod ship that
    named the stock class (appended; the stock default stays)."""
    group = [r] + list(joiners)
    values, missing, errors = combine_class([_member(m) for m in group])
    errs = list(r.errors) + list(errors)
    variants = list(r.declared_variants)
    for j in joiners:
        errs.extend(j.errors)
        if j.class_default:
            errs.append("%s: class_default ignored -- the stock class keeps "
                        "its own default" % j.ship_id)
        variants.append(Variant(_title_of(j), j.ship_id, playable=j.values.get("playable")))
    title = r.values.get("title")
    return CatalogEntry(
        ship_id=r.ship_id, icon=r.icon,
        source="mod" if any(m.source == "mod" for m in group) else "stock",
        origins=tuple(o for m in group for o in m.origins),
        title=title, species=values.get("species"), era=values.get("era"),
        role=values.get("role"), playable=values.get("playable"),
        variants=tuple(variants), missing=missing, errors=tuple(errs),
        raw_name=r.raw_name, raw_race=r.raw_race)


def _named_entry(name: str, members: list) -> CatalogEntry:
    """A class formed by ships naming the same `variant_of`."""
    idx = resolve_class_default([(_title_of(m), m.class_default) for m in members], name)
    default = members[idx]
    ordered = [default] + [m for i, m in enumerate(members) if i != idx]
    values, missing, errors = combine_class([_member(m) for m in ordered])
    errs = [e for m in ordered for e in m.errors] + list(errors)
    if sum(1 for m in members if m.class_default) > 1:
        errs.append("class %r: several ships marked class_default; using %s"
                    % (name, default.ship_id))
    variants = [Variant(_title_of(default), playable=default.values.get("playable"))]
    variants += [Variant(_title_of(m), m.ship_id, playable=m.values.get("playable"))
                 for m in ordered[1:]]
    return CatalogEntry(
        ship_id=default.ship_id, icon=default.icon, source="mod",
        origins=tuple(o for m in ordered for o in m.origins),
        title=name, species=values.get("species"), era=values.get("era"),
        role=values.get("role"), playable=values.get("playable"),
        variants=tuple(variants), missing=missing, errors=tuple(errs),
        raw_name=default.raw_name, raw_race=default.raw_race)


def _classes(records: list):
    """(entries, members-by-entry-id) from the records."""
    stock_by_title = {r.values["title"].strip().lower(): r for r in records
                      if r.source == "stock" and r.values.get("title")}
    own, joined, named = [], {}, {}
    for r in records:
        key = (r.variant_of or "").strip().lower()
        if not key or r.source == "stock":
            own.append(r)
            continue
        stock = stock_by_title.get(key)
        if stock is not None:
            joined.setdefault(stock.ship_id.lower(), []).append(r)
            continue
        named.setdefault(key, {"name": r.variant_of.strip(), "members": []})["members"].append(r)
    entries, members = [], {}
    for r in own:
        joiners = joined.get(r.ship_id.lower(), [])
        e = _own_entry(r, joiners)
        entries.append(e)
        members[e.ship_id.lower()] = [r] + joiners
    for c in named.values():
        e = _named_entry(c["name"], c["members"])
        entries.append(e)
        members[e.ship_id.lower()] = list(c["members"])
    return entries, members


def ships(source: Optional[str] = None) -> list:
    """Every ShipRecord (stock and mod), or only `source` ("stock"/"mod")."""
    return [r for r in _built().ships if source is None or r.source == source]


# ── gate support (sub-project 3 §2.3-2.4, §3.3) ────────────────────────────

RACE_TO_SPECIES = {"fed": "Federation", "klingon": "Klingon", "romulan": "Romulan",
                   "cardassian": "Cardassian", "ferengi": "Ferengi", "kessok": "Kessok"}

# Folded ship ids hidden for this PROCESS by "Skip for now". Not part of the
# memo: invalidate() must not un-skip. reset_session() is for tests.
_skipped: set = set()


def skip_for_session(ship_ids) -> None:
    _skipped.update(str(s).lower() for s in ship_ids)
    invalidate()


def skipped() -> frozenset:
    return frozenset(_skipped)


def reset_session() -> None:
    _skipped.clear()
    invalidate()


def incomplete_ships() -> list:
    """Mod ships the gate must ask about: those missing a key, plus every mod
    member of a class with a role/species conflict -- whatever its siblings
    are missing, since the player fixes a conflict by editing any member.
    Load order, no duplicates."""
    b = _built()
    out = [r for r in b.ships if r.source == "mod" and r.missing]
    seen = {r.ship_id for r in out}
    for e in b.entries:
        if e.complete:
            continue
        group = b.members.get(e.ship_id.lower(), [])
        _v, _m, errors = combine_class([_member(m) for m in group])
        if any(err.startswith(("role:", "species:")) for err in errors):
            for m in group:
                if m.source == "mod" and m.ship_id not in seen:
                    out.append(m)
                    seen.add(m.ship_id)
    return out


def suggestions(r: ShipRecord) -> dict:
    """Pre-fills for one ship (spec §2.4). Only keys with a real source."""
    out: dict = {}
    if r.raw_name:
        out["title"] = r.raw_name
    species = RACE_TO_SPECIES.get(str(r.raw_race or "").lower())
    if species:
        out["species"] = species
    if r.player_menu:
        out["playable"] = True
    out["role"] = "tactical"
    sub = re.sub(r"\s*class\s*$", "", str(r.sub_menu or ""), flags=re.IGNORECASE).strip()
    if sub:
        out["variant_of"] = sub
    return out


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


# ── boot report ────────────────────────────────────────────────────────────

def describe() -> str:
    """One boot line (+ indented details), or "" when there is nothing to
    say: stock only, every entry complete, no problems (spec §5). The whole
    body is guarded: host_loop calls this unguarded at boot."""
    try:
        return _describe(_built())
    except Exception as exc:  # noqa: BLE001 -- a boot report must not kill boot
        return "ship catalog: WARNING could not build: %s: %s" % (
            type(exc).__name__, exc)


def _describe(b: _Built) -> str:
    n_stock = sum(1 for e in b.entries if e.source == "stock")
    n_mod = len(b.entries) - n_stock
    bad = [e for e in b.entries if not e.complete]
    if not (n_mod or bad or b.unresolved or b.shared or b.stock_error):
        return ""

    head = "ship catalog: %d stock, %d mod" % (n_stock, n_mod)
    if bad:
        by_mod: dict = {}
        for e in bad:
            who = (e.origins[-1][0] if e.origins else None) or "stock"
            by_mod[who] = by_mod.get(who, 0) + 1
        head += "; %d incomplete (%s)" % (len(bad), ", ".join(
            "%s: %d" % (k, by_mod[k]) for k in sorted(by_mod)))
    lines = [head]
    for ship_id, names in b.shared:
        # A definition built outside plugin_origin has no mod name: "?".
        lines.append("  shared stem %r: %s" % (
            ship_id, " over ".join(str(n or "?") for n in reversed(names))))
    for ship_file, mod_name in b.unresolved:
        lines.append("  unresolved: %s (%s) -- ships/%s.py not found"
                     % (ship_file, mod_name, ship_file))
    if b.stock_error:
        lines.append("  WARNING stock metadata failed to load: %s" % b.stock_error)
    return "\n".join(lines)
