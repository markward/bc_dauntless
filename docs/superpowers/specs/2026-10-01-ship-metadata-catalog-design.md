# Ship metadata and the ship catalog — Design

**Status:** spec, awaiting review
**Date:** 2026-10-01
**Programme:** Quick Battle redesign, sub-project 1 of 3.
`2026-10-01-quickbattle-redesign-roadmap.md` is the authority. Its "Standing
decisions" are settled and are not re-opened here.
**Consumers:** sub-project 2 (setup screen and battle start) and sub-project 3
(mod metadata gate). Neither is built here. This spec defines what they read.

## Intent

Dauntless needs its own metadata for every ship definition: era span, role,
playable, named variants, title and species. BC's own data cannot carry these.
This sub-project decides:

- where the metadata lives,
- how stock ships and mod ships declare it,
- which source wins when several do,
- and the single catalog API that sub-projects 2 and 3 read.

**Success looks like this:**

- Sub-projects 2 and 3 each call `engine.ship_catalog` and never read a ShipDef,
  a stock file or a mod file themselves.
- The 33 stock entries come out with exactly the roadmap appendix's values.
- A mod ship with no metadata comes out as *incomplete*, naming exactly which
  fields are missing.

> **Amended by sub-project 3** (`2026-10-01-mod-ships-screen-design.md` §2):
> - Ships group into classes by a free-text `variant_of` class name, with a
>   `class_default`.
> - `variants[0]` may be name-only.
> - `Variant` gains `playable`.
> - The API gains a per-ship level: `ShipRecord`, `ships()` and
>   `incomplete_ships()`.

## Decisions taken in the brainstorm (2026-10-01)

| # | Question | Decision |
|---|---|---|
| D1 | How does a mod declare metadata? | **On its Foundation `ShipDef`.** There is no sidecar manifest file, because metadata must not end up in pockets all over the place. |
| D2 | Where is stock metadata? | **An engine-owned, committed `shipdef_overrides.py`** with one section per stock ship, following the `hardpoint_overrides.py` pattern. Stock ships get real `ShipDefinition` objects there, the way Foundation's own `StaticDefs.py` re-registers them. |
| D3 | Where do the gate's answers for a mod ship go? | **Into the mod itself**, as a generated `Custom/Ships/` script that sub-project 3 writes. There is no user file beside `settings.json`. |
| D4 | Can a player edit **stock** metadata in-game? | **No.** Stock values change only by editing `shipdef_overrides.py`, which goes through code review. |
| D5 | A named ship that exists both as a hull-name swap and as a separate SDK script (USS Enterprise) | **Spawn the separate script.** A variant can carry both a `script` and a `registry`. |
| D6 | Species insignia artwork | **Committed in-tree** under `native/assets/insignias/`. It cannot be distributed separately. |
| D7 | Mandatory fields on a mod ship | **Era, role, playable, title and species. Nothing is inferred.** Variants are optional. |
| D8 | Architecture | **A derived, read-only catalog view** over the ShipDefs (approach 1 of 3). |

## 1. Data model: the `dauntless` attribute

All of a definition's Dauntless metadata lives in **one attribute, `dauntless`,
on the ShipDef, holding a dict.**

Why one namespaced attribute rather than five plain ones:

- `ShipDefinition.species` is already taken. It is Foundation's SDK species int
  (`App.SPECIES_GALAXY`), which drives AI and networking.
- One name cannot collide with an attribute Foundation or FoundationTech adds
  later.
- The gate's generated file has exactly one thing to set.

The dict uses Python 1.5-safe literals only (no `True`/`False`, no f-strings).
A Dauntless-aware mod therefore still loads in the original BC, where real
Foundation simply keeps the extra attribute.

```python
Foundation.ShipDef.DCMPDefiant.dauntless = {
    'title':    'Defiant',
    'species':  'Federation',
    'era':      ('DS9', 'DS9'),
    'role':     'tactical',
    'playable': 1,
    'variants': [
        {'name': 'USS Defiant', 'registry': 'Defiant'},
    ],
}
```

