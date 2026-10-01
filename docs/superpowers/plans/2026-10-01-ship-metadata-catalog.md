# Ship Metadata Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Quick Battle ship definition Dauntless-owned metadata (era span, role, playable, title, species, named variants) and expose it through one read-only catalog API, `engine.ship_catalog`.

**Architecture:**
- Metadata is a `dauntless` dict on the Foundation `ShipDefinition`.
- Stock ships get unlisted `ShipDefinition`s from a committed, hand-edited `engine/foundation/shipdef_overrides.py`. Mod ships set the attribute in their own `Custom/Ships` scripts.
- `engine/ship_catalog/` merges the two per key (stock first, then mods in load order). It validates the result into frozen `CatalogEntry` records, memoised against the mod index.

**Tech Stack:** Python 3 (engine), pytest via `uv run pytest`. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md`. Read it first; this plan argues from it. Roadmap: `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md`.

## Global Constraints

**Git (shared checkout)**
- Work on branch `feat/qb-ship-metadata`, in worktree `.claude/worktrees/qb-ship-metadata`. Run `git branch --show-current` before every commit. **Never commit to `main`.**
- Stage with explicit pathspecs only. These are banned: `git add -A`, `git add .`, `git stash`, `git checkout -- <path>`, `git restore`, `git clean`, `git reset --hard`.

**Paths**
- Resolve paths at use, never at import. No module-level constant may hold a path.
- Never spell `game` or `sdk` as a path segment; use `engine.paths` accessors. `tests/unit/test_path_indirection.py` enforces this.

**Data rules**
- `dauntless` dict literals in `shipdef_overrides.py` must be Python 1.5-safe: no `True`/`False`, no f-strings. Use `1`/`0`.
- Era ids, exactly: `ENT TOS MOV TNG DS9 PIC DISC`, plus `'all'`.
- Role ids, exactly: `tactical auxiliary station automated`.
- Mandatory keys, in this order: `era, role, playable, title, species`. `variants` is optional.

**Behaviour**
- The catalog never raises. Bad data becomes `missing` or `errors` on the entry.
- Do not change the behaviour of:
  - QuickBattle's SDK tables
  - `bridge_selection`
  - `shipdef.all_definitions()` and `icon_name_for_script`
  - `species_icons`
  - `foundation.describe`

**Gate**
- Run `scripts/check_tests.sh` before calling the branch done.

## Review Focus

1. **Mod authors' case drift.** `shipFile = 'galaxy'` or `'LCintrepid'` against a file `LCIntrepid.py` must still resolve, and must merge onto the stock `Galaxy` entry. Pinned in Task 5 (`test_mod_shipfile_case_drift_merges_onto_stock`).
2. **A mod `dauntless` that is not a dict** (a string, a list) must not crash the build. The entry is all-missing and carries an error. Pinned in Task 5 (`test_non_dict_dauntless_is_an_error_not_a_crash`).
3. **A partial declaration on a new mod ship** must report exactly the remaining keys as missing, in mandatory order. Pinned in Task 5 (`test_partial_mod_metadata_lists_exactly_the_rest`).
4. **A plugin script that raises after building a ShipDef** must not leave its origin attached to the next mod's definitions. Pinned in Task 3 (`test_origin_is_cleared_after_a_failing_plugin`).
5. **Lowercase era ids** (`'ds9'`), lists in place of tuples, and an out-of-range `playable` (`2`): the first two are accepted and the last is rejected. Pinned in Task 2.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/ship_catalog/__init__.py` (create) | Public API re-exports |
| `engine/ship_catalog/tables.py` (create) | `ERAS`, `ROLES`, `STOCK_SPECIES`, `MANDATORY`: pure display constants |
| `engine/ship_catalog/schema.py` (create) | `Variant`, `Parsed`, `parse_dauntless()`: pure validation of one merged dict |
| `engine/ship_catalog/catalog.py` (create) | `CatalogEntry`, build, merge, membership, memo, `species()`, `insignia_path()`, `describe()` |
| `engine/foundation/shipdef_overrides.py` (create) | The 33 stock definitions with their `dauntless` sections |
| `engine/foundation/shipdef.py` (modify) | `_listed` kwarg, `"dauntless"` in `_KNOWN`, `plugin_origin()` and `_origin` |
| `engine/foundation/loader.py` (modify) | Wrap each `runpy.run_path` in `plugin_origin` |
| `engine/foundation/__init__.py` (modify) | `reset()` also invalidates the catalog |
| `engine/host_loop.py` (modify, ~line 9415) | Print `ship_catalog.describe()` after the Foundation report |
| `native/assets/insignias/*.svg` (create) | The five committed insignias, copied from the spike branch |
| `tests/conftest.py` (modify) | Invalidate the catalog in `_reset_leakable_engine_globals` |
| `tests/unit/test_ship_catalog_*.py`, `tests/integration/test_ship_catalog_stock_content.py` (create) | Tests |
| `CLAUDE.md` (modify) | One Key-reference row |

---

### Task 1: Tables and package skeleton

**Files:**
- Create: `engine/ship_catalog/__init__.py`
- Create: `engine/ship_catalog/tables.py`
- Test: `tests/unit/test_ship_catalog_tables.py`

**Interfaces:**
- Produces:
  - `Era(id, name, tag, start, end)`, `ERAS`, `ERA_IDS`, `ALL_ERAS = "all"`, `DEFAULT_ERAS = ("DS9",)`
  - `Role(id, label)`, `ROLES`, `ROLE_IDS`
  - `Species(name, flagship, insignia)`, `STOCK_SPECIES`
  - `MANDATORY = ("era", "role", "playable", "title", "species")`

- [ ] **Step 1: Write the failing test**

```python
"""engine.ship_catalog.tables -- the display data mod files never spell."""
from engine.ship_catalog import tables as t


def test_eras_are_the_roadmaps_seven_in_order():
    assert t.ERA_IDS == ("ENT", "TOS", "MOV", "TNG", "DS9", "PIC", "DISC")
    ds9 = t.ERAS[4]
    assert (ds9.name, ds9.tag, ds9.start, ds9.end) == (
        "Quadrant Wars", "DS9 · VOY", 2367, 2399)
    # A boundary year belongs to the later era: each era starts where the
    # previous one ends, except the 2499/2500 gap the roadmap authored.
    assert t.ERAS[0].start == 2140 and t.ERAS[-1].end == 3200
    assert t.DEFAULT_ERAS == ("DS9",)
    assert t.ALL_ERAS == "all"


def test_roles_ids_and_labels():
    assert t.ROLE_IDS == ("tactical", "auxiliary", "station", "automated")
    assert [r.label for r in t.ROLES] == [
        "Tactical", "Auxiliary", "Station", "Automated / Unmanned"]


def test_stock_species_pill_order_and_flagships():
    assert [(s.name, s.flagship) for s in t.STOCK_SPECIES] == [
        ("Federation", "Sovereign"), ("Klingon", "Vorcha"),
        ("Romulan", "Warbird"), ("Cardassian", "Keldon"),
        ("Ferengi", "Marauder"), ("Kessok", "KessokHeavy"),
        ("Civilian", "Freighter"), ("Neutral", "Asteroid")]
    assert all(s.insignia is None for s in t.STOCK_SPECIES)  # resolved at use


def test_mandatory_order():
    assert t.MANDATORY == ("era", "role", "playable", "title", "species")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_ship_catalog_tables.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ship_catalog'`

- [ ] **Step 3: Write the implementation**

`engine/ship_catalog/tables.py`:

```python
"""Display tables for ship metadata: eras, roles, stock species.

Pure constants. Mod files name eras and roles by ID only, so names, tags and
years can change here without touching any mod. Insignia paths are NOT here:
they resolve at use (catalog.insignia_path), never at import.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md §4.1
"""
from __future__ import annotations

from collections import namedtuple

Era = namedtuple("Era", "id name tag start end")

ERAS = (
    Era("ENT", "Pre Federation", "ENT", 2140, 2240),
    Era("TOS", "Early Federation", "TOS", 2240, 2293),
    Era("MOV", "Expansion Era", "MOV", 2293, 2330),
    Era("TNG", "High Era", "TNG", 2330, 2367),
    Era("DS9", "Quadrant Wars", "DS9 · VOY", 2367, 2399),
    Era("PIC", "Romulan Vacuum", "PIC", 2399, 2499),
    Era("DISC", "Distant Future", "DISC", 2500, 3200),
)
ERA_IDS = tuple(e.id for e in ERAS)
ALL_ERAS = "all"
DEFAULT_ERAS = ("DS9",)          # BC is set after the Dominion War

Role = namedtuple("Role", "id label")

ROLES = (
    Role("tactical", "Tactical"),
    Role("auxiliary", "Auxiliary"),
    Role("station", "Station"),
    Role("automated", "Automated / Unmanned"),
)
ROLE_IDS = tuple(r.id for r in ROLES)

# insignia is a Path or None; always None here, filled by catalog.species().
Species = namedtuple("Species", "name flagship insignia")

STOCK_SPECIES = (
    Species("Federation", "Sovereign", None),
    Species("Klingon", "Vorcha", None),
    Species("Romulan", "Warbird", None),
    Species("Cardassian", "Keldon", None),
    Species("Ferengi", "Marauder", None),
    Species("Kessok", "KessokHeavy", None),
    Species("Civilian", "Freighter", None),
    Species("Neutral", "Asteroid", None),
)

MANDATORY = ("era", "role", "playable", "title", "species")
```

`engine/ship_catalog/__init__.py`:

```python
"""The ship catalog: every Quick Battle ship definition, with Dauntless metadata.

The ONE place the engine reads ship metadata from. Consumers (the setup
screen, the mod metadata gate) never read a ShipDef or a metadata file.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md
"""
from engine.ship_catalog.tables import (  # noqa: F401
    ALL_ERAS, DEFAULT_ERAS, ERA_IDS, ERAS, MANDATORY, ROLE_IDS, ROLES,
    STOCK_SPECIES, Era, Role, Species)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_ship_catalog_tables.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/__init__.py engine/ship_catalog/tables.py tests/unit/test_ship_catalog_tables.py
git commit -m "feat(ship_catalog): era, role and stock species tables"
```

---

### Task 2: `parse_dauntless`: validate one metadata dict

**Files:**
- Create: `engine/ship_catalog/schema.py`
- Modify: `engine/ship_catalog/__init__.py` (re-export `Variant`)
- Test: `tests/unit/test_ship_catalog_schema.py`

**Interfaces:**
- Consumes: `tables.ALL_ERAS, ERA_IDS, MANDATORY, ROLE_IDS, STOCK_SPECIES`
- Produces:
  - `Variant(name: str, script: str | None = None, registry: str | None = None)`, frozen
  - `Parsed(values: dict, variants: tuple[Variant], missing: tuple[str], errors: tuple[str])`, frozen
  - `parse_dauntless(raw) -> Parsed`. `values` keys are a subset of `MANDATORY`:
    - `era` is `(from_id, to_id)` or `("all",)`
    - `role` is a role id
    - `playable` is a `bool`
    - `title` is a stripped str
    - `species` uses the stock spelling when it matches case-insensitively

- [ ] **Step 1: Write the failing tests**

```python
"""engine.ship_catalog.schema.parse_dauntless -- one merged dict in, values,
missing keys and readable errors out. Never raises."""
import pytest

from engine.ship_catalog.schema import Variant, parse_dauntless

FULL = {"title": "Galaxy", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}


def test_full_dict_is_complete():
    p = parse_dauntless(FULL)
    assert p.missing == () and p.errors == ()
    assert p.values == {"title": "Galaxy", "species": "Federation",
                        "era": ("DS9", "DS9"), "role": "tactical",
                        "playable": True}
    assert p.variants == ()


def test_none_means_everything_missing_without_errors():
    p = parse_dauntless(None)
    assert p.missing == ("era", "role", "playable", "title", "species")
    assert p.errors == ()


def test_non_dict_is_an_error_and_everything_missing():
    p = parse_dauntless("Federation")
    assert p.missing == ("era", "role", "playable", "title", "species")
    assert len(p.errors) == 1 and "must be a dict" in p.errors[0]


@pytest.mark.parametrize("era, want", [
    ("DS9", ("DS9", "DS9")),
    ("ds9", ("DS9", "DS9")),                 # ids fold
    (("MOV", "DS9"), ("MOV", "DS9")),
    (["tng", "PIC"], ("TNG", "PIC")),        # list accepted
    ("all", ("all",)),
    ("ALL", ("all",)),
])
def test_era_forms(era, want):
    assert parse_dauntless(dict(FULL, era=era)).values["era"] == want


@pytest.mark.parametrize("era", [
    ("DS9", "MOV"),          # from after to
    "VOY",                   # not an id
    ("DS9",),                # wrong arity
    ("DS9", "PIC", "DISC"),
    2370, None, "",
])
def test_invalid_era_is_missing_with_an_error(era):
    p = parse_dauntless(dict(FULL, era=era))
    assert p.missing == ("era",)
    assert len(p.errors) == 1 and p.errors[0].startswith("era:")


@pytest.mark.parametrize("playable, want", [(1, True), (0, False),
                                             (True, True), (False, False)])
def test_playable_accepts_0_1_and_bools(playable, want):
    assert parse_dauntless(dict(FULL, playable=playable)).values["playable"] is want


@pytest.mark.parametrize("playable", [2, -1, "yes", None, 1.0])
def test_playable_rejects_anything_else(playable):
    assert parse_dauntless(dict(FULL, playable=playable)).missing == ("playable",)


def test_role_folds_and_rejects_labels_and_unknowns():
    assert parse_dauntless(dict(FULL, role="Station")).values["role"] == "station"
    assert parse_dauntless(dict(FULL, role="Automated / Unmanned")).missing == ("role",)
    assert parse_dauntless(dict(FULL, role="carrier")).missing == ("role",)


def test_species_canonicalises_stock_spelling_and_keeps_new_ones():
    assert parse_dauntless(dict(FULL, species="klingon")).values["species"] == "Klingon"
    assert parse_dauntless(dict(FULL, species=" Borg ")).values["species"] == "Borg"
    assert parse_dauntless(dict(FULL, species="  ")).missing == ("species",)


def test_title_is_stripped_and_must_be_non_empty():
    assert parse_dauntless(dict(FULL, title=" Defiant ")).values["title"] == "Defiant"
    assert parse_dauntless(dict(FULL, title="")).missing == ("title",)
    assert parse_dauntless(dict(FULL, title=7)).missing == ("title",)


def test_missing_keys_come_out_in_mandatory_order():
    p = parse_dauntless({"title": "X", "role": "tactical"})
    assert p.missing == ("era", "playable", "species")
    assert p.errors == ()


def test_variants_kept_in_order():
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Sovereign", "registry": "Sovereign"},
        {"name": "USS Enterprise", "script": "Enterprise", "registry": "Enterprise"},
    ]))
    assert p.variants == (Variant("USS Sovereign", None, "Sovereign"),
                          Variant("USS Enterprise", "Enterprise", "Enterprise"))
    assert p.errors == ()


@pytest.mark.parametrize("bad, fragment", [
    ({"registry": "X"}, "needs a non-empty 'name'"),
    ({"name": "USS Nameless"}, "needs a 'script' or a 'registry'"),
    ("USS Venture", "must be a dict"),
])
def test_invalid_variant_is_dropped_with_an_error_and_never_makes_incomplete(bad, fragment):
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Dauntless", "registry": "Dauntless"}, bad]))
    assert p.variants == (Variant("USS Dauntless", None, "Dauntless"),)
    assert p.missing == ()
    assert len(p.errors) == 1 and fragment in p.errors[0]


def test_duplicate_variant_name_is_dropped():
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS A", "registry": "A"}, {"name": "USS A", "registry": "B"}]))
    assert p.variants == (Variant("USS A", None, "A"),)
    assert "duplicate" in p.errors[0]


def test_class_default_must_not_carry_a_script():
    """variants[0] IS the definition: it spawns the definition's own script."""
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Geronimo", "script": "Geronimo", "registry": "Geronimo"},
        {"name": "USS Devore", "registry": "Devore"}]))
    assert p.variants == (Variant("USS Devore", None, "Devore"),)
    assert "class default" in p.errors[0]


def test_variants_not_a_list_is_an_error():
    p = parse_dauntless(dict(FULL, variants="USS Venture"))
    assert p.variants == () and "variants: must be a list" in p.errors[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_catalog_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ship_catalog.schema'`