| Key | Type | Rules |
|---|---|---|
| `title` | non-empty str | The human-friendly name. Ours, not BC's `Ships.tgl`. |
| `species` | non-empty str | Free text. A value not in the stock species table creates a new species (see §4). Compared case-insensitively. |
| `era` | `'all'`, an era id, or `(from, to)` / `[from, to]` | Era ids: `ENT TOS MOV TNG DS9 PIC DISC`. A bare id `X` means `(X, X)`. `from` must not come after `to`. |
| `role` | str | `tactical`, `auxiliary`, `station` or `automated`. Compared case-insensitively. |
| `playable` | `0`/`1` (bools accepted) | Governs "Set as player ship". |
| `variants` | list of variant dicts | Optional. `[0]` is the class default. |

**Variant dict:**

| Key | Rules |
|---|---|
| `name` | Required, non-empty, for example `'USS Venture'`. Unique within the definition. |
| `script` | Optional. A `ships/<script>.py` to spawn instead of the definition's own script. It must resolve, in the stock tree or a mod. |
| `registry` | Optional. The hull-name decal registry: the `Masks/<registry>/` folder `hull_decals` resolves, which is the stem of BC's `ReplaceTexture(…, "ID")` path. Not checked for existence: Galaxy, Nebula and Akira have no masks yet and render nameless by design. |

A variant needs **at least one of** `script` and `registry`. A name with
neither would spawn an unnamed class default under a label it does not show.

**The class default (`variants[0]`) must not carry a `script`.** The default
*is* the definition, so it spawns the definition's own script. This is why
Akira's default "USS Geronimo" is registry-only, and `ships/Geronimo.py` stays
campaign-only (see §7).

**Era and role display data is not in mod files.** Names, tags ("DS9 · VOY")
and year ranges live in the catalog's own tables (§4), so a renamed era never
breaks a mod.

## 2. Where each layer lives

| Layer | File | Written by |
|---|---|---|
| Stock | `engine/foundation/shipdef_overrides.py` (committed) | Hand-edited by us, reviewed |
| Mod | The mod's own `scripts/Custom/Ships/*.py`, setting `ShipDef.<X>.dauntless` | The mod author |
| Gate answers | `scripts/Custom/Ships/zz_Dauntless_<shipFile>.py`, inside the mod | Sub-project 3 (§6 fixes its contract) |

### 2.1 The stock file

`shipdef_overrides.py` reads like a Foundation `Custom/Ships` script, so a mod
author can copy a section as a template. It is **hand-edited**. Unlike
`hardpoint_overrides.py` it is not machine-owned, because nothing in-game writes
to it (D4).

```python
Galaxy = _stock("Galaxy", race="Fed", iconName="Galaxy")
Galaxy.dauntless = {
    'title': 'Galaxy', 'species': 'Federation', 'era': 'DS9',
    'role': 'tactical', 'playable': 1,
    'variants': [
        {'name': 'USS Dauntless',     'registry': 'Dauntless'},
        {'name': 'USS San Francisco', 'registry': 'SanFrancisco'},
        {'name': 'USS Venture',       'registry': 'Venture'},
    ],
}
```

`_stock(...)` builds a real `ShipDefinition`, so stock and mod ships are one
model. These definitions are deliberately **unlisted**:

- They are not added to `shipdef._ALL_DEFINITIONS`.
- They are not registered into QuickBattle's tables.
- They are not assigned onto `Foundation.ShipDef`.

Three existing readers of `all_definitions()` would otherwise change
behaviour:

- `bridge_selection._mod_player_ship_files`
- `shipdef.icon_name_for_script`, which feeds `species_icons`
- `foundation.describe`

BC's QuickBattle tables already hold every stock ship, so a stock
`register()` would only produce 30 name collisions. The file exposes
`stock_definitions() -> list`, in file order.

`ShipDefinition.__init__` gains a keyword-only `_listed=True`. `_stock` passes
`False`. This is the only change to the Foundation surface, apart from adding
`"dauntless"` to `_KNOWN` so a mod's `dauntless` is not reported as an unknown
attribute.

The stock file holds **all 33 roadmap-appendix entries**, with these iconNames
where the stem differs from the id: Shuttle → `FedShuttle`, EscapePod →
`LifeBoat`, Decoy → `ProbeType2`, CardHybrid → `Hybrid`. Variants per §7.

### 2.2 Provenance

The catalog must know **which mod** declared a definition, and under which
`Foundation.ShipDef` attribute name. The gate writes into that mod, under that
name.

- `foundation/loader.py` sets a module-level "current plugin" context
  (`mod_name`, index key) around each `runpy.run_path`.