- [ ] **Step 3: Write the implementation**

`engine/ship_catalog/schema.py`:

```python
"""Validate one ShipDef `dauntless` dict (already merged across layers).

Pure: no paths, no mods, no Foundation. An invalid value is treated exactly
like an absent one (it lands in `missing`), plus a readable line in `errors`
so the mod metadata gate can say WHY. An invalid variant is dropped with an
error; variants are optional, so that never makes an entry incomplete.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md §1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from engine.ship_catalog.tables import (
    ALL_ERAS, ERA_IDS, MANDATORY, ROLE_IDS, STOCK_SPECIES)


@dataclass(frozen=True)
class Variant:
    """A named ship. `script` spawns a separate ships/<script>.py instead of
    the definition's own; `registry` is the hull-name decal registry
    (Masks/<registry>/). At least one is set."""
    name: str
    script: Optional[str] = None
    registry: Optional[str] = None


@dataclass(frozen=True)
class Parsed:
    values: dict
    variants: tuple
    missing: tuple
    errors: tuple


def _text(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _era(value) -> Optional[tuple]:
    if isinstance(value, str):
        if value.strip().lower() == ALL_ERAS:
            return (ALL_ERAS,)
        value = (value, value)
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    if not all(isinstance(v, str) for v in value):
        return None
    lo, hi = (v.strip().upper() for v in value)
    if lo not in ERA_IDS or hi not in ERA_IDS:
        return None
    if ERA_IDS.index(lo) > ERA_IDS.index(hi):
        return None
    return (lo, hi)


def _role(value) -> Optional[str]:
    if isinstance(value, str) and value.strip().lower() in ROLE_IDS:
        return value.strip().lower()
    return None


def _playable(value) -> Optional[bool]:
    # bool first: bool is an int subclass, and True/False must stay accepted.
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None


def _species(value) -> Optional[str]:
    text = _text(value)
    if text is None:
        return None
    for s in STOCK_SPECIES:
        if s.name.lower() == text.lower():
            return s.name
    return text


_PARSERS = {"era": _era, "role": _role, "playable": _playable,
            "title": _text, "species": _species}


def parse_dauntless(raw) -> Parsed:
    errors: list = []
    if raw is None:
        raw = {}
    elif not isinstance(raw, dict):
        errors.append("dauntless: must be a dict (got %r)" % (raw,))
        raw = {}

    values: dict = {}
    missing: list = []
    for key in MANDATORY:
        if key not in raw:
            missing.append(key)
            continue
        got = _PARSERS[key](raw[key])
        if got is None:
            missing.append(key)
            errors.append("%s: invalid value %r" % (key, raw[key]))
        else:
            values[key] = got

    variants = _variants(raw.get("variants"), errors)
    return Parsed(values, variants, tuple(missing), tuple(errors))


def _variants(raw, errors: list) -> tuple:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        errors.append("variants: must be a list (got %r)" % (raw,))
        return ()
    kept: list = []
    seen: set = set()
    for i, v in enumerate(raw):
        where = "variants[%d]" % i
        if not isinstance(v, dict):
            errors.append("%s: must be a dict (got %r)" % (where, v))
            continue
        name = _text(v.get("name"))
        if name is None:
            errors.append("%s: needs a non-empty 'name'" % where)
            continue
        script = _text(v.get("script"))
        registry = _text(v.get("registry"))
        if script is None and registry is None:
            errors.append("%s %r: needs a 'script' or a 'registry'" % (where, name))
            continue
        if name in seen:
            errors.append("%s %r: duplicate name" % (where, name))
            continue
        if not kept and script is not None:
            # The first KEPT variant is the class default, which spawns the
            # definition's own script (spec §1).
            errors.append("%s %r: the class default must not have a 'script'"
                          % (where, name))
            continue
        seen.add(name)
        kept.append(Variant(name, script, registry))
    return tuple(kept)
```

Append to `engine/ship_catalog/__init__.py`:

```python
from engine.ship_catalog.schema import Variant  # noqa: F401
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_catalog_schema.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/schema.py engine/ship_catalog/__init__.py tests/unit/test_ship_catalog_schema.py
git commit -m "feat(ship_catalog): validate a ShipDef dauntless dict"
```

---

### Task 3: Foundation surface: unlisted definitions, `dauntless`, provenance

**Files:**
- Modify: `engine/foundation/shipdef.py` (the `_KNOWN` set at line 13; `ShipDefinition.__init__` at line 61; a new context manager)
- Modify: `engine/foundation/loader.py:56-66`
- Test: `tests/unit/test_foundation_shipdef_metadata.py`

**Interfaces:**
- Produces:
  - `ShipDefinition(race, abbrev, species, details=None, dict=None, *, _listed=True)`. With `_listed=False` the definition is not added to `_ALL_DEFINITIONS`.
  - `shipdef.plugin_origin(mod_name: str, key: str)`, a context manager.
  - Every `ShipDefinition` gets `_origin`: `(mod_name, key)` inside a plugin run, else `None`.
  - `"dauntless"` joins `_KNOWN`, so it is not an unknown attribute.

- [ ] **Step 1: Write the failing tests**