- `ShipDefinition.__init__` copies it into a private `_origin`. Underscore
  attributes already bypass `unknown_attributes`.
- The attribute name is recovered at catalog build by an identity search of
  `Foundation.ShipDef.__dict__`.

## 3. Merge and membership

**Identity is the script stem**: `shipFile` for a mod, the id for stock. It is
compared case-folded, because mod authors spell `shipFile` inconsistently (see
`icon_name_for_script`). The entry's `ship_id` keeps the first spelling seen,
which is stock's when stock is involved.

**Which definitions are entries:**

- Every stock definition.
- Every **listed** mod `ShipDefinition` that registered for a QuickBattle menu
  (`menuGroup` or `playerMenuGroup` is not `None`). That is the set the picker
  shows today.
- A mod definition whose script does not resolve (`ships/<shipFile>.py` in
  neither the stock tree nor the mod index) is **not** an entry. It is counted
  in the boot report as `unresolved`.

**Merge, per key of the `dauntless` dict:**

1. Start from the stock section, if the stem is a stock ship.
2. Apply each mod definition for the same stem, in plugin load order (loader
   filename order). Each key present wins.

The result is that:

- A mod that **replaces a stock ship in place** without a ShipDef (an in-place
  `ships/Sovereign.py`) keeps the stock entry unchanged.
- One whose ShipDef sets nothing inherits all of it, so it is never gated.
- One that sets only `title` changes only the title.

**Two mods defining the same stem** merge in load order. Each such stem is
listed in the boot report, because the same rule for files is reported as a
conflict by `mods.describe`.

`source` on the entry is `"stock"` when no mod definition shares the stem,
and `"mod"` otherwise, even if that mod definition sets no `dauntless` keys. `origins` lists every contributing mod in order. The gate
writes to the **last** one, the one whose values won.

## 4. The catalog API: `engine/ship_catalog/`

One package. Everything else in the engine reads ship metadata through it.

```
engine/ship_catalog/
    __init__.py     # the public API below, re-exported
    tables.py       # ERAS, ROLES, STOCK_SPECIES: display data, pure constants
    schema.py       # parse_dauntless(): dict -> (values, missing, errors); pure
    catalog.py      # build, merge, memo, describe()
```

### 4.1 Tables

```python
Era     = namedtuple("Era", "id name tag start end")    # years, from <= y < end
ERAS    = (Era("ENT", "Pre Federation", "ENT", 2140, 2240), ...,
           Era("DISC", "Distant Future", "DISC", 2500, 3200))
DEFAULT_ERAS = ("DS9",)                                  # Quadrant Wars

Role    = namedtuple("Role", "id label")
ROLES   = (Role("tactical", "Tactical"), Role("auxiliary", "Auxiliary"),
           Role("station", "Station"), Role("automated", "Automated / Unmanned"))

Species = namedtuple("Species", "name flagship insignia")  # insignia: Path | None
```

`STOCK_SPECIES` holds, in pill order, Federation, Klingon, Romulan, Cardassian,
Ferengi, Kessok, Civilian and Neutral, with the spike's flagships (Sovereign,
Vorcha, Warbird, Keldon, Marauder, KessokHeavy, Freighter, Asteroid). The first
five have insignia stems.

### 4.2 Records

```python
@dataclass(frozen=True)
class Variant:
    name: str
    script: str | None
    registry: str | None

@dataclass(frozen=True)
class CatalogEntry:
    ship_id: str            # script stem, display spelling
    icon: str               # iconName stem, data/Icons/Ships/<icon>.tga
    source: str             # "stock" | "mod"
    origins: tuple          # ((mod_name, shipdef_attr | None), ...) in load order
    # metadata; None when missing or invalid
    title: str | None
    species: str | None     # canonical spelling (stock table's when it matches)
    era: tuple | None       # (from_id, to_id), or ("all",)
    role: str | None        # role id
    playable: bool | None
    variants: tuple         # of Variant; () when none
    # gate support
    missing: tuple          # mandatory keys absent or invalid, in D7 order
    errors: tuple           # human-readable, one per invalid value or variant
    raw_name: str           # ShipDef.name: a suggestion source for the gate
    raw_race: str | None    # ShipDef.race: a suggestion source for the gate

    @property
    def complete(self) -> bool: ...          # not self.missing
    def in_eras(self, era_ids) -> bool: ...  # "all" always matches; span overlap otherwise
```