```python
"""Foundation surface for ship metadata: the `dauntless` attribute, unlisted
(stock) definitions, and which mod built a definition."""
import pytest

from engine import foundation, mods
from engine.foundation import loader, quickbattle, shipdef
from engine.foundation.shipdef import ShipDefinition, all_definitions, plugin_origin


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def test_dauntless_is_a_known_attribute():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    d.dauntless = {"title": "X"}
    assert "dauntless" not in d.unknown_attributes


def test_unlisted_definition_stays_out_of_all_definitions():
    d = ShipDefinition("Fed", "X", None, {"shipFile": "X"}, _listed=False)
    assert d not in all_definitions()
    assert shipdef.icon_name_for_script("ships.X") is None


def test_listed_is_the_default():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    assert d in all_definitions()


def test_origin_is_recorded_inside_plugin_origin_only():
    with plugin_origin("DCMPv2", "custom/ships/dcmp.py"):
        inside = ShipDefinition("Fed", "A", 103)
    outside = ShipDefinition("Fed", "B", 103)
    assert inside._origin == ("DCMPv2", "custom/ships/dcmp.py")
    assert outside._origin is None
    assert "_origin" not in inside.unknown_attributes


def _touch(p, body):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


_MAKE = ("from engine.foundation.shipdef import ShipDefinition\n"
         "ShipDefinition('Fed', %r, 103, {'shipFile': %r})\n")


def test_loader_attributes_each_definition_to_its_mod(tmp_path):
    _touch(tmp_path / "ModA" / "scripts" / "Custom" / "Ships" / "a.py", _MAKE % ("A", "A"))
    _touch(tmp_path / "ModB" / "scripts" / "Custom" / "Ships" / "b.py", _MAKE % ("B", "B"))
    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()
    got = {d.abbrev: d._origin for d in all_definitions()}
    assert got == {"A": ("ModA", "custom/ships/a.py"),
                   "B": ("ModB", "custom/ships/b.py")}


def test_origin_is_cleared_after_a_failing_plugin(tmp_path):
    _touch(tmp_path / "ModA" / "scripts" / "Custom" / "Ships" / "a.py",
           _MAKE % ("A", "A") + "raise RuntimeError('boom')\n")
    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()
    assert report.failures and report.failures[0][0] == "custom/ships/a.py"
    assert shipdef._CURRENT_ORIGIN is None
    later = ShipDefinition("Fed", "C", 103)
    assert later._origin is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_foundation_shipdef_metadata.py -v`
Expected: FAIL with `ImportError: cannot import name 'plugin_origin'`

- [ ] **Step 3: Write the implementation**

In `engine/foundation/shipdef.py`:

1. Add `"dauntless"` to `_KNOWN`. Its last line becomes:

```python
    "friendlyDetails", "enemyDetails", "menuGroup", "playerMenuGroup",
    "dauntless",
})
```

2. Below `_ALL_DEFINITIONS: list = []`, add:

```python
# (mod_name, folded index key) of the Custom/ plugin script currently being
# run by engine.foundation.loader, else None. Copied into each definition's
# `_origin` so the ship catalog knows WHICH mod declared it -- the metadata
# gate writes its answers into that mod (spec 2026-10-01 ship metadata §2.2).
_CURRENT_ORIGIN = None


@contextlib.contextmanager
def plugin_origin(mod_name, key):
    global _CURRENT_ORIGIN
    previous = _CURRENT_ORIGIN
    _CURRENT_ORIGIN = (mod_name, key)
    try:
        yield
    finally:
        _CURRENT_ORIGIN = previous
```

and `import contextlib` under `from __future__ import annotations`.

3. Change `__init__`'s signature and its registration lines:

```python
    def __init__(self, race, abbrev, species, details=None, dict=None, *,
                 _listed=True):
        # `dict` shadows the builtin deliberately: Foundation's own keyword
        # is spelled that way and mods pass it positionally or by name.
        object.__setattr__(self, "unknown_attributes", {})
        # Every definition ever built, so describe() can report declared
        # techs without the caller having to hand them over. Registration
        # into ShipDef is a mod's choice; existing is not. The one exception
        # is _listed=False: engine/foundation/shipdef_overrides.py's STOCK
        # definitions, which carry metadata only and must not change what
        # all_definitions()'s readers (bridge_selection, icon_name_for_script,
        # describe) see.
        if _listed:
            _ALL_DEFINITIONS.append(self)
        self._origin = _CURRENT_ORIGIN
```

The remaining lines of `__init__` (`self.race = race` onward) are unchanged.

In `engine/foundation/loader.py`, inside `load_plugins`, replace the `try:` body:

```python
            try:
                with plugin_origin(mf.mod_name, key):
                    runpy.run_path(str(mf.abs_path), run_name="__foundation__")
```

and add `from engine.foundation.shipdef import plugin_origin` beside `from engine import mods` inside the function.

- [ ] **Step 4: Run the tests to verify they pass, then the Foundation suite**

Run: `uv run pytest tests/unit/test_foundation_shipdef_metadata.py tests/unit/test_foundation_*.py tests/unit/test_bridge_selection.py -v`
Expected: PASS (all). The existing Foundation tests guard the unchanged default behaviour.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/foundation/shipdef.py engine/foundation/loader.py tests/unit/test_foundation_shipdef_metadata.py
git commit -m "feat(foundation): dauntless attribute, unlisted defs, plugin provenance"
```

---

### Task 4: The stock file `shipdef_overrides.py`

**Files:**
- Create: `engine/foundation/shipdef_overrides.py`
- Test: `tests/unit/test_ship_catalog_stock.py`

**Interfaces:**
- Consumes: `ShipDefinition(..., _listed=False)` (Task 3); `parse_dauntless` (Task 2, test only)
- Produces: `shipdef_overrides.stock_definitions() -> list[ShipDefinition]`: 33 entries in file order, each with `shipFile`, `iconName`, `name` (the title), `race` (the species) and `dauntless`.

- [ ] **Step 1: Write the failing test**

```python
"""engine/foundation/shipdef_overrides.py -- the stock seed, which must equal
the roadmap appendix (docs/superpowers/specs/2026-10-01-quickbattle-redesign-
roadmap.md). The table below is a deliberate literal copy: drift fails here."""
import ast
from pathlib import Path

import pytest

from engine import foundation
from engine.foundation import shipdef_overrides
from engine.foundation.shipdef import all_definitions
from engine.ship_catalog.schema import parse_dauntless


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    yield
    foundation.reset()


T, A, S, U = "tactical", "auxiliary", "station", "automated"
# ship_id, title, species, role, playable, era, icon, variant names
APPENDIX = [
    ("Akira", "Akira", "Federation", T, True, "DS9", "Akira", ["USS Geronimo", "USS Devore"]),
    ("Ambassador", "Ambassador", "Federation", T, True, "DS9", "Ambassador", ["USS Zhukov", "USS Excalibur"]),
    ("Galaxy", "Galaxy", "Federation", T, True, "DS9", "Galaxy", ["USS Dauntless", "USS San Francisco", "USS Venture"]),
    ("Nebula", "Nebula", "Federation", T, True, "DS9", "Nebula", ["USS Berkeley", "USS Prometheus", "USS Khitomer", "USS Nightingale"]),
    ("Sovereign", "Sovereign", "Federation", T, True, "DS9", "Sovereign", ["USS Sovereign", "USS Enterprise"]),
    ("Shuttle", "Shuttle", "Federation", A, True, "DS9", "FedShuttle", []),
    ("EscapePod", "Escape Pod", "Federation", A, False, "DS9", "LifeBoat", []),
    ("FedStarbase", "Fed Starbase", "Federation", S, False, "DS9", "FedStarbase", []),
    ("FedOutpost", "Fed Outpost", "Federation", S, False, "DS9", "FedOutpost", []),
    ("SpaceFacility", "Space Facility", "Federation", S, False, "DS9", "SpaceFacility", []),
    ("DryDock", "Dry Dock", "Federation", S, False, "DS9", "DryDock", []),
    ("CommArray", "Comm Array", "Federation", U, False, "DS9", "CommArray", []),
    ("Probe", "Probe", "Federation", U, False, "DS9", "Probe", []),
    ("Decoy", "Decoy", "Federation", U, False, "DS9", "ProbeType2", []),
    ("BirdOfPrey", "Bird of Prey", "Klingon", T, True, "DS9", "BirdOfPrey", []),
    ("Vorcha", "Vor'cha", "Klingon", T, True, "DS9", "Vorcha", []),
    ("Warbird", "Warbird", "Romulan", T, True, "DS9", "Warbird", []),
    ("Galor", "Galor", "Cardassian", T, True, "DS9", "Galor", []),
    ("Keldon", "Keldon", "Cardassian", T, True, "DS9", "Keldon", []),
    ("CardHybrid", "Hybrid", "Cardassian", T, True, "DS9", "Hybrid", []),
    ("CardFreighter", "Card Freighter", "Cardassian", A, False, "DS9", "CardFreighter", []),
    ("CardStarbase", "Card Starbase", "Cardassian", S, False, "DS9", "CardStarbase", []),
    ("CardStation", "Card Station", "Cardassian", S, False, "DS9", "CardStation", []),
    ("CardOutpost", "Card Outpost", "Cardassian", S, False, "DS9", "CardOutpost", []),
    ("CommLight", "Comm Light", "Cardassian", U, False, "DS9", "CommLight", []),
    ("Marauder", "Marauder", "Ferengi", T, True, "DS9", "Marauder", []),
    ("KessokLight", "Kessok Light", "Kessok", T, True, "DS9", "KessokLight", []),
    ("KessokHeavy", "Kessok Heavy", "Kessok", T, True, "DS9", "KessokHeavy", []),
    ("KessokMine", "Kessok Mine", "Kessok", U, False, "DS9", "KessokMine", []),
    ("Sunbuster", "Sun Buster", "Kessok", U, False, "DS9", "Sunbuster", []),
    ("Transport", "Transport", "Civilian", A, True, "DS9", "Transport", []),
    ("Freighter", "Freighter", "Civilian", A, False, "DS9", "Freighter", []),
    ("Asteroid", "Asteroid", "Neutral", U, False, "all", "Asteroid", []),
]


def _rows():
    out = []
    for d in shipdef_overrides.stock_definitions():
        p = parse_dauntless(d.dauntless)
        assert p.missing == () and p.errors == (), (d.shipFile, p)
        era = "all" if p.values["era"] == ("all",) else p.values["era"][0]
        assert p.values["era"] in (("all",), ("DS9", "DS9"))
        out.append((d.shipFile, p.values["title"], p.values["species"],
                    p.values["role"], p.values["playable"], era, d.iconName,
                    [v.name for v in p.variants]))
    return out


def test_stock_seed_equals_the_roadmap_appendix():
    assert _rows() == APPENDIX


def test_sixteen_playable_match_bridge_selection():
    from engine.bridge_selection import STOCK_PLAYER_SHIPS
    playable = {r[0] for r in APPENDIX if r[4]}
    assert playable == set(STOCK_PLAYER_SHIPS)


def test_fed_variant_registries_and_the_enterprise_script():
    by_id = {d.shipFile: parse_dauntless(d.dauntless).variants
             for d in shipdef_overrides.stock_definitions()}
    assert [(v.registry, v.script) for v in by_id["Sovereign"]] == [
        ("Sovereign", None), ("Enterprise", "Enterprise")]
    assert [v.registry for v in by_id["Galaxy"]] == ["Dauntless", "SanFrancisco", "Venture"]
    assert [v.registry for v in by_id["Nebula"]] == ["Berkeley", "Prometheus", "Khitomer", "Nightingale"]
    assert [(v.registry, v.script) for v in by_id["Akira"]] == [
        ("Geronimo", None), ("Devore", None)]
    assert [v.registry for v in by_id["Ambassador"]] == ["Zhukov", "Excalibur"]


def test_stock_definitions_are_unlisted():
    shipdef_overrides.stock_definitions()
    assert all_definitions() == []


def test_name_and_race_carry_title_and_species():
    d = {x.shipFile: x for x in shipdef_overrides.stock_definitions()}["CardHybrid"]
    assert (d.name, d.race) == ("Hybrid", "Cardassian")


def test_dict_literals_are_python_15_safe():
    """A mod author copies a section as a template into a file that must
    still load in the original BC's Python 1.5: no True/False, no f-strings
    inside any `<X>.dauntless = {...}` literal. (The module's own plumbing,
    e.g. `_listed=False`, is engine code and is not checked.)"""
    tree = ast.parse(Path(shipdef_overrides.__file__).read_text())
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == "dauntless"
                        for t in n.targets)]
    assert len(literals) == 33
    for lit in literals:
        for node in ast.walk(lit):
            assert not (isinstance(node, ast.Constant)
                        and isinstance(node.value, bool)), node.lineno
            assert not isinstance(node, ast.JoinedStr), node.lineno
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_ship_catalog_stock.py -v`
Expected: FAIL with `ImportError: cannot import name 'shipdef_overrides'`

- [ ] **Step 3: Write the stock file**

`engine/foundation/shipdef_overrides.py`, the complete content:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_ship_catalog_stock.py tests/unit/test_path_indirection.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/foundation/shipdef_overrides.py tests/unit/test_ship_catalog_stock.py
git commit -m "feat(foundation): stock ship metadata in shipdef_overrides.py"
```

---

### Task 5: The catalog: build, merge, membership, memo

**Files:**
- Create: `engine/ship_catalog/catalog.py`
- Modify: `engine/ship_catalog/__init__.py` (re-exports)
- Modify: `engine/foundation/__init__.py:149-159` (`reset()` invalidates the catalog)
- Modify: `tests/conftest.py:881-885` (invalidate in `_reset_leakable_engine_globals`)
- Test: `tests/unit/test_ship_catalog_merge.py`

**Interfaces:**
- Consumes:
  - `parse_dauntless`, `Variant` (Task 2)
  - `ShipDefinition`, `plugin_origin`, `all_definitions` (Task 3)
  - `shipdef_overrides.stock_definitions()` (Task 4)
  - `bridge_selection._stock_ship_stems()` and `_mod_ship_stems()`, both `{folded stem: stem}`
- Produces:
  - A frozen dataclass:

    ```
    CatalogEntry(ship_id, icon, source, origins, title, species, era, role,
                 playable, variants, missing, errors, raw_name, raw_race)
    ```

    with `.complete` and `.in_eras(era_ids)`.
  - `entries() -> list[CatalogEntry]`, sorted by `((title or ship_id).lower(), ship_id)`
  - `entry(ship_id) -> CatalogEntry | None`
  - `incomplete() -> list[CatalogEntry]`
  - `invalidate() -> None`
  - Internals that Task 7 reads: `_built() -> _Built(entries, unresolved: list[(ship_file, mod_name)], shared: list[(ship_id, [mod_name, ...])], stock_error: str | None)`
  - Test seam: `_stock_definitions()`

- [ ] **Step 1: Write the failing tests**