An invalid value is treated like an absent one: the key lands in `missing`,
with a line in `errors`. An invalid **variant** is dropped with an `errors`
line. Because variants are optional, that never makes an entry incomplete.

### 4.3 Functions

| Function | Returns |
|---|---|
| `entries()` | Every entry, complete or not, sorted by `(title or ship_id).lower()` |
| `entry(ship_id)` | One entry by case-folded stem, or `None` |
| `incomplete()` | `[e for e in entries() if not e.complete]`, which is the gate's work list |
| `species()` | `STOCK_SPECIES`, then any species used by an entry but not in the table, alphabetical, with insignia per §4.4 and flagship `None` |
| `insignia_path(species)` | `Path`, or `None` |
| `invalidate()` | Drops the memo. The gate calls it after writing, and `foundation.reset()` calls it |
| `describe()` | The boot report line, or `""` |

**Memoisation** follows `bridge_selection`: the build is cached against the
identity of `mods.current()` and dropped by `invalidate()`. Entries are
**snapshots**: mutating a ShipDef after the build is invisible until
`invalidate()`.

**Never raises.** A broken stock section or mod value degrades to `errors` or
`missing` on that entry. `catalog.py` wraps the stock import itself. If the
whole stock file fails, the catalog holds mod entries only, and `describe()`
says so.

### 4.4 Insignia resolution

For a species, the first that exists wins:

1. `paths.project_asset_root() / "insignias" / <stem>.svg`, where stem is the
   lowercased species name. These are committed (D6): the spike's five cleaned
   SVGs.
2. `paths.game_asset("data/Icons/Species/<Species>.svg")`, then `.png` and
   `.tga`. This is how a mod that introduces a species ships its emblem through
   the overlay.
3. `None`. The screen shows the flagship's icon, or the first entry's icon for a
   species with no flagship.

Paths are resolved at call time, never at import (the CLAUDE.md path rule).

## 5. Boot

No new boot step is required. The catalog builds lazily on first use, which is
always after `foundation.load_plugins()` at `host_loop.py` ~9412. The one
addition: right after the Foundation report there, print
`ship_catalog.describe()` to stderr when it is non-empty:

```
ship catalog: 33 stock, 15 mod; 15 incomplete (DCMPv2: 12, LC Intrepid Pack: 3)
  shared stem 'Defiant': ModB over ModA
  unresolved: XyzShip (SomeMod) -- ships/XyzShip.py not found
```

A mod definition over a **stock** stem is the normal override path and is not
reported. Only mod-over-mod is.

The line is empty only when there are no mod entries, no problems, and the
stock file loaded. Until sub-project 3 ships, incomplete mod ships **are not
blocked**: today's panel never reads the catalog, so nothing changes for the
player.

## 6. Contract for sub-project 3 (the gate's file)

Fixed here so the catalog's merge and the gate's writer agree:

- Path: `<mod content root>/scripts/Custom/Ships/zz_Dauntless_<shipFile>.py`,
  using the `Scripts`/`Custom`/`Ships` spelling the mod already uses. The `zz_`
  prefix sorts it after the author's files, so the loader runs it last.
- Body, Python 1.5-safe, guarded so it is harmless in the original BC:

  ```python
  import Foundation
  if hasattr(Foundation.ShipDef, 'DCMPDefiant'):
      d = Foundation.ShipDef.DCMPDefiant
      if not hasattr(d, 'dauntless'):
          d.dauntless = {}
      d.dauntless.update({'era': ('DS9', 'DS9'), 'role': 'tactical', ...})
  ```
- It writes only the keys the user answered. An author's later update that adds
  real metadata still loses to the user's answers. That is accepted: the user
  made a deliberate choice.
- After writing it, the gate must register the file in the mod index (in the
  manner of `mods.register_game_file`, an SDK-target sibling) and re-run that
  one script, or ask for a reboot. That choice belongs to sub-project 3. Either
  way it calls `ship_catalog.invalidate()`.

## 7. Stock seed

The roadmap appendix, verbatim, as the 33 entries. Every era is `'DS9'` except
Asteroid (`'all'`), and the role ids map from the appendix's labels. Variants,
after D5 and the §1 class-default rule:

| ship_id | Variants (`[0]` = class default) |
|---|---|
| Akira | USS Geronimo (registry Geronimo) · USS Devore (registry Devore) |
| Ambassador | USS Zhukov (registry Zhukov) · USS Excalibur (registry Excalibur) |
| Galaxy | USS Dauntless · USS San Francisco · USS Venture (registries Dauntless, SanFrancisco, Venture) |
| Nebula | USS Berkeley · USS Prometheus · USS Khitomer · USS Nightingale (registries by the same stems) |
| Sovereign | USS Sovereign (registry Sovereign) · **USS Enterprise (script Enterprise, registry Enterprise)** |

Every registry stem is BC's own: it appears in an SDK `ReplaceTexture(…, "ID")`
call (checked 2026-10-01).

**Consequence of the class-default rule:** `ships/Geronimo.py` (different
hardpoints from Akira) is not reachable from the catalog. Picking USS Geronimo
spawns `Akira.py` named Geronimo, which is exactly what BC's `MissionLib`
"default NCC" does. The other separate-script ships (Peregrine, RanKuf,
MatanKeldon, E2M0Warbird, BombFreighter, BiranuStation) are not seeded, because
the appendix lists only `ReplaceTexture` names. Adding one later is a one-line
edit to `shipdef_overrides.py`.

## 8. What BC's own data keeps doing

Nothing in BC's own data is rewritten. Our title and species are for our UI and
filters only.

| BC data | Status |
|---|---|
| `Ships.tgl` names and descriptions | Unchanged. Titles come from the catalog; sub-project 2 may still read `Ships.tgl` descriptions as bios. |
| `Multiplayer/SpeciesToShip` and `SetSpecies` ints | Unchanged. They drive AI, networking and `species_icons`. |
| QuickBattle `ST_*`, `g_dShipNameToType` and the detail tables | Unchanged. Foundation's `register()` still writes mod rows. Sub-project 2 decides how much of QuickBattle survives. |
| `bridge_selection.STOCK_PLAYER_SHIPS` | Unchanged **in this sub-project**. It agrees with the stock `playable` values (16 ships). Switching it to `catalog.playable` is a follow-up for after sub-project 3: before the gate exists, every mod ship is incomplete and would drop out of the bridges panel. |

## 9. Testing

Pure units first; the only fixtures are fake ShipDefs and a temp mod tree.

| Test file | Covers |
|---|---|
| `tests/unit/test_ship_catalog_schema.py` | `parse_dauntless`: every key's valid and invalid forms; era shorthand, span order and `'all'`; role and species folding; the variant rules (name required and unique, script/registry, class default without a script); invalid values land in `missing` plus `errors`; bools accepted for `playable` |
| `tests/unit/test_ship_catalog_stock.py` | The stock file yields exactly the 33 appendix rows (a literal table in the test, so a drift fails loudly); every entry is complete; stock definitions are unlisted (`all_definitions()` is empty after the import; `bridge_selection` and `icon_name_for_script` are unaffected); Python 1.5-safe literals (an `ast` check: no `True`/`False` names) |
| `tests/unit/test_ship_catalog_merge.py` | Membership (only QB-registered listed mod definitions); per-key merge over stock; an in-place replacement keeps stock; two mods on one stem, in order, reported; an unresolved script is excluded and reported; provenance (`origins`, the `shipdef_attr` lookup); `incomplete()`; memo invalidation on an index change and on `invalidate()`; `foundation.reset()` invalidates |
| `tests/unit/test_ship_catalog_species.py` | `species()` order and mod-introduced species; the three-step insignia resolution, including the overlay; the five committed SVGs exist |
| `tests/unit/test_ship_catalog_describe.py` | The boot line's content for each case, and the empty case |
| `tests/unit/test_foundation_loader.py` (extend) | `_origin` is set during `runpy` and cleared after, including after a failing script |
| `tests/integration/test_ship_catalog_installed_mods.py` | Asset-backed: with the stock content root configured, every stock id and every variant `script` resolves to a real `ships/<id>.py`. Skipped without content, following the existing convention. |

`scripts/check_tests.sh` is the gate.

## Not in scope

- The setup screen, presets, groups and spawning (sub-project 2).
- The gate's UI, timing and writer (sub-project 3). Only its file contract (§6)
  is fixed here.
- Switching `bridge_selection` to `playable` (see §8).
- Reading hull and shield values for the scale bars. Sub-project 2 reads them
  from **loaded** ship properties, per the roadmap.
- Authoring hull-name masks for Galaxy, Nebula and Akira.