```python
"""engine.ship_catalog -- membership, per-key merge over stock, provenance,
memoisation. Stock is substituted through catalog._stock_definitions so each
test controls it; the fake install supplies the ships/*.py that exist."""
import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition, plugin_origin
from engine.ship_catalog import catalog
from engine.ship_catalog.schema import Variant
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401

FULL = {"title": "Galaxy", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}
ALL_MISSING = ("era", "role", "playable", "title", "species")


@pytest.fixture(autouse=True)
def _qb_clean():
    """RegisterQBShipMenu(qb=None) still records into quickbattle._registered,
    and conftest does not reset it."""
    quickbattle.reset()
    yield
    quickbattle.reset()


def _stock_def(ship_id, **dauntless):
    d = ShipDefinition("Federation", ship_id, None,
                       {"shipFile": ship_id, "name": ship_id}, _listed=False)
    d.dauntless = dict(dauntless)
    return d


def _mod_def(ship_file, mod="M", attr=None, dauntless=None, menu=True):
    with plugin_origin(mod, "custom/ships/%s.py" % ship_file.lower()):
        d = ShipDefinition("Fed", ship_file, 103,
                           {"shipFile": ship_file, "name": "Mod " + ship_file})
    if dauntless is not None:
        d.dauntless = dauntless
    if menu:
        d.RegisterQBShipMenu("Fed Ships", qb=None)
    if attr:
        setattr(foundation.ShipDef, attr, d)
    ship_catalog.invalidate()
    return d


@pytest.fixture
def stock(fake_install, monkeypatch):
    """Stock = Galaxy (complete) + Sovereign with an Enterprise script variant."""
    defs = [_stock_def("Galaxy", **FULL),
            _stock_def("Sovereign", **dict(FULL, title="Sovereign", variants=[
                {"name": "USS Sovereign", "registry": "Sovereign"},
                {"name": "USS Enterprise", "script": "Enterprise",
                 "registry": "Enterprise"}]))]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    quickbattle.reset()
    ship_catalog.invalidate()
    yield defs
    quickbattle.reset()
    ship_catalog.invalidate()


def test_stock_entries_are_complete_and_stock_sourced(stock):
    e = ship_catalog.entry("galaxy")
    assert e.ship_id == "Galaxy" and e.source == "stock" and e.origins == ()
    assert e.complete and e.era == ("DS9", "DS9") and e.playable is True
    assert [x.ship_id for x in ship_catalog.entries()] == ["Galaxy", "Sovereign"]


def test_missing_variant_script_is_dropped_with_an_error(stock):
    e = ship_catalog.entry("Sovereign")       # fake install has no Enterprise.py
    assert e.variants == (Variant("USS Sovereign", None, "Sovereign"),)
    assert any("ships/Enterprise.py not found" in x for x in e.errors)
    assert e.complete


def test_variant_script_that_exists_is_kept(stock, tmp_path):
    install_mod(tmp_path, "EntMod", {"scripts/ships/Enterprise.py": "# ship\n"})
    ship_catalog.invalidate()
    names = [v.name for v in ship_catalog.entry("Sovereign").variants]
    assert names == ["USS Sovereign", "USS Enterprise"]


def test_mod_def_over_a_stock_stem_wins_per_key(stock):
    _mod_def("Galaxy", mod="GalMod", attr="GalMod", dauntless={"title": "Galaxy Refit"})
    e = ship_catalog.entry("Galaxy")
    assert e.title == "Galaxy Refit" and e.species == "Federation" and e.complete
    assert e.source == "mod" and e.origins == (("GalMod", "GalMod"),)
    assert e.raw_name == "Mod Galaxy"


def test_mod_shipfile_case_drift_merges_onto_stock(stock):
    _mod_def("galaxy", mod="GalMod", dauntless={"role": "station"})
    e = ship_catalog.entry("GALAXY")
    assert e.ship_id == "Galaxy" and e.role == "station"
    assert len(ship_catalog.entries()) == 2


def test_mod_def_with_no_dauntless_inherits_stock_and_is_complete(stock):
    _mod_def("Galaxy", mod="GalMod")
    e = ship_catalog.entry("Galaxy")
    assert e.complete and e.title == "Galaxy" and e.source == "mod"


def test_in_place_replacement_without_a_shipdef_keeps_stock(stock, tmp_path):
    install_mod(tmp_path, "CG", {"scripts/ships/Galaxy.py": "# replaced\n"})
    ship_catalog.invalidate()
    e = ship_catalog.entry("Galaxy")
    assert e.source == "stock" and e.complete


def test_new_mod_ship_without_metadata_is_incomplete(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", attr="LCintrepidZZ")
    e = ship_catalog.entry("LCIntrepid")
    assert e.ship_id == "LCintrepid" and e.source == "mod"
    assert e.missing == ALL_MISSING and not e.complete
    assert e.origins == (("LC", "LCintrepidZZ"),)
    assert (e.raw_name, e.raw_race) == ("Mod LCintrepid", "Fed")
    assert ship_catalog.incomplete() == [e]


def test_partial_mod_metadata_lists_exactly_the_rest(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", dauntless={"era": "DS9", "role": "tactical"})
    assert ship_catalog.entry("LCintrepid").missing == ("playable", "title", "species")


def test_non_dict_dauntless_is_an_error_not_a_crash(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", dauntless="Federation")
    e = ship_catalog.entry("LCintrepid")
    assert e.missing == ALL_MISSING
    assert any("must be a dict" in x for x in e.errors)


def test_definition_not_on_a_qb_menu_is_not_an_entry(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", menu=False)
    assert ship_catalog.entry("LCintrepid") is None


def test_unresolved_script_is_excluded_and_recorded(stock):
    _mod_def("Ghost", mod="GhostMod")
    assert ship_catalog.entry("Ghost") is None
    assert catalog._built().unresolved == [("Ghost", "GhostMod")]


def test_two_mods_on_one_stem_merge_in_load_order_and_are_recorded(stock, tmp_path):
    install_mod(tmp_path, "A", {"scripts/ships/Defiant.py": "# ship\n"})
    _mod_def("Defiant", mod="ModA", dauntless=dict(FULL, title="A title"))
    _mod_def("Defiant", mod="ModB", dauntless={"title": "B title"})
    e = ship_catalog.entry("Defiant")
    assert e.title == "B title" and e.complete
    assert [o[0] for o in e.origins] == ["ModA", "ModB"]
    assert catalog._built().shared == [("Defiant", ["ModA", "ModB"])]


def test_entries_are_memoised_until_invalidate(stock):
    first = ship_catalog.entries()
    assert ship_catalog.entries()[0] is first[0]
    ship_catalog.invalidate()
    assert ship_catalog.entries()[0] is not first[0]


def test_a_new_mod_index_rebuilds(stock):
    first = ship_catalog.entries()
    mods.configure(mods.ModIndex(files={}, mods=[]))
    assert ship_catalog.entries()[0] is not first[0]


def test_foundation_reset_invalidates(stock):
    first = ship_catalog.entries()
    foundation.reset()
    assert ship_catalog.entries()[0] is not first[0]


def test_a_broken_stock_file_degrades_to_mod_entries_only(fake_install, monkeypatch, tmp_path):
    def boom():
        raise SyntaxError("bad stock")
    monkeypatch.setattr(catalog, "_stock_definitions", boom)
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC")
    ship_catalog.invalidate()
    assert [e.ship_id for e in ship_catalog.entries()] == ["LCintrepid"]
    assert "SyntaxError: bad stock" in catalog._built().stock_error


@pytest.mark.parametrize("era, selected, want", [
    (("DS9", "DS9"), ("DS9",), True),
    (("MOV", "DS9"), ("TNG",), True),         # inside the span
    (("MOV", "TNG"), ("DS9", "PIC"), False),
    (("all",), ("ENT",), True),
    (None, ("DS9",), False),                  # incomplete era never matches
])
def test_in_eras(stock, era, selected, want):
    import dataclasses
    e = dataclasses.replace(ship_catalog.entry("Galaxy"), era=era)
    assert e.in_eras(selected) is want
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_catalog_merge.py -v`
Expected: FAIL with `ImportError: cannot import name 'catalog'`

- [ ] **Step 3: Write the implementation**

`engine/ship_catalog/catalog.py`:

```python
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
```

Append to `engine/ship_catalog/__init__.py`:

```python
from engine.ship_catalog.catalog import (  # noqa: F401
    CatalogEntry, entries, entry, incomplete, invalidate)
```

In `engine/foundation/__init__.py` `reset()`, append at the end:

```python
    # The ship catalog snapshots ShipDefs; a reset leaves it describing
    # definitions that no longer exist.
    from engine import ship_catalog
    ship_catalog.invalidate()
```

In `tests/conftest.py` `_reset_leakable_engine_globals`, directly after the `mods.configure(None)` try-block (line ~885), add:

```python
    # Ship catalog memo (engine/ship_catalog/catalog.py): keyed on the mod
    # index, but a test that mutates a ShipDef in place would otherwise leak
    # a stale snapshot into the next test that happens to share the index.
    try:
        from engine import ship_catalog as _ship_catalog
        _ship_catalog.invalidate()
    except Exception:
        pass
```

- [ ] **Step 4: Run the tests to verify they pass, then the neighbours**

Run: `uv run pytest tests/unit/test_ship_catalog_merge.py tests/unit/test_foundation_*.py tests/unit/test_bridge_selection.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py engine/foundation/__init__.py tests/conftest.py tests/unit/test_ship_catalog_merge.py
git commit -m "feat(ship_catalog): merge stock and mod ShipDefs into catalog entries"
```

---

### Task 6: Species list and insignia (with the committed SVGs)

**Files:**
- Create: `native/assets/insignias/{federation,klingon,romulan,cardassian,ferengi}.svg`, copied from the spike branch
- Modify: `engine/ship_catalog/catalog.py` (add `species()` and `insignia_path()`)
- Modify: `engine/ship_catalog/__init__.py`
- Test: `tests/unit/test_ship_catalog_species.py`

**Interfaces:**
- Consumes: `tables.STOCK_SPECIES`, `Species` (Task 1); `entries()` (Task 5)
- Produces:
  - `species() -> list[Species]`: the stock eight, then mod-introduced species alphabetically with `flagship=None`. Each has `insignia` resolved.
  - `insignia_path(species: str) -> Path | None`

- [ ] **Step 1: Copy the insignias from the spike branch**

```bash
mkdir -p native/assets/insignias
for s in federation klingon romulan cardassian ferengi; do git show spike/quickbattle-setup:spikes/quickbattle-setup/insignias/$s.svg > native/assets/insignias/$s.svg; done
ls -la native/assets/insignias
```

Expected: five non-empty `.svg` files (about 1.9 to 23 KB each).

- [ ] **Step 2: Write the failing tests**

```python
"""Species list and insignia resolution (spec §4.4): committed SVG, then the
asset overlay (a mod-introduced species), then None (flagship icon)."""
from pathlib import Path

import pytest

from engine import paths, ship_catalog
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition, plugin_origin
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


def test_the_five_committed_insignias_exist():
    root = paths.project_asset_root() / "insignias"
    for s in ("Federation", "Klingon", "Romulan", "Cardassian", "Ferengi"):
        assert ship_catalog.insignia_path(s) == root / ("%s.svg" % s.lower())
        assert (root / ("%s.svg" % s.lower())).stat().st_size > 0


def test_no_insignia_for_kessok_civilian_neutral(fake_install):
    for s in ("Kessok", "Civilian", "Neutral", "", None):
        assert ship_catalog.insignia_path(s) is None


def test_overlay_supplies_a_mod_species_emblem(fake_install):
    _sdk, game_root = fake_install       # fake_install's game_asset -> game_root/rel
    emblem = game_root / "data" / "Icons" / "Species" / "Borg.png"
    emblem.parent.mkdir(parents=True)
    emblem.write_bytes(b"png")
    assert ship_catalog.insignia_path("Borg") == emblem


def test_committed_svg_beats_the_overlay(fake_install):
    _sdk, game_root = fake_install
    p = game_root / "data" / "Icons" / "Species" / "Federation.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"png")
    assert ship_catalog.insignia_path("Federation").suffix == ".svg"


def test_species_lists_stock_then_mod_introduced_alphabetically(
        fake_install, monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: [])
    install_mod(tmp_path, "M", {"scripts/ships/Cube.py": "# s\n",
                                "scripts/ships/Bug.py": "# s\n"})
    quickbattle.reset()
    for ship, sp in (("Cube", "Borg"), ("Bug", "Dominion")):
        with plugin_origin("M", "custom/ships/x.py"):
            d = ShipDefinition("Fed", ship, 103, {"shipFile": ship})
        d.dauntless = {"species": sp}
        d.RegisterQBShipMenu("Fed Ships", qb=None)
    ship_catalog.invalidate()
    got = ship_catalog.species()
    assert [s.name for s in got] == [
        "Federation", "Klingon", "Romulan", "Cardassian", "Ferengi",
        "Kessok", "Civilian", "Neutral", "Borg", "Dominion"]
    assert got[0].insignia is not None and got[0].flagship == "Sovereign"
    assert got[-1].flagship is None and got[-1].insignia is None
    quickbattle.reset()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_catalog_species.py -v`
Expected: FAIL with `AttributeError: module 'engine.ship_catalog' has no attribute 'insignia_path'`

- [ ] **Step 4: Write the implementation**

Append to `engine/ship_catalog/catalog.py`:

```python
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
```

Change the `__init__.py` catalog import to:

```python
from engine.ship_catalog.catalog import (  # noqa: F401
    CatalogEntry, entries, entry, incomplete, insignia_path, invalidate,
    species)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_catalog_species.py tests/unit/test_path_indirection.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add native/assets/insignias/federation.svg native/assets/insignias/klingon.svg native/assets/insignias/romulan.svg native/assets/insignias/cardassian.svg native/assets/insignias/ferengi.svg engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py tests/unit/test_ship_catalog_species.py
git commit -m "feat(ship_catalog): species list and in-tree insignias"
```

---

### Task 7: Boot report `describe()` and the host-loop line

**Files:**
- Modify: `engine/ship_catalog/catalog.py` (add `describe()`)
- Modify: `engine/ship_catalog/__init__.py`
- Modify: `engine/host_loop.py` (just after the `_fnd_text` print, ~line 9415)
- Test: `tests/unit/test_ship_catalog_describe.py`

**Interfaces:**
- Consumes: `_built()` and `_Built` (Task 5)
- Produces: `describe() -> str`, the boot report, or `""`. Never raises.

- [ ] **Step 1: Write the failing tests**

```python
"""ship_catalog.describe() -- the boot line (spec §5)."""
import pytest

from engine import ship_catalog
from engine.ship_catalog import catalog
from engine.ship_catalog.catalog import CatalogEntry, _Built


def _e(ship_id, source="stock", mod=None, complete=True):
    return CatalogEntry(
        ship_id=ship_id, icon=ship_id, source=source,
        origins=((mod, ship_id),) if mod else (), title=ship_id,
        species="Federation", era=("DS9", "DS9"), role="tactical",
        playable=True, variants=(),
        missing=() if complete else ("era",), errors=(),
        raw_name=ship_id, raw_race="Fed")


@pytest.fixture
def built(monkeypatch):
    holder = {}
    monkeypatch.setattr(catalog, "_built", lambda: holder["b"])
    def set_(entries, unresolved=(), shared=(), stock_error=None):
        holder["b"] = _Built(list(entries), list(unresolved), list(shared), stock_error)
    return set_


def test_stock_only_and_healthy_is_silent(built):
    built([_e("Galaxy"), _e("Akira")])
    assert ship_catalog.describe() == ""


def test_counts_and_incomplete_grouped_by_mod(built):
    built([_e("Galaxy"), _e("Defiant", "mod", "DCMPv2", False),
           _e("Avenger", "mod", "DCMPv2", False),
           _e("LCintrepid", "mod", "LC Intrepid Pack", False),
           _e("Fine", "mod", "Other")])
    assert ship_catalog.describe() == (
        "ship catalog: 1 stock, 4 mod; 3 incomplete "
        "(DCMPv2: 2, LC Intrepid Pack: 1)")


def test_complete_mods_omit_the_incomplete_clause(built):
    built([_e("Galaxy"), _e("Fine", "mod", "Other")])
    assert ship_catalog.describe() == "ship catalog: 1 stock, 1 mod"


def test_shared_unresolved_and_stock_error_lines(built):
    built([_e("Defiant", "mod", "ModB")],
          unresolved=[("XyzShip", "SomeMod")],
          shared=[("Defiant", ["ModA", "ModB"])],
          stock_error="SyntaxError: bad")
    assert ship_catalog.describe().splitlines() == [
        "ship catalog: 0 stock, 1 mod",
        "  shared stem 'Defiant': ModB over ModA",
        "  unresolved: XyzShip (SomeMod) -- ships/XyzShip.py not found",
        "  WARNING stock metadata failed to load: SyntaxError: bad",
    ]


def test_describe_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(catalog, "_built", boom)
    assert ship_catalog.describe() == "ship catalog: WARNING could not build: RuntimeError: x"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_catalog_describe.py -v`
Expected: FAIL with `AttributeError: module 'engine.ship_catalog' has no attribute 'describe'`

- [ ] **Step 3: Write the implementation**

Append to `engine/ship_catalog/catalog.py`:

```python
# ── boot report ────────────────────────────────────────────────────────────

def describe() -> str:
    """One boot line (+ indented details), or "" when there is nothing to
    say: stock only, every entry complete, no problems (spec §5)."""
    try:
        b = _built()
    except Exception as exc:  # noqa: BLE001 -- a boot report must not kill boot
        return "ship catalog: WARNING could not build: %s: %s" % (
            type(exc).__name__, exc)
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
        lines.append("  shared stem %r: %s" % (ship_id, " over ".join(reversed(names))))
    for ship_file, mod_name in b.unresolved:
        lines.append("  unresolved: %s (%s) -- ships/%s.py not found"
                     % (ship_file, mod_name, ship_file))
    if b.stock_error:
        lines.append("  WARNING stock metadata failed to load: %s" % b.stock_error)
    return "\n".join(lines)
```

Add `describe` to the `__init__.py` catalog import list.

In `engine/host_loop.py`, directly after:

```python
    _fnd_text = _foundation.describe(_fnd_report)
    if _fnd_text:
        print(_fnd_text, file=sys.stderr)
```

insert:

```python
    # Ship metadata catalog (engine/ship_catalog): built here, after every
    # Foundation plugin has run, so the report names mod ships that still
    # lack metadata. Report only -- nothing is gated until sub-project 3.
    from engine import ship_catalog as _ship_catalog
    _cat_text = _ship_catalog.describe()
    if _cat_text:
        print(_cat_text, file=sys.stderr)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_catalog_describe.py -v`
Expected: PASS (all)

- [ ] **Step 5: Verify against the real install and the real mods (manual)**

```bash
DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" DAUNTLESS_SDK_DIR="/Users/mward/Documents/Star Trek Bridge Commander/sdk" DAUNTLESS_MODS_DIR=/Users/mward/Documents/Projects/bc_dauntless/mods uv run python -c "from engine import paths, mods, foundation, ship_catalog; paths.configure(paths.resolve()); mods.install(); foundation.load_plugins(); print(ship_catalog.describe()); print(len(ship_catalog.entries()))"
```

Expected:
- A head line reading `33 stock`, with the mod count and incomplete count matching the installed packs (DCMPv2 and LC Intrepid Pack, all incomplete).
- No `WARNING`.
- If a plugin fails to import `App` or `Foundation` in this bare process, record the output verbatim in the task report. Do **not** change engine code to make it pass: the host boot installs the SDK finder first.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py engine/host_loop.py tests/unit/test_ship_catalog_describe.py
git commit -m "feat(ship_catalog): boot report line after Foundation plugins"
```

---

### Task 8: Asset-backed check, CLAUDE.md row, full gate

**Files:**
- Create: `tests/integration/test_ship_catalog_stock_content.py`
- Modify: `CLAUDE.md` (one row in the "Key reference material" table, after the "Ship → bridge matrix" row)

**Interfaces:**
- Consumes: `shipdef_overrides.stock_definitions()` (Task 4); the real configured content

- [ ] **Step 1: Write the test**

```python
"""Against the REAL configured BC content: every stock id, variant script and
icon in shipdef_overrides.py exists. Skipped when no content is configured."""
import pytest

from engine import paths
from engine.foundation import shipdef_overrides


def _stems(rel_dir, pattern):
    try:
        d = paths.sdk_scripts() / rel_dir if pattern == "*.py" else paths.game_asset(rel_dir)
    except Exception:
        pytest.skip("no BC content configured")
    if not d.is_dir():
        pytest.skip("no BC content at %s" % d)
    return {p.stem.lower() for p in d.glob(pattern)}


def test_every_stock_id_and_variant_script_is_a_real_ship_script():
    stems = _stems("ships", "*.py")
    for d in shipdef_overrides.stock_definitions():
        assert d.shipFile.lower() in stems, d.shipFile
        for v in d.dauntless.get("variants", []):
            if "script" in v:
                assert v["script"].lower() in stems, (d.shipFile, v)


def test_every_stock_icon_exists():
    icons = _stems("data/Icons/Ships", "*.tga")
    for d in shipdef_overrides.stock_definitions():
        assert d.iconName.lower() in icons, (d.shipFile, d.iconName)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_ship_catalog_stock_content.py -v`
Expected: PASS when content is configured, SKIP otherwise.

- [ ] **Step 3: Add the CLAUDE.md row**

Insert this row after the "Ship → bridge matrix (auto player bridge)" row:

```markdown
| Ship metadata catalog | `engine/ship_catalog/`, `engine/foundation/shipdef_overrides.py`, `docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md` | Dauntless-owned per-ship metadata (era span, role, playable, title, species, named variants) for Quick Battle. It lives as a `dauntless` dict on the Foundation `ShipDef`: stock ships in the hand-edited, committed `shipdef_overrides.py` (unlisted defs, never in `all_definitions()`), and mod ships in their own `Custom/Ships`, with gate answers later written into the mod as `zz_Dauntless_<shipFile>.py`. **Read metadata ONLY through `engine.ship_catalog`** (`entries()`, `entry()`, `incomplete()`, `species()`, `insignia_path()`): it merges stock then mods per key and validates. Insignias are committed in `native/assets/insignias/`. ⚠️ Keep the stock dict literals Python 1.5-safe (1/0, never True/False). ⚠️ A variant's `script` spawns a separate ship script; `variants[0]` (class default) never has one. |
```

- [ ] **Step 4: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, no failure outside `tests/known_failures.txt`. If anything new fails, it is a regression from this branch: stop and fix it. Never call it "pre-existing" by eye.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add tests/integration/test_ship_catalog_stock_content.py CLAUDE.md
git commit -m "test(ship_catalog): stock seed against real content; CLAUDE.md row"
```
