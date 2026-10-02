# Mod Ships Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pre-boot "Mods" screen. In **gate** mode it collects missing Dauntless metadata for mod ships and writes it into each mod. In **home** mode it is a read-only list of installed mod ships, reached by `--mods` or by a pause-menu relaunch. Behind it are a class-by-name catalog model, CEF keyboard input, and the Foundation `SubMenu` fix.

**Architecture:**
- **Catalog:** builds one `ShipRecord` per ship (sub-project 1's per-key merge, unchanged), then forms classes from records by a free-text `variant_of` name, with one starred `class_default`.
- **Screen:** a `Panel` state machine (`engine/ui/mods_screen_panel.py`) with a dumb CEF page. It runs in a pre-boot pump loop extracted from the first-run picker's.
- **Writing:** answers go to `zz_Dauntless_<shipFile>.py` in the mod, which is registered in the mod index and re-run in-process.
- **Native:** a GLFW text-event queue feeds `CefBrowserHost::SendKeyEvent`. A relaunch request stored in the `platform` library makes `host_main` `execv` itself after `Py_FinalizeEx`.

**Tech Stack:** Python 3.11 (engine, pytest via `uv run pytest`), C++20 (GLFW, CEF, pybind11, gtest), plain JS/CSS for the CEF page.

**Spec:** `docs/superpowers/specs/2026-10-01-mod-ships-screen-design.md` (read it first). Related:
- sub-project 1: `docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md`
- the roadmap: `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md`
- the design spike: branch `spike/mod-metadata-gate`, `spikes/mod-metadata-gate/` (look with `git show spike/mod-metadata-gate:spikes/mod-metadata-gate/app.js`)

## Global Constraints

**Git (shared checkout)**
- Work on branch `feat/qb-mod-gate`, in worktree `.claude/worktrees/qb-mod-gate`. Run `git branch --show-current` before every commit. **Never commit to `main`.**
- Stage with explicit pathspecs only. These are **banned**: `git add -A`, `git add .`, `git stash`, `git checkout -- <path>`, `git restore`, `git clean`, `git reset --hard`.
- To prove a test catches a bug, back the file up with `cp`, mutate it, then restore with `cp` and `diff` the result.

**Paths and scripts**
- Resolve paths at use; never capture them at import. Never spell `game` or `sdk` as a path segment (`tests/unit/test_path_indirection.py`).
- Generated `zz_` files must be **Python 1.5-safe**: no `True`/`False`, no f-strings, `1`/`0` for booleans. They must also be guarded with `hasattr(Foundation.ShipDef, '<attr>')`.

**Boot behaviour**
- **Never block or break boot.** No CEF means no screen. Any exception in the screen path is logged with `dev_mode.log_swallowed` and boot continues as "skip for now".

**UI**
- Off-screen CEF has no native `<select>`, no native tooltips and no drag-and-drop. Pickers are page-drawn. The style is the cp-* family from `native/assets/ui-cef/css/configuration_panel.css`.
- Era display leads with the **code** (`DS9 · VOY`); the stored id for era 5 stays `DS9`.

**Build and test**
- One build tree, `build/`. Build with `cmake --build build -j`. Never run cmake from inside `native/`.
- After a C++ change, rebuild before running pytest. A stale `.so` shows up as a missing attribute on `_dauntless_host`.
- Run the gate, `scripts/check_tests.sh`, before calling the branch done. Never call a failure "pre-existing" by eye.

## Review Focus

1. **A player editing several ticked rows, then unticking one.** Edits must apply only while the row is ticked. Pinned in Task 8, `test_edit_on_unticked_row_touches_only_that_row`.
2. **A class with members across two mods.** Classes cross mod boundaries. The catalog must form one entry, and the gate's default star must consider both mods' rows. Pinned in Task 5, `test_class_spans_two_mods`, and Task 8, `test_star_spans_mods`.
3. **A write that fails partway** (the second file of three is read-only). The files already written stay and are correct, the screen shows the error, and Skip and Quit still work. Pinned in Task 8, `test_writer_error_is_shown_and_skip_still_works`.
4. **Keyboard events arriving while the page has not loaded.** They are dropped harmlessly: `cef_send_key_event` with no browser is a no-op. Pinned in Task 10's C++ guard, `if (!g_client || !g_client->browser()) return;`, mirroring `send_mouse_click`.
5. **Relaunch argv when the player already passed `--mods`.** The flag must not double. Pinned in Task 11, `RelaunchArgv.DoesNotDoubleAnExtraArg`.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/foundation/shipdef.py` (modify) | Read `SubMenu`/`SubSubMenu` from `details` |
| `engine/ship_catalog/schema.py` (modify) | `variant_of`, `class_default`; `Variant.playable`; name-only class default |
| `engine/ship_catalog/catalog.py` (modify) | `ShipRecord`, `ships()`, class formation, `resolve_class_default`, `combine_class`, `incomplete_ships`, `suggestions`, `skip_for_session`/`skipped`/`reset_session` |
| `engine/ship_catalog/__init__.py` (modify) | Re-exports |
| `engine/foundation/quickbattle.py` (modify) | Skip-aware button injection |
| `engine/mods.py` (modify) | `register_sdk_file`, `MODS_SCREEN_FLAG`, `mods_screen_requested` |
| `engine/ship_catalog/gate_writer.py` (create) | Render, write, register and run `zz_` files |
| `engine/ui/mods_screen_panel.py` (create) | The screen's state machine |
| `engine/ui/mods_screen.py` (create) | Orchestration: decide the mode, build the panel, run it, handle the outcome |
| `native/assets/ui-cef/{index.html, js/mods_screen.js, css/mods_screen.css}` (modify/create) | The page |
| `native/src/renderer/{include/renderer/text_input.h, text_input.cc}` (create) | Text-event queue and GLFW→Windows key mapping |
| `native/src/renderer/{include/renderer/window.h, window.cc}` (modify) | Char/key callbacks, `drain_text_events()` |
| `native/src/ui_cef/{cef_lifecycle.h, cef_lifecycle.cc}` (modify) | `send_key_event` |
| `native/src/platform/{relaunch.h, relaunch.cc}` (create) | Relaunch request store, argv builder, exec |
| `native/src/host/host_bindings.cc` (modify) | `drain_text_events`, `cef_send_key_event` (plus stub), `request_relaunch` |
| `native/src/host/host_main.cc` (modify) | Relaunch after `Py_FinalizeEx` |
| `engine/host_io.py` (modify) | Add the three bindings to `_REQUIRED_BINDINGS` |
| `engine/host_loop.py` (modify) | `_run_preboot_panel` (extracted, with keyboard forwarding); the Mods screen after `load_plugins`; the pause-row handler |
| `engine/ui/first_run_panel.py` (modify) | `teardown_script` |
| `engine/ui/pause_menu.py` (modify) | The "Quit and Manage Mods" row |
| `tests/…` | Per task |

---

### Task 0: Worktree runtime setup (no commit)

The worktree has no `settings.json`, no `mods/`, no venv and no build. Both suites need all four. The detail is in memory `feedback_worktrees_runtime_deps`.

- [ ] **Step 1: Copy the per-tree files and set up the venv**

```bash
cp /Users/mward/Documents/Projects/bc_dauntless/settings.json .
mkdir -p mods
cp -Rc /Users/mward/Documents/Projects/bc_dauntless/mods/. mods/
uv sync --extra dev
```

- [ ] **Step 2: Configure and build**

```bash
cmake -B build -S . -DPython3_EXECUTABLE=/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/qb-mod-gate/.venv/bin/python3
cmake --build build -j
```

Expected: `[100%] Built target _dauntless_host` and `build/dauntless` exists.

- [ ] **Step 3: Get a baseline**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures`. If it is not clean, stop and report before Task 1.

---

### Task 1: Foundation shim reads `SubMenu`/`SubSubMenu` from `details`

**Files:**
- Modify: `engine/foundation/shipdef.py` (`ShipDefinition.__init__`, where `self.SubMenu = None` / `self.SubSubMenu = None` are set)
- Test: `tests/unit/test_foundation_shipdef_submenu.py`

**Interfaces:**
- Produces: `ShipDefinition(race, abbrev, species, {"SubMenu": "X", "SubSubMenu": "Y"})` gives `.SubMenu == "X"` and `.SubSubMenu == "Y"`.

- [ ] **Step 1: Write the failing test**

```python
"""Every corpus mod passes SubMenu in the details dict:
FedShipDef(abbrev, species, {'name':..., 'SubMenu': SubMenu}). The shim
used to read only name/iconName/shipFile from it, so nested QuickBattle
menus never appeared live -- the menu-injection tests set the attribute
directly and could not see it."""
import pytest

from engine import foundation
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def test_submenu_and_subsubmenu_come_from_details():
    d = ShipDefinition("Fed", "DCMPDefiant", 103,
                       {"name": "Defiant", "shipFile": "DCMPDefiant",
                        "SubMenu": "Defiant Class", "SubSubMenu": "Escorts"})
    assert d.SubMenu == "Defiant Class"
    assert d.SubSubMenu == "Escorts"
    assert "SubMenu" not in d.unknown_attributes


def test_absent_keys_stay_none():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    assert d.SubMenu is None and d.SubSubMenu is None


def test_a_later_attribute_still_wins():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X", "SubMenu": "A"})
    d.SubMenu = "B"
    assert d.SubMenu == "B"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_foundation_shipdef_submenu.py -q -p no:cacheprovider`
Expected: FAIL in `test_submenu_and_subsubmenu_come_from_details` (`None != 'Defiant Class'`).

- [ ] **Step 3: Implement**

In `ShipDefinition.__init__`, replace:

```python
        self.SubMenu = None
        self.SubSubMenu = None
```

with:

```python
        # Every corpus mod passes these in `details` (BC Mod Packager's
        # generated ShipDef line); reading only name/iconName/shipFile from it
        # meant nested QuickBattle menus never appeared live.
        self.SubMenu = details.get("SubMenu") or None
        self.SubSubMenu = details.get("SubSubMenu") or None
```

- [ ] **Step 4: Run the new test and the neighbours**

Run: `uv run pytest tests/unit/test_foundation_shipdef_submenu.py tests/unit/test_foundation_menu_injection.py tests/unit/test_foundation_shipdef.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/foundation/shipdef.py tests/unit/test_foundation_shipdef_submenu.py
git commit -m "fix(foundation): read SubMenu/SubSubMenu from a ShipDef's details dict"
```

---

### Task 2: Schema: `variant_of`, `class_default`, `Variant.playable`, name-only class default

**Files:**
- Modify: `engine/ship_catalog/schema.py`
- Test: `tests/unit/test_ship_catalog_schema_classes.py`

**Interfaces:**
- Produces:
  - `Variant(name, script=None, registry=None, playable=None)`
  - `Parsed(values, variants, missing, errors, variant_of: str | None, class_default: bool)`
  - The first kept declared variant may be name-only.

- [ ] **Step 1: Write the failing test**

```python
"""Sub-project 3 schema additions: a free-text class name, the class-default
flag, Variant.playable, and a name-only class default."""
from engine.ship_catalog.schema import Variant, parse_dauntless

FULL = {"title": "Avenger", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}


def test_variant_of_is_trimmed_free_text():
    p = parse_dauntless(dict(FULL, variant_of="  Defiant "))
    assert p.variant_of == "Defiant" and p.errors == ()


def test_absent_or_blank_variant_of_is_none_without_error():
    assert parse_dauntless(FULL).variant_of is None
    p = parse_dauntless(dict(FULL, variant_of="  "))
    assert p.variant_of is None and p.errors == ()


def test_non_string_variant_of_is_an_error():
    p = parse_dauntless(dict(FULL, variant_of=7))
    assert p.variant_of is None
    assert any(e.startswith("variant_of:") for e in p.errors)


def test_class_default_accepts_0_1_and_bools():
    assert parse_dauntless(dict(FULL, class_default=1)).class_default is True
    assert parse_dauntless(dict(FULL, class_default=False)).class_default is False
    assert parse_dauntless(FULL).class_default is False
    p = parse_dauntless(dict(FULL, class_default="yes"))
    assert p.class_default is False and any(e.startswith("class_default:") for e in p.errors)


def test_neither_key_affects_missing():
    assert parse_dauntless(dict(FULL, variant_of="X", class_default=1)).missing == ()


def test_variant_carries_playable_defaulting_to_none():
    assert Variant("USS X").playable is None
    assert Variant("USS X", script="X", playable=True).playable is True


def test_first_variant_may_be_name_only():
    p = parse_dauntless(dict(FULL, variants=[{"name": "USS Defiant"},
                                             {"name": "USS Valiant", "registry": "Valiant"}]))
    assert p.variants == (Variant("USS Defiant"), Variant("USS Valiant", None, "Valiant"))
    assert p.errors == ()


def test_a_later_name_only_variant_is_still_an_error():
    p = parse_dauntless(dict(FULL, variants=[{"name": "A", "registry": "A"}, {"name": "B"}]))
    assert p.variants == (Variant("A", None, "A"),)
    assert "needs a 'script' or a 'registry'" in p.errors[0]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_ship_catalog_schema_classes.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: 'Parsed' object has no attribute 'variant_of'`.

- [ ] **Step 3: Implement** in `engine/ship_catalog/schema.py`

1. Add `playable` to `Variant`:

```python
@dataclass(frozen=True)
class Variant:
    """A named ship. `script` spawns a separate ships/<script>.py instead of
    the definition's own; `registry` is the hull-name decal registry
    (Masks/<registry>/). The class default (variants[0]) may set neither: it
    spawns the entry's own script. `playable` is set on a variant that is a
    class member ship (it has its own flag); None means "the entry's"."""
    name: str
    script: Optional[str] = None
    registry: Optional[str] = None
    playable: Optional[bool] = None
```

2. Extend `Parsed`:

```python
@dataclass(frozen=True)
class Parsed:
    values: dict
    variants: tuple
    missing: tuple
    errors: tuple
    variant_of: Optional[str] = None     # class name, trimmed; None = own class
    class_default: bool = False
```

3. At the end of `parse_dauntless`, replace `return Parsed(values, variants, tuple(missing), tuple(errors))` with:

```python
    variant_of = None
    if "variant_of" in raw and raw["variant_of"] is not None:
        if isinstance(raw["variant_of"], str):
            variant_of = raw["variant_of"].strip() or None
        else:
            errors.append("variant_of: invalid value %r" % (raw["variant_of"],))
    class_default = False
    if "class_default" in raw:
        got = _playable(raw["class_default"])      # same 0/1/bool rule
        if got is None:
            errors.append("class_default: invalid value %r" % (raw["class_default"],))
        else:
            class_default = got
    return Parsed(values, variants, tuple(missing), tuple(errors),
                  variant_of, class_default)
```

4. In `_variants`, replace the "needs a script or a registry" check:

```python
        if script is None and registry is None and kept:
            # Only the class default (the first kept variant) may be
            # name-only: it spawns the entry's own script.
            errors.append("%s %r: needs a 'script' or a 'registry'" % (where, name))
            continue
```

- [ ] **Step 4: Run the new tests and sub-project 1's schema and stock tests**

Run: `uv run pytest tests/unit/test_ship_catalog_schema_classes.py tests/unit/test_ship_catalog_schema.py tests/unit/test_ship_catalog_stock.py -q -p no:cacheprovider`
Expected: all pass.

If the old test `test_invalid_variant_is_dropped_with_an_error_and_never_makes_incomplete` fails on its `{"name": "USS Nameless"}` case: that case is the *second* variant, so it must still error. If it doesn't, the `kept` condition is wrong.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/schema.py tests/unit/test_ship_catalog_schema_classes.py
git commit -m "feat(ship_catalog): variant_of, class_default, Variant.playable in the schema"
```

---

### Task 3: Catalog: `ShipRecord` and `ships()`; entries rebuilt from records

This is a refactor plus additions. Every sub-project 1 test must stay green.

**Files:**
- Modify: `engine/ship_catalog/catalog.py`, `engine/ship_catalog/__init__.py`
- Create: `tests/helpers/catalog_fixtures.py`
- Test: `tests/unit/test_ship_catalog_ships.py`

**Interfaces:**
- Produces:
  - `ShipRecord` (fields below)
  - `ships(source=None) -> list[ShipRecord]`
  - `_Built.ships: list[ShipRecord]`
- Consumes: `Parsed.variant_of`, `Parsed.class_default` (Task 2).

- [ ] **Step 1: Write the failing test**

First, the shared helpers, reused by Tasks 4 and 5. `tests/unit/` is not a package, so they live in `tests/helpers/catalog_fixtures.py`:

```python
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

```

Then `tests/unit/test_ship_catalog_ships.py`:

```python
"""ShipRecord: one per ShipDef in the catalog, before class formation."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Galaxy", **FULL)]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs
    ship_catalog.invalidate()


def test_stock_ship_record(stock):
    (r,) = ship_catalog.ships("stock")
    assert (r.ship_id, r.source, r.mod, r.shipdef_attr) == ("Galaxy", "stock", None, None)
    assert r.values["title"] == "Galaxy" and r.missing == ()
    assert r.variant_of is None and r.class_default is False


def test_mod_ship_record_fields(stock, tmp_path):
    install_mod(tmp_path, "DCMPv2", {"scripts/ships/DCMPAvenger.py": "# s\n"})
    _mod_def("DCMPAvenger", mod="DCMPv2", attr="DCMPAvenger", player=True,
             details={"SubMenu": "Defiant Class"},
             dauntless={"variant_of": "Defiant", "class_default": 1})
    (r,) = ship_catalog.ships("mod")
    assert (r.ship_id, r.source, r.mod, r.shipdef_attr) == ("DCMPAvenger", "mod", "DCMPv2", "DCMPAvenger")
    assert r.variant_of == "Defiant" and r.class_default is True
    assert r.sub_menu == "Defiant Class" and r.player_menu is True
    assert r.raw_name == "Mod DCMPAvenger" and r.raw_race == "Fed"
    assert r.missing == ("era", "role", "playable", "title", "species")


def test_ships_with_no_filter_lists_both(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/X.py": "# s\n"})
    _mod_def("X")
    assert {r.ship_id for r in ship_catalog.ships()} == {"Galaxy", "X"}
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_ship_catalog_ships.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.ship_catalog' has no attribute 'ships'`.

- [ ] **Step 3: Implement** in `engine/ship_catalog/catalog.py`

1. Add `field` to the `dataclasses` import. After `CatalogEntry`, add:

```python
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
```

2. Add `ships: list` as the **first** field of `_Built`, then update every `_Built(...)` construction to pass it.

3. Rename `_entry(stock_d, mod_ds, installed)` to `_record(...)` and return a `ShipRecord`:

```python
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
```

4. Add `_entry_from_record`. It reproduces sub-project 1's entry exactly; Task 4 replaces it with class formation:

```python
def _entry_from_record(r: ShipRecord) -> CatalogEntry:
    v = r.values
    return CatalogEntry(
        ship_id=r.ship_id, icon=r.icon, source=r.source, origins=r.origins,
        title=v.get("title"), species=v.get("species"), era=v.get("era"),
        role=v.get("role"), playable=v.get("playable"),
        variants=r.declared_variants, missing=r.missing, errors=r.errors,
        raw_name=r.raw_name, raw_race=r.raw_race)
```

5. Change the tail of `_build()`:

```python
    records = []
    shared = []
    for stock_d, mod_ds in groups.values():
        r = _record(stock_d, mod_ds, installed)
        records.append(r)
        names = [_mod_name(d) for d in mod_ds]
        if len(set(names)) >= 2:
            shared.append((r.ship_id, names))
    built = [_entry_from_record(r) for r in records]
    built.sort(key=lambda e: ((e.title or e.ship_id).lower(), e.ship_id))
    return _Built(records, built, unresolved, shared, stock_error)
```

6. Add the public reader:

```python
def ships(source: Optional[str] = None) -> list:
    """Every ShipRecord (stock and mod), or only `source` ("stock"/"mod")."""
    return [r for r in _built().ships if source is None or r.source == source]
```

7. In `engine/ship_catalog/__init__.py`, add `ShipRecord` and `ships` to the `catalog` import list.

- [ ] **Step 4: Run the new tests and every sub-project 1 test**

Run: `uv run pytest tests/unit/test_ship_catalog_ships.py tests/unit/test_ship_catalog_merge.py tests/unit/test_ship_catalog_describe.py tests/unit/test_ship_catalog_species.py -q -p no:cacheprovider`
Expected: all pass. `test_ship_catalog_describe.py` builds `_Built(...)` positionally. If it fails on that, update its fixture's constructor call to pass `[]` as the new first argument (`ships`). Ledger that as a ruling.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py tests/helpers/catalog_fixtures.py tests/unit/test_ship_catalog_ships.py tests/unit/test_ship_catalog_describe.py
git commit -m "feat(ship_catalog): ShipRecord per definition; ships() reader"
```

---

### Task 4: Catalog: class formation by name

**Files:**
- Modify: `engine/ship_catalog/catalog.py`, `engine/ship_catalog/__init__.py`
- Test: `tests/unit/test_ship_catalog_classes.py`

**Interfaces:**
- Produces:
  - `resolve_class_default(members: list[tuple[str, bool]]) -> int`, where each member is `(title, class_default)`. Returns an index.
  - `combine_class(members: list[tuple[str, dict, tuple]]) -> tuple[dict, tuple, tuple]`, where each member is `(label, values, missing)`. Returns `(values, missing, errors)`.
  - `_Built.members: dict[str, list[ShipRecord]]`, keyed by the entry's `ship_id.lower()`.
  - Entries are now **classes**.
- Consumes: `ShipRecord` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
"""Classes are names: ships naming the same `variant_of` form ONE entry; each
member is a variant spawning its own script; one starred default."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from engine.ship_catalog.catalog import combine_class, resolve_class_default
from engine.ship_catalog.schema import Variant
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Nebula", **dict(FULL, title="Nebula", variants=[
        {"name": "USS Berkeley", "registry": "Berkeley"}]))]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs
    ship_catalog.invalidate()


def _ship(title, **kw):
    return dict(FULL, title=title, **kw)


def _mods(tmp_path, mod, files):
    install_mod(tmp_path, mod, {"scripts/ships/%s.py" % f: "# s\n" for f in files})


def test_resolve_class_default_order():
    assert resolve_class_default([("Avenger", False), ("Defiant", True)]) == 1
    assert resolve_class_default([("Avenger", False), ("Defiant", False)]) == 0
    # several marked: title match among the marked wins, else the first marked
    assert resolve_class_default([("A", True), ("B", True)]) == 0
    # none marked: exact title match, then whole word, then first
    assert resolve_class_default([("Avenger", False), ("Defiant", False)], "defiant") == 1
    assert resolve_class_default([("USS Bellerophon LC", False), ("USS Intrepid LC", False)], "intrepid") == 1
    assert resolve_class_default([("Avenger", False), ("Lynx", False)], "defiant") == 0


def test_combine_class_era_union_and_conflicts():
    a = ("A", {"era": ("TNG", "DS9"), "role": "tactical", "species": "Federation", "playable": False}, ())
    b = ("B", {"era": ("DS9", "PIC"), "role": "station", "species": "Federation", "playable": True}, ())
    values, missing, errors = combine_class([a, b])
    assert values["era"] == ("TNG", "PIC")
    assert values["playable"] is True and values["species"] == "Federation"
    assert missing == ("role",)
    assert errors == ("role: tactical (A) vs station (B)",)
    c = ("C", {"era": ("all",), "role": "tactical", "species": "Federation", "playable": False}, ())
    assert combine_class([a, c])[0]["era"] == ("all",)


def test_named_class_is_one_entry(stock, tmp_path):
    _mods(tmp_path, "DCMPv2", ["DCMPAvenger", "DCMPDefiant", "DCMPLynx"])
    for f, t in (("DCMPAvenger", "Avenger"), ("DCMPDefiant", "Defiant"), ("DCMPLynx", "Lynx")):
        _mod_def(f, mod="DCMPv2", attr=f, dauntless=_ship(t, variant_of="Defiant"))
    e = ship_catalog.entry("DCMPDefiant")
    assert e.title == "Defiant" and e.source == "mod" and e.complete
    assert e.variants == (Variant("Defiant", playable=True),
                          Variant("Avenger", "DCMPAvenger", playable=True),
                          Variant("Lynx", "DCMPLynx", playable=True))
    assert ship_catalog.entry("DCMPAvenger") is None
    assert len([x for x in ship_catalog.entries() if x.source == "mod"]) == 1


def test_class_default_flag_moves_the_default(stock, tmp_path):
    _mods(tmp_path, "M", ["A", "B"])
    _mod_def("A", dauntless=_ship("Avenger", variant_of="Defiant"))
    _mod_def("B", dauntless=_ship("Bravo", variant_of="Defiant", class_default=1))
    e = [x for x in ship_catalog.entries() if x.title == "Defiant"][0]
    assert e.ship_id == "B" and e.variants[0] == Variant("Bravo", playable=True)


def test_class_spans_two_mods(stock, tmp_path):
    _mods(tmp_path, "ModA", ["A"])
    _mods(tmp_path, "ModB", ["B"])     # install_mod reconfigures with BOTH mods present
    _mod_def("A", mod="ModA", dauntless=_ship("Alpha", variant_of="Shared"))
    _mod_def("B", mod="ModB", dauntless=_ship("Beta", variant_of="shared "))
    (e,) = [x for x in ship_catalog.entries() if x.source == "mod"]
    assert e.title == "Shared" and [o[0] for o in e.origins] == ["ModA", "ModB"]


def test_stock_class_join_appends_and_keeps_stock_default(stock, tmp_path):
    _mods(tmp_path, "LC", ["LCvoyagerZZ"])
    _mod_def("LCvoyagerZZ", mod="LC", dauntless=_ship("USS Voyager LC", variant_of="nebula", class_default=1))
    e = ship_catalog.entry("Nebula")
    assert e.source == "mod"
    assert e.variants == (Variant("USS Berkeley", None, "Berkeley"),
                          Variant("USS Voyager LC", "LCvoyagerZZ", playable=True))
    assert any("class_default ignored" in x for x in e.errors)
    assert ship_catalog.entry("LCvoyagerZZ") is None


def test_role_conflict_makes_class_incomplete(stock, tmp_path):
    _mods(tmp_path, "M", ["A", "B"])
    _mod_def("A", dauntless=_ship("Alpha", variant_of="K"))
    _mod_def("B", dauntless=_ship("Beta", variant_of="K", role="station"))
    e = [x for x in ship_catalog.entries() if x.title == "K"][0]
    assert "role" in e.missing and not e.complete


def test_member_missing_a_key_makes_class_incomplete(stock, tmp_path):
    _mods(tmp_path, "M", ["A"])
    _mod_def("A", dauntless={"variant_of": "K", "title": "Alpha"})
    e = [x for x in ship_catalog.entries() if x.title == "K"][0]
    assert e.missing == ("era", "role", "playable", "species")


def test_own_class_unchanged(stock, tmp_path):
    _mods(tmp_path, "M", ["X"])
    _mod_def("X", dauntless=_ship("Xeno"))
    e = ship_catalog.entry("X")
    assert e.title == "Xeno" and e.variants == () and e.complete
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_ship_catalog_classes.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'combine_class'`.

- [ ] **Step 3: Implement** in `engine/ship_catalog/catalog.py`

Add `import re` at the top, and add `MANDATORY` to the import from `tables`. Then add:

```python
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
```

Then:
1. Add `members: dict` as the **second** field of `_Built` (after `ships`).
2. In `_build()`, replace `built = [_entry_from_record(r) for r in records]` with `built, members = _classes(records)`, and return `_Built(records, members, built, unresolved, shared, stock_error)`.
3. Delete `_entry_from_record`.
4. Import `Variant` from `schema`.
5. Export `combine_class` and `resolve_class_default` from `__init__.py`.

- [ ] **Step 4: Run every catalog test**

Run: `uv run pytest tests/unit/test_ship_catalog_classes.py tests/unit/test_ship_catalog_ships.py tests/unit/test_ship_catalog_merge.py tests/unit/test_ship_catalog_describe.py tests/unit/test_ship_catalog_species.py tests/unit/test_ship_catalog_stock.py -q -p no:cacheprovider`
Expected: all pass. Update `test_ship_catalog_describe.py`'s positional `_Built(...)` call to pass `[], {}` for the two new leading fields if needed, and ledger it.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py tests/unit/test_ship_catalog_classes.py tests/unit/test_ship_catalog_describe.py
git commit -m "feat(ship_catalog): classes formed by variant_of name with one default"
```

---

### Task 5: Catalog: `incomplete_ships`, `suggestions`, skip-for-session; skip-aware injection

**Files:**
- Modify: `engine/ship_catalog/catalog.py`, `engine/ship_catalog/__init__.py`, `engine/foundation/quickbattle.py` (`_inject_registered_ships`), `tests/conftest.py` (`_reset_leakable_engine_globals`)
- Test: `tests/unit/test_ship_catalog_gate_api.py`

**Interfaces:**
- Produces:
  - `incomplete_ships() -> list[ShipRecord]`
  - `suggestions(r: ShipRecord) -> dict`
  - `skip_for_session(ship_ids) -> None`
  - `skipped() -> frozenset[str]` (folded ids)
  - `reset_session() -> None`
  - `RACE_TO_SPECIES: dict`

- [ ] **Step 1: Write the failing test**

```python
"""The gate's view of the catalog: which ships it must ask about, what it
pre-fills, and the session-only skip."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _clean():
    quickbattle.reset()
    ship_catalog.reset_session()
    yield
    quickbattle.reset()
    ship_catalog.reset_session()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Galaxy", **FULL)]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs


def test_incomplete_ships_lists_mod_ships_missing_keys(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#", "scripts/ships/B.py": "#"})
    _mod_def("A")
    _mod_def("B", dauntless=dict(FULL, title="Bee"))
    assert [r.ship_id for r in ship_catalog.incomplete_ships()] == ["A"]


def test_conflicting_class_members_are_all_incomplete(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#", "scripts/ships/B.py": "#"})
    _mod_def("A", dauntless=dict(FULL, title="A", variant_of="K"))
    _mod_def("B", dauntless=dict(FULL, title="B", variant_of="K", species="Klingon"))
    assert sorted(r.ship_id for r in ship_catalog.incomplete_ships()) == ["A", "B"]


def test_suggestions(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A", player=True, details={"SubMenu": "Defiant Class"})
    (r,) = ship_catalog.incomplete_ships()
    assert ship_catalog.suggestions(r) == {
        "title": "Mod A", "species": "Federation", "playable": True,
        "role": "tactical", "variant_of": "Defiant"}


def test_suggestions_omit_what_has_no_source(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    d = _mod_def("A", details={"SubMenu": "Class"})
    d.race = "Borg"
    ship_catalog.invalidate()
    (r,) = ship_catalog.incomplete_ships()
    assert ship_catalog.suggestions(r) == {"title": "Mod A", "role": "tactical"}


def test_skip_hides_from_every_view(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A")
    ship_catalog.skip_for_session(["a"])
    assert ship_catalog.skipped() == frozenset({"a"})
    assert ship_catalog.incomplete_ships() == []
    assert ship_catalog.entry("A") is None
    assert [r.ship_id for r in ship_catalog.ships("mod")] == []


def test_skipped_ship_gets_no_quickbattle_button(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A")
    ship_catalog.skip_for_session(["A"])
    added = []

    class Menu:
        def GetButtonW(self, name): return None
        def AddChild(self, b): added.append(b)

    class QB:
        g_pShipsPane = object()
        g_pPlayerPane = None
        ET_SELECT_SHIP_TYPE = 1
        g_pXO = None
        def CreateBridgeMenuButton(self, *a): return a

    import engine.foundation.quickbattle as fq
    orig = fq._resolve_category_chain
    fq._resolve_category_chain = lambda *a: Menu()
    try:
        assert fq._inject_registered_ships(QB()) == 0
    finally:
        fq._resolve_category_chain = orig
    assert added == []
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_ship_catalog_gate_api.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.ship_catalog' has no attribute 'reset_session'`.

- [ ] **Step 3: Implement**

In `engine/ship_catalog/catalog.py`:

```python
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
    member of a class that is incomplete only through a role/species
    conflict (each member is complete alone; the player fixes it by editing
    one). Load order, no duplicates."""
    b = _built()
    out = [r for r in b.ships if r.source == "mod" and r.missing]
    seen = {r.ship_id for r in out}
    for e in b.entries:
        if e.complete:
            continue
        group = b.members.get(e.ship_id.lower(), [])
        if all(not m.missing for m in group):
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
```

In `_build()`, filter the skipped records right after the records loop:

```python
    records = [r for r in records if r.ship_id.lower() not in _skipped]
```

Export `incomplete_ships`, `suggestions`, `skip_for_session`, `skipped`, `reset_session` and `RACE_TO_SPECIES` from `__init__.py`.

In `engine/foundation/quickbattle.py` `_inject_registered_ships`, right after `ship_def = _definition_for_sid(sid)` and its `None` check, add:

```python
        # "Skip for now" on the Mods screen: no button this session
        # (the table rows stay -- harmless without a button).
        from engine import ship_catalog
        if str(getattr(ship_def, "shipFile", "")).lower() in ship_catalog.skipped():
            continue
```

In `tests/conftest.py`, inside the ship-catalog try block of `_reset_leakable_engine_globals`, replace `_ship_catalog.invalidate()` with `_ship_catalog.reset_session()`. It also invalidates.

- [ ] **Step 4: Run the new tests and the neighbours**

Run: `uv run pytest tests/unit/test_ship_catalog_gate_api.py tests/unit/test_ship_catalog_classes.py tests/unit/test_foundation_menu_injection.py tests/unit/test_foundation_quickbattle.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/catalog.py engine/ship_catalog/__init__.py engine/foundation/quickbattle.py tests/conftest.py tests/unit/test_ship_catalog_gate_api.py
git commit -m "feat(ship_catalog): incomplete_ships, suggestions, session skip"
```

---

### Task 6: `mods.register_sdk_file` and the `--mods` flag

**Files:**
- Modify: `engine/mods.py`
- Test: `tests/unit/test_mods_sdk_register.py`

**Interfaces:**
- Produces:
  - `register_sdk_file(raw_rel, abs_path, mod_name) -> None`
  - `MODS_SCREEN_FLAG = "--mods"`
  - `mods_screen_requested(argv=None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from engine import mods


def setup_function():
    mods.configure(None)


def teardown_function():
    mods.configure(None)


def test_register_sdk_file_adds_an_sdk_entry(tmp_path):
    p = tmp_path / "zz.py"
    p.write_text("#")
    mods.register_sdk_file("Custom/Ships/zz_Dauntless_X.py", p, "M")
    mf = mods.current().lookup("custom/ships/zz_dauntless_x.py")
    assert mf is not None and mf.target == "sdk" and mf.mod_name == "M"  # paths-guard: kind label
    assert mf.abs_path == Path(p) and mf.raw_rel == "Custom/Ships/zz_Dauntless_X.py"
    assert mods.sdk_override("Custom/Ships/zz_Dauntless_X.py") == Path(p)


def test_mods_screen_requested():
    assert mods.mods_screen_requested(["--mods"]) is True
    assert mods.mods_screen_requested(["--developer"]) is False
    assert mods.MODS_SCREEN_FLAG == "--mods"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_mods_sdk_register.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.mods' has no attribute 'register_sdk_file'`.

- [ ] **Step 3: Implement** in `engine/mods.py`

After `register_game_file`, add:

```python
def register_sdk_file(raw_rel, abs_path: Path, mod_name: str) -> None:
    """The SDK-target sibling of register_game_file(): add one just-written
    script (the Mods screen's zz_Dauntless_*.py) to the configured index, so
    the Foundation loader and sdk_override() see it without a re-walk.
    `raw_rel` is relative to the mod's Scripts dir ("Custom/Ships/x.py")."""
    raw_rel = str(raw_rel).replace("\\", "/").strip("/")
    current().files[fold(raw_rel)] = ModFile(
        abs_path=Path(abs_path), mod_name=mod_name,
        target="sdk",  # paths-guard: kind label
        rel=fold(raw_rel), raw_rel=raw_rel)
```

Beside `DISABLE_FLAG`, add:

```python
# Open the pre-boot Mods screen in home mode (sub-project 3). The pause
# menu's "Quit and Manage Mods" relaunches with it.
MODS_SCREEN_FLAG = "--mods"
```

After `mods_disabled_by`, add:

```python
def mods_screen_requested(argv=None) -> bool:
    import sys
    if argv is None:
        argv = sys.argv[1:]
    return MODS_SCREEN_FLAG in argv
```

- [ ] **Step 4: Run the new tests and the path guard**

Run: `uv run pytest tests/unit/test_mods_sdk_register.py tests/unit/test_mods_index.py tests/unit/test_path_indirection.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/mods.py tests/unit/test_mods_sdk_register.py
git commit -m "feat(mods): register_sdk_file and the --mods screen flag"
```

---

### Task 7: `gate_writer`: render, write, register, run

**Files:**
- Create: `engine/ship_catalog/gate_writer.py`
- Test: `tests/unit/test_gate_writer.py`

**Interfaces:**
- Produces:
  - `GateWriteError(Exception)`
  - `render(attr: str, answers: dict) -> str`
  - `ships_dir(mod_name: str) -> tuple[Path, str]`: the absolute directory and the raw-rel prefix such as `"Custom/Ships"`
  - `write_answers(mod_name, ship_id, attr, answers) -> Path`
- `answers` keys are a subset of `title, species, era, role, playable, variant_of, class_default`. `era` is `(from_id, to_id)` or `("all",)`.

- [ ] **Step 1: Write the failing test**

```python
"""The Mods screen's writer: one guarded, Python 1.5-safe zz_ file per ship,
in the mod's own Custom/Ships spelling, registered and re-run in-process."""
import ast
import os

import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import gate_writer

ANS = {"title": "Avenger", "species": "Federation", "era": ("DS9", "DS9"),
       "role": "tactical", "playable": True, "variant_of": "Defiant",
       "class_default": True}


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset(); quickbattle.reset(); mods.configure(None)
    yield
    foundation.reset(); quickbattle.reset(); mods.configure(None)


def test_render_is_guarded_and_python15_safe():
    text = gate_writer.render("DCMPAvenger", ANS)
    assert "if hasattr(Foundation.ShipDef, 'DCMPAvenger'):" in text
    assert "'era': ('DS9', 'DS9')" in text and "'playable': 1" in text
    assert "'variant_of': 'Defiant'" in text and "'class_default': 1" in text
    tree = ast.parse(text)
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, bool) for n in ast.walk(tree))
    assert not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree))


def test_render_all_eras_and_quotes():
    text = gate_writer.render("X", {"title": "Vor'cha", "era": ("all",)})
    assert "'era': 'all'" in text and "'title': 'Vor\\'cha'" in text


def test_render_omits_class_default_when_false():
    assert "class_default" not in gate_writer.render("X", dict(ANS, class_default=False))


def _mod_tree(tmp_path):
    ships = tmp_path / "mods" / "DCMPv2" / "Scripts" / "Custom" / "Ships"
    ships.mkdir(parents=True)
    (ships / "DCMP.py").write_text(
        "import Foundation\n"
        "Foundation.ShipDef.DCMPAvenger = Foundation.FedShipDef('DCMPAvenger', 103, "
        "{'name': 'Avenger', 'shipFile': 'DCMPAvenger'})\n")
    sdk_ships = tmp_path / "mods" / "DCMPv2" / "Scripts" / "ships"
    sdk_ships.mkdir(parents=True)
    (sdk_ships / "DCMPAvenger.py").write_text("#")
    mods.configure(mods.build_index(tmp_path / "mods"))
    return ships


def test_ships_dir_follows_the_mods_spelling(tmp_path):
    ships = _mod_tree(tmp_path)
    d, prefix = gate_writer.ships_dir("DCMPv2")
    assert d == ships and prefix == "Custom/Ships"


def test_write_registers_and_runs_the_file(tmp_path):
    _mod_tree(tmp_path)
    foundation.load_plugins()
    path = gate_writer.write_answers("DCMPv2", "DCMPAvenger", "DCMPAvenger", ANS)
    assert path.name == "zz_Dauntless_DCMPAvenger.py" and path.is_file()
    assert not path.with_suffix(".py.tmp").exists()
    assert mods.current().lookup("custom/ships/zz_dauntless_dcmpavenger.py") is not None
    assert foundation.ShipDef.DCMPAvenger.dauntless["variant_of"] == "Defiant"


def test_write_failure_is_a_gate_write_error(tmp_path):
    ships = _mod_tree(tmp_path)
    os.chmod(ships, 0o500)
    try:
        with pytest.raises(gate_writer.GateWriteError) as e:
            gate_writer.write_answers("DCMPv2", "DCMPAvenger", "DCMPAvenger", ANS)
        assert "zz_Dauntless_DCMPAvenger.py" in str(e.value)
    finally:
        os.chmod(ships, 0o700)


def test_missing_attr_is_a_gate_write_error(tmp_path):
    _mod_tree(tmp_path)
    with pytest.raises(gate_writer.GateWriteError):
        gate_writer.write_answers("DCMPv2", "X", None, ANS)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_gate_writer.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'gate_writer'`.

- [ ] **Step 3: Implement** `engine/ship_catalog/gate_writer.py`

```python
"""Write the Mods screen's answers into a mod (spec 2026-10-01 mod ships §3).

One zz_Dauntless_<shipFile>.py per ship, beside the mod's own Custom/Ships
scripts (so the Foundation loader's filename order runs it LAST), guarded and
Python 1.5-safe so the same mod still loads in the original BC. After the
atomic write the file is added to the mod index and run in-process under
plugin_origin, so no reboot is needed.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

_KEY_ORDER = ("title", "species", "era", "role", "playable", "variant_of", "class_default")


class GateWriteError(Exception):
    """A write that could not complete; the message names the file."""


def _lit(s) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _value(key, v) -> str:
    if key == "era":
        return _lit("all") if tuple(v) == ("all",) else "(%s, %s)" % (_lit(v[0]), _lit(v[1]))
    if key in ("playable", "class_default"):
        return "1" if v else "0"
    return _lit(v)


def render(attr: str, answers: dict) -> str:
    items = []
    for key in _KEY_ORDER:
        if key not in answers or answers[key] is None:
            continue
        if key == "class_default" and not answers[key]:
            continue
        items.append("        %s: %s," % (_lit(key), _value(key, answers[key])))
    return ("# Written by Dauntless's Mod Ships screen. Safe to delete: the\n"
            "# screen will ask again.\n"
            "import Foundation\n"
            "if hasattr(Foundation.ShipDef, %s):\n"
            "    d = Foundation.ShipDef.%s\n"
            "    if not hasattr(d, 'dauntless'):\n"
            "        d.dauntless = {}\n"
            "    d.dauntless.update({\n%s\n    })\n") % (_lit(attr), attr, "\n".join(items))


def ships_dir(mod_name: str):
    """(absolute Custom/Ships dir, raw-rel prefix) for `mod_name`, in the
    mod's own spelling when it already has a Custom/Ships script."""
    from engine import mods
    for key, mf in sorted(mods.current().files.items()):
        if (mf.mod_name == mod_name and mf.target == "sdk"  # paths-guard: kind label
                and key.startswith("custom/ships/") and key.endswith(".py")):
            prefix = mf.raw_rel.rsplit("/", 1)[0]
            return mf.abs_path.parent, prefix
    for status in mods.current().mods:
        if status.name == mod_name and status.content_root is not None:
            return status.content_root / "scripts" / "Custom" / "Ships", "Custom/Ships"
    raise GateWriteError("mod %r has no content root to write into" % mod_name)


def write_answers(mod_name: str, ship_id: str, attr, answers: dict) -> Path:
    from engine import mods
    from engine.foundation.shipdef import plugin_origin
    if not attr:
        raise GateWriteError("%s has no Foundation.ShipDef name to write against" % ship_id)
    directory, prefix = ships_dir(mod_name)
    name = "zz_Dauntless_%s.py" % ship_id
    path = directory / name
    tmp = directory / (name + ".tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp.write_text(render(attr, answers), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise GateWriteError("%s: %s" % (path, exc)) from exc
    raw_rel = "%s/%s" % (prefix, name)
    mods.register_sdk_file(raw_rel, path, mod_name)
    with plugin_origin(mod_name, mods.fold(raw_rel)):
        runpy.run_path(str(path), run_name="__foundation__")
    return path
```

- [ ] **Step 4: Run the new tests and the path guard**

Run: `uv run pytest tests/unit/test_gate_writer.py tests/unit/test_path_indirection.py -q -p no:cacheprovider`
Expected: all pass. The `"scripts"` literal in `ships_dir` is a mod-layout segment, not a BC root. If `test_path_indirection` flags it, add `# paths-guard: mod content layout` on that line and ledger it.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ship_catalog/gate_writer.py tests/unit/test_gate_writer.py
git commit -m "feat(ship_catalog): gate_writer renders and runs zz_Dauntless files"
```

---

### Task 8: `ModsScreenPanel`, the screen's state machine

**Files:**
- Create: `engine/ui/mods_screen_panel.py`
- Test: `tests/unit/test_mods_screen_panel.py`

**Interfaces:**
- Consumes: `ShipRecord`, `suggestions`, `combine_class`, `resolve_class_default` (Tasks 3–5); `schema.parse_dauntless`; `tables.ERAS`, `ROLES`.
- Produces: `ModsScreenPanel(mode, editable, readonly, *, species, stock_classes, writer=None, suggest=None, error="")`, where:
  - `mode` is `"gate"` or `"home"`
  - `writer(rows: list[WriteRow]) -> None` may raise `GateWriteError`
  - `WriteRow = namedtuple("WriteRow", "mod ship_id attr answers")`
  - `.outcome` is `None`, `"continue"`, `"skip"`, `"play"` or `"quit"`
  - `.render_payload()` returns a `"setModsScreen({...});"` string
  - `.dispatch_event(action)` takes:
    - `tick:<file>`, `tick-mod:<mod>`, `clear-ticks`
    - `set:<file>:<field>:<urlencoded value>`, where field is `title`, `variant_of`, `role`, `species`, `playable` (`1`/`0`), `era` (`all`), `era-from` or `era-to` (era id)
    - `star:<file>`
    - `continue`, `skip`, `play`, `quit`
  - `teardown_script = "setModsScreen(null);"`
  - `handle_key_esc()` does nothing in gate mode and Play in home mode.

- [ ] **Step 1: Write the failing test**

```python
"""ModsScreenPanel: every decision the Mods screen makes. The page renders
the payload and reports clicks; it holds no logic (spec §1)."""
import json
from urllib.parse import quote

import pytest

from engine.ship_catalog.catalog import ShipRecord
from engine.ship_catalog.gate_writer import GateWriteError
from engine.ui.mods_screen_panel import ModsScreenPanel


def rec(ship_id, mod="DCMPv2", values=None, missing=None, sub_menu=None, player=True,
        variant_of=None, class_default=False, name=None):
    values = values or {}
    if missing is None:
        missing = tuple(k for k in ("era", "role", "playable", "title", "species") if k not in values)
    return ShipRecord(ship_id=ship_id, source="mod", mod=mod, shipdef_attr=ship_id,
                      icon="DCMPDefiantClass", values=values, variant_of=variant_of,
                      class_default=class_default, missing=missing, errors=(),
                      raw_name=name or ship_id[4:], raw_race="Fed", sub_menu=sub_menu,
                      player_menu=player)


SPECIES = ["Federation", "Klingon"]
STOCK = ["Galaxy", "Nebula"]


def gate(*editable, readonly=(), writer=None):
    return ModsScreenPanel("gate", list(editable), list(readonly), species=SPECIES,
                           stock_classes=STOCK, writer=writer)


def payload(p):
    s = p.render_payload() or p._last_pushed
    return json.loads(s[len("setModsScreen("):-2])


def row(p, f):
    return next(r for r in payload(p)["rows"] if r["file"] == f)


def ev(p, *parts):
    assert p.dispatch_event(":".join(parts))


def test_prefills_from_suggestions_and_era_stays_blank():
    p = gate(rec("DCMPAvenger", sub_menu="Defiant Class"))
    r = row(p, "DCMPAvenger")
    assert (r["title"], r["species"], r["role"], r["playable"], r["variant_of"]) == (
        "Avenger", "Federation", "tactical", True, "Defiant")
    assert r["era"] is None and r["missing"] == ["era"]
    assert payload(p)["can_continue"] is False


def test_set_era_from_and_to_drag_each_other():
    p = gate(rec("DCMPAvenger"))
    ev(p, "set", "DCMPAvenger", "era-from", "DS9")
    assert row(p, "DCMPAvenger")["era"] == "DS9-DS9"
    ev(p, "set", "DCMPAvenger", "era-to", "TNG")
    assert row(p, "DCMPAvenger")["era"] == "TNG-TNG"
    ev(p, "set", "DCMPAvenger", "era-to", "PIC")
    assert row(p, "DCMPAvenger")["era"] == "TNG-PIC"
    ev(p, "set", "DCMPAvenger", "era", "all")
    assert row(p, "DCMPAvenger")["era"] == "all"


def test_ticked_rows_all_take_an_edit():
    p = gate(rec("DCMPA"), rec("DCMPB"), rec("DCMPC"))
    ev(p, "tick", "DCMPA"); ev(p, "tick", "DCMPB")
    ev(p, "set", "DCMPA", "role", "station")
    assert [row(p, f)["role"] for f in ("DCMPA", "DCMPB", "DCMPC")] == ["station", "station", "tactical"]
    assert payload(p)["ticked"] == 2


def test_edit_on_unticked_row_touches_only_that_row():
    p = gate(rec("DCMPA"), rec("DCMPB"))
    ev(p, "tick", "DCMPA")
    ev(p, "set", "DCMPB", "species", "Klingon")
    assert row(p, "DCMPA")["species"] == "Federation" and row(p, "DCMPB")["species"] == "Klingon"


def test_tick_mod_ticks_only_editable_rows():
    ro = rec("DCMPDone", values={"title": "Done", "era": ("DS9", "DS9"), "role": "tactical",
                                 "species": "Federation", "playable": True}, missing=())
    p = gate(rec("DCMPA"), readonly=[ro])
    ev(p, "tick-mod", "DCMPv2")
    assert row(p, "DCMPA")["ticked"] and not row(p, "DCMPDone")["ticked"]
    assert row(p, "DCMPDone")["editable"] is False
    assert p.dispatch_event("set:DCMPDone:role:station") is True
    assert row(p, "DCMPDone")["role"] == "tactical"


def test_typed_values_are_url_decoded():
    p = gate(rec("DCMPA"))
    ev(p, "set", "DCMPA", "title", quote("USS Avenger: Refit"))
    assert row(p, "DCMPA")["title"] == "USS Avenger: Refit"


def test_star_auto_picks_title_match_and_moves_on_click():
    p = gate(rec("DCMPAvenger", sub_menu="Defiant Class"),
             rec("DCMPDefiant", sub_menu="Defiant Class"))
    assert row(p, "DCMPDefiant")["is_default"] and not row(p, "DCMPAvenger")["is_default"]
    ev(p, "star", "DCMPAvenger")
    assert row(p, "DCMPAvenger")["is_default"] and not row(p, "DCMPDefiant")["is_default"]


def test_star_spans_mods():
    p = gate(rec("A", mod="ModA", variant_of="K", name="Kay"),
             rec("B", mod="ModB", variant_of="k", name="Bee"))
    assert [row(p, f)["is_default"] for f in ("A", "B")] == [True, False]


def test_stock_class_has_no_star():
    p = gate(rec("LCvoyagerZZ", mod="LC", variant_of="Nebula"))
    r = row(p, "LCvoyagerZZ")
    assert r["stock_class"] is True and r["is_default"] is False


def test_class_conflict_blocks_continue_and_names_it():
    full = {"era": ("DS9", "DS9")}
    p = gate(rec("A", variant_of="K"), rec("B", variant_of="K"))
    for f in ("A", "B"):
        ev(p, "set", f, "era", "all")
    ev(p, "set", "B", "role", "station")
    assert payload(p)["can_continue"] is False
    assert "role" in row(p, "A")["conflict"]


def test_continue_writes_complete_rows_and_sets_outcome():
    written = []
    p = gate(rec("DCMPA", sub_menu="Defiant Class"), writer=lambda rows: written.extend(rows))
    ev(p, "set", "DCMPA", "era", "all")
    ev(p, "continue")
    assert p.outcome == "continue"
    (w,) = written
    assert (w.mod, w.ship_id, w.attr) == ("DCMPv2", "DCMPA", "DCMPA")
    assert w.answers == {"title": "A", "species": "Federation", "era": ("all",),
                         "role": "tactical", "playable": True, "variant_of": "Defiant",
                         "class_default": True}


def test_continue_while_incomplete_is_inert():
    p = gate(rec("DCMPA"), writer=lambda rows: pytest.fail("must not write"))
    ev(p, "continue")
    assert p.outcome is None


def test_writer_error_is_shown_and_skip_still_works():
    def boom(rows):
        raise GateWriteError("/mods/x/zz_Dauntless_DCMPA.py: Permission denied")
    p = gate(rec("DCMPA"), writer=boom)
    ev(p, "set", "DCMPA", "era", "all")
    ev(p, "continue")
    assert p.outcome is None and "Permission denied" in payload(p)["error"]
    ev(p, "skip")
    assert p.outcome == "skip"


def test_home_mode_is_read_only_with_play():
    ro = rec("DCMPDone", values={"title": "Done", "era": ("DS9", "DS9"), "role": "tactical",
                                 "species": "Federation", "playable": True}, missing=())
    p = ModsScreenPanel("home", [], [ro], species=SPECIES, stock_classes=STOCK)
    assert payload(p)["mode"] == "home" and payload(p)["header"] == "Mod Ships"
    p.handle_key_esc()
    assert p.outcome == "play"


def test_esc_does_nothing_in_gate_mode():
    p = gate(rec("DCMPA"))
    p.handle_key_esc()
    assert p.outcome is None


def test_render_payload_is_diff_cached_and_invalidate_re_emits():
    p = gate(rec("DCMPA"))
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_quit_and_teardown():
    p = gate(rec("DCMPA"))
    ev(p, "quit")
    assert p.outcome == "quit" and p.teardown_script == "setModsScreen(null);"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_mods_screen_panel.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ui.mods_screen_panel'`.

- [ ] **Step 3: Implement** `engine/ui/mods_screen_panel.py`

```python
"""The pre-boot Mods screen's state machine (spec 2026-10-01 mod ships §1).

Every decision is here; the CEF page (js/mods_screen.js) renders the payload
and reports clicks and committed text. Two modes:
  gate -- incomplete mod ships are editable rows; Continue writes them.
  home -- every mod ship read-only; Play boots (the future mod manager's home).
"""
from __future__ import annotations

import json
from collections import namedtuple
from typing import Callable, Optional
from urllib.parse import unquote

from engine.ship_catalog import catalog
from engine.ship_catalog.gate_writer import GateWriteError
from engine.ship_catalog.schema import parse_dauntless
from engine.ship_catalog.tables import ERA_IDS, ERAS, MANDATORY, ROLES
from engine.ui.panel import Panel

WriteRow = namedtuple("WriteRow", "mod ship_id attr answers")

_HEADERS = {"gate": "New mod ships need details", "home": "Mod Ships"}
_INTROS = {
    "gate": ("These ships come from mods that don't say which era, role or species "
             "they belong to. Fill in the missing details once. Your answers are "
             "saved into each mod's own folder, so you won't be asked again."),
    "home": "Every ship your installed mods add, and the details Dauntless uses for it.",
}


class _Row:
    def __init__(self, record, editable: bool, answers: dict):
        self.record = record
        self.editable = editable
        self.answers = answers          # title/species/era/role/playable/variant_of/class_default
        self.ticked = False

    @property
    def file(self) -> str:
        return self.record.ship_id

    def class_key(self) -> str:
        return (self.answers.get("variant_of") or "").strip().lower()


class ModsScreenPanel(Panel):
    def __init__(self, mode: str, editable: list, readonly: list, *, species, stock_classes,
                 writer: Optional[Callable] = None, suggest: Optional[Callable] = None,
                 error: str = "") -> None:
        super().__init__()
        self._mode = mode
        self._species = list(species)
        self._stock = list(stock_classes)
        self._stock_keys = {s.strip().lower() for s in self._stock}
        self._writer = writer
        suggest = suggest or catalog.suggestions
        self._rows = []
        for r in editable:
            answers = dict(suggest(r))
            answers.update(r.values)
            if r.variant_of:
                answers["variant_of"] = r.variant_of
            answers["class_default"] = r.class_default
            self._rows.append(_Row(r, True, answers))
        for r in readonly:
            answers = dict(r.values, variant_of=r.variant_of, class_default=r.class_default)
            self._rows.append(_Row(r, False, answers))
        self._outcome: Optional[str] = None
        self._error = error
        self._last_pushed: Optional[str] = None
        self.visible = True

    # ── Panel contract ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "mods"

    @property
    def outcome(self) -> Optional[str]:
        return self._outcome

    teardown_script = "setModsScreen(null);"

    def invalidate(self) -> None:
        super().invalidate()
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._mode == "home":
            self._outcome = "play"

    def render_payload(self) -> Optional[str]:
        script = "setModsScreen(" + json.dumps(self._snapshot()) + ");"
        if script == self._last_pushed:
            return None
        self._last_pushed = script
        return script

    def dispatch_event(self, action: str) -> bool:
        if action in ("continue", "skip", "play", "quit"):
            getattr(self, "_on_" + action)()
            return True
        if action == "clear-ticks":
            for r in self._rows:
                r.ticked = False
            return True
        if action.startswith("tick:"):
            r = self._find(action[5:])
            if r is not None and r.editable:
                r.ticked = not r.ticked
            return True
        if action.startswith("tick-mod:"):
            mod = action[9:]
            mine = [r for r in self._rows if r.editable and r.record.mod == mod]
            on = not all(r.ticked for r in mine)
            for r in mine:
                r.ticked = on
            return True
        if action.startswith("star:"):
            r = self._find(action[5:])
            if r is not None and r.editable and r.class_key() and r.class_key() not in self._stock_keys:
                for m in self._members(r.class_key()):
                    if m.editable:
                        m.answers["class_default"] = False
                r.answers["class_default"] = True
            return True
        if action.startswith("set:"):
            parts = action.split(":", 3)
            if len(parts) != 4:
                return False
            _, file, field, raw = parts
            r = self._find(file)
            if r is None or not r.editable:
                return True
            value = unquote(raw)
            for t in (self._ticked() if r.ticked else [r]):
                self._apply(t, field, value)
            return True
        return False

    # ── edits ───────────────────────────────────────────────────────────
    def _apply(self, r: _Row, field: str, value: str) -> None:
        a = r.answers
        if field in ("title", "species"):
            a[field] = value.strip() or None
        elif field == "variant_of":
            a["variant_of"] = value.strip() or None
            a["class_default"] = False
        elif field == "role":
            a["role"] = value if value in {x.id for x in ROLES} else None
        elif field == "playable":
            a["playable"] = value == "1"
        elif field == "era" and value == "all":
            a["era"] = ("all",)
        elif field in ("era-from", "era-to") and value in ERA_IDS:
            i = ERA_IDS.index(value)
            lo, hi = (ERA_IDS.index(a["era"][0]), ERA_IDS.index(a["era"][1])) \
                if isinstance(a.get("era"), tuple) and a["era"] != ("all",) else (i, i)
            if field == "era-from":
                lo, hi = i, max(hi, i)
            else:
                lo, hi = min(lo, i), i
            a["era"] = (ERA_IDS[lo], ERA_IDS[hi])

    # ── validation ──────────────────────────────────────────────────────
    def _row_missing(self, r: _Row) -> tuple:
        raw = {k: v for k, v in r.answers.items() if k in MANDATORY and v is not None}
        if "era" in raw:
            raw["era"] = list(raw["era"]) if raw["era"] != ("all",) else "all"
        return parse_dauntless(raw).missing

    def _members(self, key: str) -> list:
        return [m for m in self._rows if m.class_key() == key]

    def _conflict(self, r: _Row) -> str:
        key = r.class_key()
        if not key:
            return ""
        group = self._members(key)
        if len(group) < 2:
            return ""
        _v, _m, errors = catalog.combine_class(
            [(m.answers.get("title") or m.file,
              {k: m.answers[k] for k in ("era", "role", "species", "playable")
               if m.answers.get(k) is not None}, ()) for m in group])
        return "; ".join(errors)

    def _default_flags(self) -> dict:
        flags = {}
        seen = set()
        for r in self._rows:
            key = r.class_key()
            if not key or key in self._stock_keys or key in seen:
                continue
            seen.add(key)
            group = self._members(key)
            idx = catalog.resolve_class_default(
                [(m.answers.get("title") or m.file, bool(m.answers.get("class_default")))
                 for m in group], key)
            for i, m in enumerate(group):
                flags[m.file] = i == idx
        return flags

    def _ready(self) -> bool:
        return all(not self._row_missing(r) and not self._conflict(r)
                   for r in self._rows if r.editable)

    # ── outcomes ────────────────────────────────────────────────────────
    def _on_continue(self) -> None:
        if self._mode != "gate" or not self._ready():
            return
        flags = self._default_flags()
        rows = []
        for r in self._rows:
            if not r.editable:
                continue
            answers = {k: r.answers.get(k) for k in MANDATORY}
            if r.answers.get("variant_of"):
                answers["variant_of"] = r.answers["variant_of"]
                answers["class_default"] = flags.get(r.file, False)
            rows.append(WriteRow(r.record.mod, r.file, r.record.shipdef_attr, answers))
        if self._writer is not None:
            try:
                self._writer(rows)
            except GateWriteError as exc:
                self._error = str(exc)
                return
        self._outcome = "continue"

    def _on_skip(self) -> None:
        if self._mode == "gate":
            self._outcome = "skip"

    def _on_play(self) -> None:
        if self._mode == "home":
            self._outcome = "play"

    def _on_quit(self) -> None:
        self._outcome = "quit"

    # ── payload ─────────────────────────────────────────────────────────
    def _find(self, file: str):
        return next((r for r in self._rows if r.file == file), None)

    def _ticked(self) -> list:
        return [r for r in self._rows if r.editable and r.ticked]

    def _snapshot(self) -> dict:
        flags = self._default_flags()
        rows, by_mod = [], {}
        for r in self._rows:
            a = r.answers
            era = a.get("era")
            era_s = None if era is None else ("all" if era == ("all",) else "%s-%s" % era)
            key = r.class_key()
            rows.append({
                "file": r.file, "mod": r.record.mod, "icon": r.record.icon,
                "title": a.get("title"), "variant_of": a.get("variant_of"),
                "is_default": flags.get(r.file, False),
                "stock_class": bool(key) and key in self._stock_keys,
                "era": era_s, "role": a.get("role"), "species": a.get("species"),
                "playable": a.get("playable"), "editable": r.editable, "ticked": r.ticked,
                "missing": list(self._row_missing(r)) if r.editable else [],
                "conflict": self._conflict(r) if r.editable else "",
            })
            m = by_mod.setdefault(r.record.mod, {"name": r.record.mod, "ships": 0, "keys": set()})
            m["ships"] += 1
            m["keys"].add(key or "#" + r.file.lower())
        incomplete = [x for x in rows if x["editable"] and (x["missing"] or x["conflict"])]
        status = ("All ships complete" if not incomplete else
                  "%d %s details" % (len(incomplete), "ship needs" if len(incomplete) == 1 else "ships need"))
        return {
            "mode": self._mode, "header": _HEADERS[self._mode], "intro": _INTROS[self._mode],
            "rows": rows,
            "mods": [{"name": m["name"], "ships": m["ships"], "classes": len(m["keys"])}
                     for m in by_mod.values()],
            "species": self._species, "stock_classes": self._stock,
            "eras": [{"id": e.id, "tag": e.tag, "name": e.name} for e in ERAS],
            "roles": [{"id": r.id, "label": r.label} for r in ROLES],
            "ticked": len(self._ticked()), "status": status,
            "status_ok": not incomplete, "can_continue": self._ready(),
            "error": self._error,
        }
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_mods_screen_panel.py -q -p no:cacheprovider`
Expected: all pass. Two values may need adjusting:
- The `raw_name` the `rec()` helper derives (`ship_id[4:]`) gives "Avenger" for `DCMPAvenger` and "A" for `DCMPA`; adjust a test's expected title only if it disagrees with that rule.
- `test_class_conflict_blocks_continue_and_names_it` has an unused `full` local; delete it.

Ledger either change.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ui/mods_screen_panel.py tests/unit/test_mods_screen_panel.py
git commit -m "feat(ui): ModsScreenPanel state machine (gate and home modes)"
```

---

### Task 9: The CEF page: `mods_screen.js`, `mods_screen.css`, `index.html`

**Files:**
- Create: `native/assets/ui-cef/js/mods_screen.js`, `native/assets/ui-cef/css/mods_screen.css`
- Modify: `native/assets/ui-cef/index.html` (stylesheet link beside `css/first_run.css`; a `<section id="mods-screen">` after `#first-run`; `<script src="js/mods_screen.js">` after `first_run.js`)
- Test: `tests/ui/test_mods_screen_page.py`

**Interfaces:**
- Consumes: the payload from Task 8, and `dauntlessEvent(name)` from the existing page code.
- Produces: the global `setModsScreen(payload | null)`.

The page holds **no** state decisions. It keeps only UI state: which picker is open, and whether the species field is in typing mode. It reopens an open picker after each re-render.

- [ ] **Step 1: Write the failing test**

There is no headless CEF render, so the guard is static. It checks the page wires what Python sends and emits only events the panel accepts.

```python
"""Static guard for the Mods screen page (no headless CEF render exists).

Asserts the page defines setModsScreen, is loaded by index.html, and only
emits event verbs ModsScreenPanel.dispatch_event accepts."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
JS = (ROOT / "js" / "mods_screen.js").read_text()
HTML = (ROOT / "index.html").read_text()

ACCEPTED = {"tick", "tick-mod", "clear-ticks", "set", "star",
            "continue", "skip", "play", "quit"}


def test_index_loads_the_page():
    assert 'src="js/mods_screen.js"' in HTML
    assert 'href="css/mods_screen.css"' in HTML
    assert 'id="mods-screen"' in HTML


def test_defines_the_entry_point():
    assert "function setModsScreen(payload)" in JS


def test_only_emits_accepted_verbs():
    # msSend('<verb>...') -- possibly inside an onclick string as msSend(\'...
    # -- plus msSet(), which always sends 'set:'.
    verbs = set(re.findall(r"msSend\(\\?'([a-z-]+)", JS))
    if "msSet(" in JS:
        verbs.add("set")
    assert verbs and verbs <= ACCEPTED, verbs - ACCEPTED


def test_no_native_select_or_title_tooltips():
    assert "<select" not in JS and "title=" not in JS
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/ui/test_mods_screen_page.py -q -p no:cacheprovider`
Expected: FAIL with `FileNotFoundError` for `mods_screen.js`.

- [ ] **Step 3: Implement**

`native/assets/ui-cef/index.html`:
- Add `<link rel="stylesheet" href="css/mods_screen.css">` after the `first_run.css` link.
- After the `#first-run` section, add:

```html
    <!-- Pre-boot Mods screen (sub-project 3). setModsScreen(payload|null)
         drives it; engine/ui/mods_screen_panel.py is the state machine and
         the page holds no logic. Events: dauntlessEvent('mods/<verb>...').
         Spec: docs/superpowers/specs/2026-10-01-mod-ships-screen-design.md -->
    <section id="mods-screen">
        <div class="fr-backdrop"></div>
        <div class="cp-modal ms-modal">
            <div class="cp-header" id="ms-header"></div>
            <div class="ms-body">
                <p class="ms-intro" id="ms-intro"></p>
                <div class="ms-error" id="ms-error"></div>
                <div class="ms-selbar" id="ms-selbar"></div>
                <div id="ms-table"></div>
            </div>
            <div class="cp-footer ms-footer" id="ms-footer"></div>
        </div>
        <div class="ms-menu" id="ms-menu"></div>
    </section>
```

- Add `<script src="js/mods_screen.js"></script>` after `first_run.js`.

`native/assets/ui-cef/js/mods_screen.js`:

```javascript
// The pre-boot Mods screen. Renders engine/ui/mods_screen_panel.py's payload
// and reports clicks/committed text as dauntlessEvent('mods/...'). No logic:
// Python decides every value; the page only remembers which picker is open.
var MS = { p: null, open: null, newSpecies: null };

function msEsc(t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
}
function msJs(s) { return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }
function msSend(verb) { dauntlessEvent('mods/' + verb); }
function msSet(file, field, value) {
    msSend('set:' + file + ':' + field + ':' + encodeURIComponent(value == null ? '' : value));
}

function msEraText(era) {
    if (!era) { return null; }
    if (era === 'all') { return 'All eras'; }
    var ends = era.split('-'), tag = {};
    MS.p.eras.forEach(function (e) { tag[e.id] = e.tag; });
    return ends[0] === ends[1] ? tag[ends[0]] : tag[ends[0]] + ' → ' + tag[ends[1]];
}

function msCell(r, field, text, missing) {
    if (!r.editable) { return '<span class="ms-ro">' + msEsc(text || '—') + '</span>'; }
    return '<button class="ms-cell' + (missing ? ' ms-cell--missing' : '') +
        '" onclick="msPick(event,\'' + msJs(r.file) + '\',\'' + field + '\')">' +
        msEsc(text || 'set…') + '</button>';
}

function msRow(r) {
    var roleLabel = null;
    MS.p.roles.forEach(function (x) { if (x.id === r.role) { roleLabel = x.label; } });
    var f = msJs(r.file);
    var miss = function (k) { return r.missing.indexOf(k) >= 0; };
    var check = r.editable
        ? '<button class="ms-check' + (r.ticked ? ' ms-check--on' : '') + '" onclick="msSend(\'tick:' + f + '\')">' + (r.ticked ? '✓' : '') + '</button>'
        : '';
    var title = r.editable
        ? '<input class="ms-text' + (miss('title') ? ' ms-text--bad' : '') + '" value="' + msEsc(r.title) +
          '" onchange="msSet(\'' + f + '\',\'title\',this.value)">'
        : '<span class="ms-ro ms-ro--title">' + msEsc(r.title) + '</span>';
    var variant = r.editable
        ? '<input class="ms-text ms-text--variant" placeholder="— own class —" value="' + msEsc(r.variant_of) +
          '" onfocus="msVariantMenu(this,\'' + f + '\')" oninput="msVariantMenu(this,\'' + f + '\')"' +
          ' onchange="msSet(\'' + f + '\',\'variant_of\',this.value)">'
        : '<span class="ms-ro">' + msEsc(r.variant_of || '—') + '</span>';
    var star = !r.variant_of ? '' : r.stock_class ? '<span class="ms-stock">stock default</span>'
        : '<button class="ms-star' + (r.is_default ? ' ms-star--on' : '') + '"' +
          (r.editable ? ' onclick="msSend(\'star:' + f + '\')"' : ' disabled') + '>' + (r.is_default ? '★' : '☆') + '</button>';
    var species = MS.newSpecies === r.file
        ? '<input class="ms-text" id="ms-new-species" placeholder="Species" onchange="MS.newSpecies=null;msSet(\'' + f + '\',\'species\',this.value)">'
        : msCell(r, 'species', r.species, miss('species'));
    var playable = r.playable == null ? null : (r.playable ? 'Yes' : 'No');
    return '<tr class="ms-tr' + (r.ticked ? ' ms-tr--ticked' : '') + (r.editable ? '' : ' ms-tr--ro') + '">' +
        '<td class="ms-td-check">' + check + '</td>' +
        '<td class="ms-td-icon"><img class="ms-icon" src="game-icon://ships/' + msEsc(r.icon) + '" onerror="this.style.visibility=\'hidden\'"></td>' +
        '<td class="ms-td-title">' + title + '<span class="ms-file">' + msEsc(r.file) + '.py</span></td>' +
        '<td class="ms-td-variant">' + variant + '</td>' +
        '<td class="ms-td-star">' + star + '</td>' +
        '<td>' + msCell(r, 'era', msEraText(r.era), miss('era')) + '</td>' +
        '<td>' + msCell(r, 'role', roleLabel, miss('role') || /role/.test(r.conflict)) + '</td>' +
        '<td>' + species + '</td>' +
        '<td>' + msCell(r, 'playable', playable, miss('playable')) + '</td>' +
        '</tr>' + (r.conflict ? '<tr class="ms-conflict"><td></td><td colspan="8">' + msEsc(r.conflict) + '</td></tr>' : '');
}

function msRender() {
    var p = MS.p;
    document.getElementById('ms-header').textContent = p.header;
    document.getElementById('ms-intro').textContent = p.intro;
    var err = document.getElementById('ms-error');
    err.textContent = p.error || '';
    err.style.display = p.error ? 'block' : 'none';
    var sel = document.getElementById('ms-selbar');
    sel.style.display = p.ticked ? 'flex' : 'none';
    sel.innerHTML = p.ticked ? p.ticked + ' ticked — any edit to a ticked row applies to all ' + p.ticked +
        ' <button class="ms-link" onclick="msSend(\'clear-ticks\')">Clear</button>' : '';
    var html = '<table class="ms-table"><thead><tr><th></th><th></th><th>Title</th><th>Variant of</th>' +
        '<th>Default</th><th>Era</th><th>Role</th><th>Species</th><th>Playable</th></tr></thead><tbody>';
    p.mods.forEach(function (m) {
        var mine = p.rows.filter(function (r) { return r.mod === m.name; });
        var editable = mine.filter(function (r) { return r.editable; });
        var all = editable.length && editable.every(function (r) { return r.ticked; });
        html += '<tr class="ms-modrow"><td class="ms-td-check">' + (editable.length
            ? '<button class="ms-check' + (all ? ' ms-check--on' : '') + '" onclick="msSend(\'tick-mod:' + msJs(m.name) + '\')">' + (all ? '✓' : '') + '</button>' : '') +
            '</td><td colspan="8"><span class="ms-mod">' + msEsc(m.name) + '</span><span class="ms-count">' +
            m.ships + ' ships · ' + m.classes + (m.classes === 1 ? ' class' : ' classes') + '</span></td></tr>';
        mine.forEach(function (r) { html += msRow(r); });
    });
    document.getElementById('ms-table').innerHTML = html + '</tbody></table>';
    var foot = '<button class="cp-done-button" onclick="msSend(\'quit\')">Quit</button>' +
        '<span class="ms-status' + (p.status_ok ? ' ms-status--ok' : '') + '">' + msEsc(p.status) + '</span>';
    foot += p.mode === 'gate'
        ? '<button class="cp-done-button" onclick="msSend(\'skip\')">Skip for now</button>' +
          '<button class="cp-done-button" onclick="msSend(\'continue\')"' + (p.can_continue ? '' : ' disabled') + '>Continue</button>'
        : '<button class="cp-done-button" onclick="msSend(\'play\')">Play</button>';
    document.getElementById('ms-footer').innerHTML = foot;
    var ns = document.getElementById('ms-new-species');
    if (ns) { ns.focus(); }
}

function msCloseMenu() { document.getElementById('ms-menu').style.display = 'none'; MS.open = null; }

function msShowMenu(anchor, html) {
    var menu = document.getElementById('ms-menu');
    menu.innerHTML = html;
    menu.style.display = 'block';
    var r = anchor.getBoundingClientRect(), h = Math.min(480, menu.scrollHeight);
    menu.style.top = (r.bottom + h + 8 > window.innerHeight ? r.top - h - 4 : r.bottom + 4) + 'px';
    menu.style.left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8) + 'px';
}

function msItem(label, onclick, on) {
    return '<button class="ms-menu__item' + (on ? ' ms-menu__item--on' : '') + '" onclick="' + onclick + '">' + label + '</button>';
}

function msRowOf(file) {
    var hit = null;
    MS.p.rows.forEach(function (r) { if (r.file === file) { hit = r; } });
    return hit;
}

function msPick(ev, file, field) {
    ev.stopPropagation();
    var r = msRowOf(file), f = msJs(file), html = '';
    if (field === 'playable' && r.playable != null) { msSet(file, 'playable', r.playable ? '0' : '1'); return; }
    var many = r.ticked && MS.p.ticked > 1 ? ' <span class="ms-many">(' + MS.p.ticked + ' ticked rows)</span>' : '';
    if (field === 'role') {
        html = '<div class="ms-menu__head">Role' + many + '</div>';
        MS.p.roles.forEach(function (x) { html += msItem(msEsc(x.label), "msSet('" + f + "','role','" + x.id + "');msCloseMenu()", r.role === x.id); });
    } else if (field === 'species') {
        html = '<div class="ms-menu__head">Species' + many + '</div>';
        MS.p.species.forEach(function (s) { html += msItem(msEsc(s), "msSet('" + f + "','species','" + msJs(s) + "');msCloseMenu()", r.species === s); });
        html += msItem('New…', "MS.newSpecies='" + f + "';msCloseMenu();msRender()", false);
    } else if (field === 'playable') {
        html = '<div class="ms-menu__head">Playable' + many + '</div>' +
            msItem('Yes', "msSet('" + f + "','playable','1');msCloseMenu()", false) +
            msItem('No', "msSet('" + f + "','playable','0');msCloseMenu()", false);
    } else if (field === 'era') {
        var ends = r.era && r.era !== 'all' ? r.era.split('-') : [null, null];
        var col = function (which, cur) {
            return MS.p.eras.map(function (e) {
                return '<button class="ms-era' + (cur === e.id ? ' ms-era--on' : '') + '" onclick="msSet(\'' + f + '\',\'era-' + which + '\',\'' + e.id + '\')">' +
                    '<b>' + msEsc(e.tag) + '</b><span>' + msEsc(e.name) + '</span></button>';
            }).join('');
        };
        html = '<div class="ms-menu__head">Era' + many + '</div><div class="ms-era-grid"><div><div class="ms-era-col">From</div>' +
            col('from', ends[0]) + '</div><div><div class="ms-era-col">To</div>' + col('to', ends[1]) + '</div></div>' +
            msItem('All eras (timeless)', "msSet('" + f + "','era','all');msCloseMenu()", r.era === 'all');
    }
    MS.open = { file: file, field: field };
    msShowMenu(ev.currentTarget, html);
}

function msVariantMenu(input, file) {
    var typed = input.value.trim().toLowerCase(), counts = {}, f = msJs(file);
    MS.p.rows.forEach(function (r) {
        var v = (r.variant_of || '').trim();
        if (r.file !== file && v) { counts[v] = (counts[v] || 0) + 1; }
    });
    var names = Object.keys(counts).filter(function (v) { return !typed || v.toLowerCase().indexOf(typed) >= 0; });
    names.sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); });
    var html = '<div class="ms-menu__head">Used elsewhere</div>';
    html += names.length ? names.map(function (v) {
        return msItem(msEsc(v) + ' <span class="ms-n">' + counts[v] + (counts[v] === 1 ? ' ship' : ' ships') + '</span>',
            "msSet('" + f + "','variant_of','" + msJs(v) + "');msCloseMenu()", false);
    }).join('') : '<div class="ms-menu__empty">Nothing typed on other rows yet</div>';
    if (typed) {
        var stock = MS.p.stock_classes.filter(function (c) { return c.toLowerCase().indexOf(typed) >= 0; });
        if (stock.length) {
            html += '<div class="ms-menu__head">Stock classes</div>' + stock.map(function (c) {
                return msItem(msEsc(c) + ' <span class="ms-n">stock</span>', "msSet('" + f + "','variant_of','" + msJs(c) + "');msCloseMenu()", false);
            }).join('');
        }
    }
    html += msItem('Clear (own class)', "msSet('" + f + "','variant_of','');msCloseMenu()", false);
    MS.open = { file: file, field: 'variant_of' };
    msShowMenu(input, html);
}

document.addEventListener('click', function (ev) {
    if (!ev.target.closest('#ms-menu') && !(ev.target.classList && ev.target.classList.contains('ms-text--variant'))) { msCloseMenu(); }
});

function setModsScreen(payload) {
    var root = document.getElementById('mods-screen');
    if (!root) { return; }
    if (!payload) { root.style.display = 'none'; msCloseMenu(); return; }
    var reopen = MS.open && MS.open.field === 'era' ? MS.open : null;
    MS.p = payload;
    msRender();
    root.style.display = 'flex';
    if (reopen) {
        var btns = document.querySelectorAll('.ms-cell');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].getAttribute('onclick').indexOf("'" + msJs(reopen.file) + "','era'") >= 0) {
                msPick({ stopPropagation: function () {}, currentTarget: btns[i] }, reopen.file, 'era');
            }
        }
    }
}
```

> **Icon source:** check how other panels load ship icons. Grep `ship_icons` in `native/assets/ui-cef/js/` and `engine/ui/ship_icons.py`, and copy the URL scheme they use (for example a `data:` URI from Python, or a host scheme). If icons need a Python-side URL, add `"icon_url"` to Task 8's row payload, computed with `engine.ui.ship_icons`, and use it here in place of the `game-icon://` placeholder. Ledger it as a ruling.

`native/assets/ui-cef/css/mods_screen.css`: port the spike's `gate.css` table rules, renaming `gx-` to `ms-`. Root rules mirror `#first-run` (fixed, full-viewport, centred, `z-index: 300`, Antonio):

```css
/* Pre-boot Mods screen (sub-project 3). The chrome is cp-* (configuration_panel.css);
   only the table and pickers are styled here. Root mirrors #first-run. */
#mods-screen { display: none; position: fixed; inset: 0; align-items: center;
    justify-content: center; z-index: 300; font-family: "Antonio", sans-serif; }
#mods-screen .ms-modal { width: 80vw; height: 86vh; min-width: 900px; position: relative; z-index: 1; }
.ms-body { flex: 1 1 auto; overflow-y: auto; padding: 12px 16px; }
.ms-intro { color: #cdd3dc; font-size: 14px; line-height: 1.45; margin: 0 0 10px; max-width: 70ch; }
.ms-error { display: none; color: #fff; background: rgb(90, 24, 24); border: 1px solid rgb(216, 43, 43); padding: 6px 10px; margin-bottom: 8px; }
.ms-selbar { display: none; position: sticky; top: 0; z-index: 3; align-items: center; gap: 10px;
    background: rgb(40, 34, 14); border: 1px solid rgb(255, 210, 90); color: rgb(255, 210, 90); padding: 5px 10px; margin-bottom: 8px; }
.ms-table { width: 100%; border-collapse: collapse; font-size: 13px; color: #cdd3dc; }
.ms-table th { position: sticky; top: 0; z-index: 2; background: rgb(20, 22, 28); text-align: left; font-weight: normal;
    font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(216, 132, 80, 0.9);
    padding: 6px; border-bottom: 1px solid rgb(80, 88, 100); }
.ms-table td { padding: 3px 6px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: middle; }
.ms-modrow td { background: rgb(14, 15, 20); padding-top: 10px; }
.ms-mod { font-size: 18px; color: #fff; margin-right: 10px; }
.ms-count { font-size: 12px; color: #8a93a3; letter-spacing: 0.08em; text-transform: uppercase; }
.ms-tr--ticked td { background: rgba(255, 210, 90, 0.07); }
.ms-td-icon { width: 46px; } .ms-icon { width: 44px; height: 30px; object-fit: contain; }
.ms-td-title { width: 230px; } .ms-td-variant { width: 170px; } .ms-td-star { width: 70px; }
.ms-file { display: block; font-size: 11px; color: #8a93a3; margin-top: 1px; }
.ms-text { font: inherit; font-size: 14px; color: #fff; background: rgb(28, 31, 38); border: 1px solid rgb(80, 88, 100);
    padding: 2px 6px; height: 24px; box-sizing: border-box; width: 100%; }
.ms-text:focus { outline: none; border-color: rgb(255, 210, 90); }
.ms-text--bad { border-color: rgb(255, 150, 80); }
.ms-text--variant::placeholder { color: rgb(100, 106, 118); font-style: italic; }
.ms-cell { font: inherit; font-size: 13px; color: #cdd3dc; background: transparent; border: 1px solid rgb(60, 64, 72);
    height: 24px; padding: 0 8px; cursor: pointer; white-space: nowrap; min-width: 54px; text-align: left; }
.ms-cell:hover { border-color: rgb(255, 210, 90); color: #fff; }
.ms-cell--missing { border-color: rgb(255, 150, 80); color: rgb(255, 150, 80); }
.ms-ro { color: #cdd3dc; } .ms-ro--title { color: #fff; font-size: 14px; }
.ms-tr--ro td { opacity: 0.75; }
.ms-check { width: 18px; height: 18px; border: 1px solid rgb(80, 88, 100); background: transparent; color: #111;
    font-size: 12px; line-height: 16px; padding: 0; cursor: pointer; display: block; }
.ms-check--on { background: rgb(255, 210, 90); border-color: rgb(255, 210, 90); }
.ms-star { border: 0; background: transparent; cursor: pointer; font-size: 18px; color: rgb(100, 106, 118); padding: 0 6px; }
.ms-star--on { color: rgb(255, 210, 90); }
.ms-stock { font-size: 11px; color: #8a93a3; font-style: italic; white-space: nowrap; }
.ms-conflict td { color: rgb(255, 150, 80); font-size: 12px; padding-top: 0; }
.ms-link { border: 1px solid rgb(80, 88, 100); background: transparent; color: #cdd3dc; font: inherit; font-size: 12px;
    height: 22px; padding: 0 8px; cursor: pointer; }
.ms-footer { gap: 10px; } .ms-footer .cp-done-button:first-child { margin-right: auto; }
.ms-status { color: rgb(255, 150, 80); font-size: 13px; margin-right: 8px; }
.ms-status--ok { color: rgb(150, 220, 150); }
.ms-menu { display: none; position: fixed; z-index: 310; min-width: 200px; max-height: 480px; overflow-y: auto;
    background: rgb(18, 20, 26); border: 1px solid rgb(80, 88, 100); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6); padding: 4px 0; }
.ms-menu__head { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #8a93a3; padding: 4px 12px; }
.ms-menu__item { display: block; width: 100%; text-align: left; border: 0; background: transparent; color: #cdd3dc;
    font: inherit; font-size: 14px; padding: 5px 12px; cursor: pointer; }
.ms-menu__item:hover { background: rgb(37, 26, 64); color: #fff; }
.ms-menu__item--on { color: rgb(255, 210, 90); }
.ms-menu__empty { font-size: 12px; color: #8a93a3; padding: 4px 12px 6px; font-style: italic; }
.ms-many, .ms-n { color: rgb(255, 210, 90); font-size: 11px; margin-left: 6px; text-transform: none; letter-spacing: 0; }
.ms-era-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 4px; padding: 0 4px; }
.ms-era-col { font-size: 11px; color: #8a93a3; padding: 2px 8px; text-transform: uppercase; letter-spacing: 0.1em; }
.ms-era { display: flex; flex-direction: column; align-items: flex-start; width: 100%; border: 0; background: transparent;
    color: #cdd3dc; cursor: pointer; font: inherit; padding: 3px 8px; text-align: left; }
.ms-era b { font-weight: normal; font-size: 14px; color: #fff; } .ms-era span { font-size: 11px; color: #8a93a3; }
.ms-era:hover { background: rgb(37, 26, 64); } .ms-era--on b { color: rgb(255, 210, 90); }
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/ui/test_mods_screen_page.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/assets/ui-cef/js/mods_screen.js native/assets/ui-cef/css/mods_screen.css native/assets/ui-cef/index.html tests/ui/test_mods_screen_page.py
git commit -m "feat(ui-cef): Mods screen page (table, pickers, quick-pick, default star)"
```

---

### Task 10: Native keyboard: text-event queue, key mapping, `Window`, CEF `send_key_event`, bindings

**Files:**
- Create: `native/src/renderer/include/renderer/text_input.h`, `native/src/renderer/text_input.cc`
- Modify:
  - `native/src/renderer/CMakeLists.txt` (add `text_input.cc` to `add_library(renderer STATIC …)`)
  - `native/src/renderer/include/renderer/window.h`
  - `native/src/renderer/window.cc` (ctor callbacks, move ctor/assign, `drain_text_events`)
  - `native/src/ui_cef/cef_lifecycle.{h,cc}`
  - `native/src/host/host_bindings.cc` (`drain_text_events` beside `consume_scroll_y`; `cef_send_key_event` in the CEF block, plus a stub)
  - `native/tests/renderer/CMakeLists.txt` (add `text_input_test.cc`)
  - `engine/host_io.py` (`_REQUIRED_BINDINGS`)
- Test: `native/tests/renderer/text_input_test.cc`, `tests/host/test_text_input_bindings.py`

**Interfaces:**
- Produces:
  - `renderer::TextEvent{kind, code, scancode, action, mods}`
  - `renderer::kTextEventChar = 0`, `kTextEventKey = 1`
  - `renderer::TextEventQueue`, with capacity 256 (it drops the oldest)
  - `renderer::glfw_key_to_windows_vk(int) -> int`, which returns 0 for a non-editing key
  - `Window::drain_text_events() -> std::vector<TextEvent>`
  - `ui_cef::send_key_event(int type, int windows_vk, int native_code, int character, int glfw_mods)`, where type is 0 RAWKEYDOWN, 1 KEYUP or 2 CHAR
  - Python: `drain_text_events() -> list[tuple[int,int,int,int,int]]` and `cef_send_key_event(kind, code, scancode, action, mods) -> None`

- [ ] **Step 1: Write the failing tests**

`native/tests/renderer/text_input_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/text_input.h>
#include <GLFW/glfw3.h>

using renderer::TextEvent;
using renderer::TextEventQueue;

TEST(TextInput, MapsEditingKeysToWindowsVk) {
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_BACKSPACE), 0x08);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_TAB), 0x09);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_ENTER), 0x0D);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_ESCAPE), 0x1B);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_END), 0x23);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_HOME), 0x24);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_LEFT), 0x25);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_UP), 0x26);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_RIGHT), 0x27);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_DOWN), 0x28);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_DELETE), 0x2E);
}

TEST(TextInput, NonEditingKeysMapToZero) {
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_A), 0);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_F1), 0);
}

TEST(TextInput, QueueDrainsInOrderAndEmpties) {
    TextEventQueue q;
    q.push({renderer::kTextEventChar, 'a', 0, 1, 0});
    q.push({renderer::kTextEventKey, GLFW_KEY_BACKSPACE, 51, 1, 0});
    auto out = q.drain();
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].code, 'a');
    EXPECT_EQ(out[1].kind, renderer::kTextEventKey);
    EXPECT_EQ(q.size(), 0u);
}

TEST(TextInput, QueueIsBoundedDroppingOldest) {
    TextEventQueue q;
    for (int i = 0; i < 300; ++i) q.push({renderer::kTextEventChar, i, 0, 1, 0});
    auto out = q.drain();
    ASSERT_EQ(out.size(), TextEventQueue::kCapacity);
    EXPECT_EQ(out.front().code, 300 - static_cast<int>(TextEventQueue::kCapacity));
    EXPECT_EQ(out.back().code, 299);
}
```

`tests/host/test_text_input_bindings.py`:

```python
"""The compiled module exposes the keyboard bindings (a stale .so must fail
here, not silently leave the Mods screen un-typeable)."""
import _dauntless_host as h

from engine import host_io


def test_bindings_exist():
    for name in ("drain_text_events", "cef_send_key_event", "request_relaunch"):
        assert hasattr(h, name), name


def test_bindings_are_required():
    assert {"drain_text_events", "cef_send_key_event", "request_relaunch"} <= host_io._REQUIRED_BINDINGS


def test_send_key_event_without_a_browser_is_a_noop():
    h.cef_send_key_event(0, ord("a"), 0, 1, 0)       # no browser alive in pytest
    h.cef_send_key_event(1, 259, 51, 1, 0)           # GLFW_KEY_BACKSPACE
```

(`request_relaunch` is built in Task 11. Until then, `test_bindings_exist` fails for that one name; that is expected and is fixed by Task 11's commit. Ledger it.)

- [ ] **Step 2: Add the gtest to CMake, build, and see it fail**

Add `text_input_test.cc` to `add_executable(renderer_tests …)` in `native/tests/renderer/CMakeLists.txt`.

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: FAIL with `fatal error: 'renderer/text_input.h' file not found`.

- [ ] **Step 3: Implement**

`native/src/renderer/include/renderer/text_input.h`:

```cpp
// native/src/renderer/include/renderer/text_input.h
//
// Typed text for CEF fields (Mods screen titles, class names). GLFW char and
// key callbacks push here; the host drains once per frame and forwards to
// CefBrowserHost::SendKeyEvent. Game key bindings never read this -- they
// poll glfwGetKey via Window::key_state.
#pragma once

#include <cstddef>
#include <deque>
#include <vector>

namespace renderer {

constexpr int kTextEventChar = 0;   // code = Unicode codepoint
constexpr int kTextEventKey = 1;    // code = GLFW key; only editing keys

struct TextEvent {
    int kind;
    int code;
    int scancode;   // native key code (macOS kVK_*), for CEF native_key_code
    int action;     // GLFW_PRESS / GLFW_REPEAT / GLFW_RELEASE
    int mods;       // GLFW_MOD_* bits
};

class TextEventQueue {
public:
    static constexpr std::size_t kCapacity = 256;
    void push(const TextEvent& e);
    std::vector<TextEvent> drain();
    std::size_t size() const noexcept { return q_.size(); }
private:
    std::deque<TextEvent> q_;
};

/// Windows virtual-key code for an editing key (what CEF's windows_key_code
/// expects on every platform), or 0 if `glfw_key` is not one we forward.
int glfw_key_to_windows_vk(int glfw_key) noexcept;

}  // namespace renderer
```

`native/src/renderer/text_input.cc`:

```cpp
// native/src/renderer/text_input.cc
#include "renderer/text_input.h"

#include <GLFW/glfw3.h>

namespace renderer {

void TextEventQueue::push(const TextEvent& e) {
    // Bounded: nothing drains in-game yet (sub-project 2 adds focus
    // arbitration), so the oldest events fall off rather than growing.
    if (q_.size() >= kCapacity) q_.pop_front();
    q_.push_back(e);
}

std::vector<TextEvent> TextEventQueue::drain() {
    std::vector<TextEvent> out(q_.begin(), q_.end());
    q_.clear();
    return out;
}

int glfw_key_to_windows_vk(int glfw_key) noexcept {
    switch (glfw_key) {
        case GLFW_KEY_BACKSPACE: return 0x08;  // VK_BACK
        case GLFW_KEY_TAB:       return 0x09;  // VK_TAB
        case GLFW_KEY_ENTER:     return 0x0D;  // VK_RETURN
        case GLFW_KEY_ESCAPE:    return 0x1B;  // VK_ESCAPE
        case GLFW_KEY_END:       return 0x23;  // VK_END
        case GLFW_KEY_HOME:      return 0x24;  // VK_HOME
        case GLFW_KEY_LEFT:      return 0x25;  // VK_LEFT
        case GLFW_KEY_UP:        return 0x26;  // VK_UP
        case GLFW_KEY_RIGHT:     return 0x27;  // VK_RIGHT
        case GLFW_KEY_DOWN:      return 0x28;  // VK_DOWN
        case GLFW_KEY_DELETE:    return 0x2E;  // VK_DELETE
        default:                 return 0;
    }
}

}  // namespace renderer
```

Add `text_input.cc` to `add_library(renderer STATIC …)` in `native/src/renderer/CMakeLists.txt`.

`window.h`:
- Add `#include <vector>` and `#include "renderer/text_input.h"`.
- Add the public method:

```cpp
    /// Typed characters and editing keys since the last call (oldest first),
    /// for forwarding to a CEF text field. Filled by GLFW callbacks during
    /// poll_events(); bounded (see TextEventQueue).
    std::vector<TextEvent> drain_text_events();
```

- Add the private member `TextEventQueue text_events_;`.

`window.cc`, in the constructor, after the scroll callback:

```cpp
    glfwSetCharCallback(handle_, [](GLFWwindow* w, unsigned int codepoint) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->text_events_.push({kTextEventChar, static_cast<int>(codepoint), 0, GLFW_PRESS, 0});
        }
    });

    glfwSetKeyCallback(handle_, [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (glfw_key_to_windows_vk(key) == 0) return;   // editing keys only
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->text_events_.push({kTextEventKey, key, scancode, action, mods});
        }
    });
```

In the move constructor's initializer list add `text_events_(std::move(other.text_events_)),`. In the move assignment add `text_events_ = std::move(other.text_events_);`. Then add:

```cpp
std::vector<TextEvent> Window::drain_text_events() {
    return text_events_.drain();
}
```

`cef_lifecycle.h`, after `send_mouse_wheel`:

```cpp
// Keyboard forwarding for typed CEF fields. type: 0 = RAWKEYDOWN,
// 1 = KEYUP, 2 = CHAR (character set). windows_vk is CEF's
// windows_key_code (all platforms); native_code is the platform key code
// (GLFW scancode). glfw_mods are GLFW_MOD_* bits. No-op with no browser.
void send_key_event(int type, int windows_vk, int native_code, int character, int glfw_mods);
```

`cef_lifecycle.cc`, after `send_mouse_wheel`:

```cpp
void send_key_event(int type, int windows_vk, int native_code, int character, int glfw_mods) {
    if (!g_client || !g_client->browser()) return;
    auto host = g_client->browser()->GetHost();
    if (!host) return;
    CefKeyEvent ev;
    ev.type = type == 2 ? KEYEVENT_CHAR : (type == 1 ? KEYEVENT_KEYUP : KEYEVENT_RAWKEYDOWN);
    ev.windows_key_code = windows_vk;
    ev.native_key_code = native_code;
    ev.character = static_cast<char16_t>(character);
    ev.unmodified_character = static_cast<char16_t>(character);
    uint32_t m = 0;
    if (glfw_mods & 0x1) m |= EVENTFLAG_SHIFT_DOWN;    // GLFW_MOD_SHIFT
    if (glfw_mods & 0x2) m |= EVENTFLAG_CONTROL_DOWN;  // GLFW_MOD_CONTROL
    if (glfw_mods & 0x4) m |= EVENTFLAG_ALT_DOWN;      // GLFW_MOD_ALT
    if (glfw_mods & 0x8) m |= EVENTFLAG_COMMAND_DOWN;  // GLFW_MOD_SUPER
    ev.modifiers = m;
    host->SendKeyEvent(ev);
}
```

`host_bindings.cc`:

Next to `consume_scroll_y` (outside the CEF `#ifdef`), add:

```cpp
    m.def("drain_text_events",
          []() {
              if (!g_window) {
                  throw std::runtime_error("drain_text_events: init must be called first");
              }
              py::list out;
              for (const auto& e : g_window->drain_text_events()) {
                  out.append(py::make_tuple(e.kind, e.code, e.scancode, e.action, e.mods));
              }
              return out;
          },
          "Typed characters and editing keys since the last call, oldest first, "
          "as (kind, code, scancode, action, mods); kind 0 = char (code = "
          "codepoint), 1 = key (code = GLFW key).");
```

Inside `#ifdef DAUNTLESS_ENABLE_CEF`, after `cef_send_mouse_wheel`:

```cpp
    m.def("cef_send_key_event",
          [](int kind, int code, int scancode, int action, int mods) {
              if (kind == renderer::kTextEventChar) {
                  dauntless::ui_cef::send_key_event(2, 0, 0, code, mods);
                  return;
              }
              const int vk = renderer::glfw_key_to_windows_vk(code);
              if (vk == 0) return;
              const bool up = action == GLFW_RELEASE;
              dauntless::ui_cef::send_key_event(up ? 1 : 0, vk, scancode, 0, mods);
              // Enter also needs its CHAR for the DOM to commit an <input>.
              if (!up && code == GLFW_KEY_ENTER) {
                  dauntless::ui_cef::send_key_event(2, vk, scancode, '\r', mods);
              }
          },
          py::arg("kind"), py::arg("code"), py::arg("scancode"), py::arg("action"), py::arg("mods"),
          "Forward one drain_text_events() tuple to the CEF overlay as key "
          "event(s). No-op with no browser.");
```

In the `#else` stub list, add `m.def("cef_send_key_event", [](int, int, int, int, int) {});`.

Add `#include <renderer/text_input.h>` near the other renderer includes in `host_bindings.cc`.

In `engine/host_io.py` `_REQUIRED_BINDINGS`, add `"drain_text_events"`, `"cef_send_key_event"` and `"request_relaunch"`. The last one lands in Task 11, so this file's commit belongs to Task 11's commit. Stage `host_io.py` there, not here.

- [ ] **Step 4: Build and run the native and Python tests**

```bash
cmake --build build -j 2>&1 | tail -3
ctest --test-dir build -R TextInput --output-on-failure
uv run pytest tests/host/test_text_input_bindings.py -q -p no:cacheprovider
```

Expected:
- the build succeeds
- ctest: 4 `TextInput.*` tests pass
- pytest: `test_send_key_event_without_a_browser_is_a_noop` passes; the other two fail only on `request_relaunch` (Task 11)

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/renderer/include/renderer/text_input.h native/src/renderer/text_input.cc native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/window.h native/src/renderer/window.cc native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc native/src/host/host_bindings.cc native/tests/renderer/text_input_test.cc native/tests/renderer/CMakeLists.txt tests/host/test_text_input_bindings.py
git commit -m "feat(native): GLFW text-event queue and CEF key forwarding bindings"
```

---

### Task 11: Native relaunch: `platform/relaunch`, `request_relaunch`, `host_main`

**Files:**
- Create: `native/src/platform/relaunch.h`, `native/src/platform/relaunch.cc`
- Modify:
  - `native/src/platform/CMakeLists.txt` (add `relaunch.cc` to `PLATFORM_SOURCES`)
  - `native/src/host/host_bindings.cc` (`request_relaunch`, outside the CEF block)
  - `native/src/host/host_main.cc` (after `Py_FinalizeEx`)
  - `native/tests/platform/CMakeLists.txt`
  - `engine/host_io.py`
- Test: `native/tests/platform/relaunch_test.cc`

**Interfaces:**
- Produces:
  - `platform::set_relaunch_request(std::vector<std::string>)`
  - `platform::take_relaunch_request(std::vector<std::string>*) -> bool`
  - `platform::build_relaunch_argv(exe, original_args, extra_args) -> std::vector<std::string>`
  - `platform::relaunch(argv, error&) -> int`
  - Python: `request_relaunch(extra_args: list[str]) -> None`

- [ ] **Step 1: Write the failing test**

`native/tests/platform/relaunch_test.cc`:

```cpp
#include <gtest/gtest.h>
#include "platform/relaunch.h"

using dauntless::platform::build_relaunch_argv;

TEST(RelaunchArgv, ExeFirstThenOriginalThenExtra) {
    auto a = build_relaunch_argv("/x/dauntless", {"--developer", "--game-dir", "/g"}, {"--mods"});
    EXPECT_EQ(a, (std::vector<std::string>{"/x/dauntless", "--developer", "--game-dir", "/g", "--mods"}));
}

TEST(RelaunchArgv, DoesNotDoubleAnExtraArg) {
    auto a = build_relaunch_argv("/x/dauntless", {"--mods", "--developer"}, {"--mods"});
    EXPECT_EQ(a, (std::vector<std::string>{"/x/dauntless", "--developer", "--mods"}));
}

TEST(RelaunchRequest, TakeIsOnceAndLastCallWins) {
    std::vector<std::string> out;
    EXPECT_FALSE(dauntless::platform::take_relaunch_request(&out));
    dauntless::platform::set_relaunch_request({"--a"});
    dauntless::platform::set_relaunch_request({"--mods"});
    ASSERT_TRUE(dauntless::platform::take_relaunch_request(&out));
    EXPECT_EQ(out, (std::vector<std::string>{"--mods"}));
    EXPECT_FALSE(dauntless::platform::take_relaunch_request(&out));
}
```

Add `relaunch_test.cc` to `add_executable(platform_tests …)`.

- [ ] **Step 2: Build and see it fail**

Run: `cmake --build build -j 2>&1 | tail -3`
Expected: FAIL with `'platform/relaunch.h' file not found`.

- [ ] **Step 3: Implement**

`native/src/platform/relaunch.h`:

```cpp
// native/src/platform/relaunch.h
//
// "Quit and Manage Mods": Python records a request during the game; host_main
// performs it AFTER Py_FinalizeEx (CEF and the window are already down), by
// re-executing itself with the original arguments plus the request's.
#pragma once

#include <string>
#include <vector>

namespace dauntless::platform {

void set_relaunch_request(std::vector<std::string> extra_args);
bool take_relaunch_request(std::vector<std::string>* extra_args);

/// {exe, original args minus any that appear in extra_args, extra args}.
std::vector<std::string> build_relaunch_argv(const std::string& exe,
                                             const std::vector<std::string>& original_args,
                                             const std::vector<std::string>& extra_args);

/// POSIX: execv (returns only on failure, -1, with `error` set).
/// Windows: _spawnv(_P_NOWAIT) then returns 0 (the caller exits).
int relaunch(const std::vector<std::string>& argv, std::string& error);

}  // namespace dauntless::platform
```

`native/src/platform/relaunch.cc`:

```cpp
// native/src/platform/relaunch.cc
#include "platform/relaunch.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <optional>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace dauntless::platform {

namespace {
std::optional<std::vector<std::string>>& pending() {
    static std::optional<std::vector<std::string>> p;
    return p;
}
}  // namespace

void set_relaunch_request(std::vector<std::string> extra_args) {
    pending() = std::move(extra_args);
}

bool take_relaunch_request(std::vector<std::string>* extra_args) {
    if (!pending()) return false;
    *extra_args = std::move(*pending());
    pending().reset();
    return true;
}

std::vector<std::string> build_relaunch_argv(const std::string& exe,
                                             const std::vector<std::string>& original_args,
                                             const std::vector<std::string>& extra_args) {
    std::vector<std::string> out{exe};
    for (const auto& a : original_args) {
        if (std::find(extra_args.begin(), extra_args.end(), a) == extra_args.end()) out.push_back(a);
    }
    out.insert(out.end(), extra_args.begin(), extra_args.end());
    return out;
}

int relaunch(const std::vector<std::string>& argv, std::string& error) {
    if (argv.empty()) { error = "empty argv"; return -1; }
    std::vector<char*> raw;
    for (const auto& a : argv) raw.push_back(const_cast<char*>(a.c_str()));
    raw.push_back(nullptr);
#ifdef _WIN32
    if (_spawnv(_P_NOWAIT, raw[0], raw.data()) == -1) {
        error = std::string("_spawnv: ") + std::strerror(errno);
        return -1;
    }
    return 0;
#else
    execv(raw[0], raw.data());
    error = std::string("execv: ") + std::strerror(errno);
    return -1;
#endif
}

}  // namespace dauntless::platform
```

Add `relaunch.cc` to `PLATFORM_SOURCES` in `native/src/platform/CMakeLists.txt`.

`host_bindings.cc`: add `#include "platform/relaunch.h"`, and outside the CEF block (next to `drain_text_events`):

```cpp
    m.def("request_relaunch",
          [](std::vector<std::string> extra_args) {
              dauntless::platform::set_relaunch_request(std::move(extra_args));
          },
          py::arg("extra_args"),
          "Ask host_main to re-execute the game after a clean shutdown, with the "
          "original arguments plus `extra_args` (Quit and Manage Mods). Last call "
          "wins. Only the dauntless binary honours it; the pytest .so just stores it.");
```

Check `pybind11/stl.h` is already included; add it if not.

`host_main.cc`: add `#include "platform/relaunch.h"` and `#include <vector>`. Replace the tail:

```cpp
teardown:
    if (Py_FinalizeEx() < 0) return 2;
    {
        std::vector<std::string> extra;
        if (dauntless::platform::take_relaunch_request(&extra)) {
            std::string err;
            auto exe = dauntless::platform::executable_path(argv[0], err);
            if (exe.empty()) {
                std::fprintf(stderr, "[relaunch] cannot find own executable: %s\n", err.c_str());
                return rc;
            }
            std::vector<std::string> original(argv + 1, argv + argc);
            auto args = dauntless::platform::build_relaunch_argv(exe.string(), original, extra);
            if (dauntless::platform::relaunch(args, err) != 0) {
                std::fprintf(stderr, "[relaunch] failed: %s\n", err.c_str());
            }
        }
    }
    return rc;
```

`engine/host_io.py`: add `"drain_text_events"`, `"cef_send_key_event"` and `"request_relaunch"` to `_REQUIRED_BINDINGS`, in the set literal's existing style.

- [ ] **Step 4: Build and run the tests**

```bash
cmake --build build -j 2>&1 | tail -3
ctest --test-dir build -R "Relaunch" --output-on-failure
uv run pytest tests/host/test_text_input_bindings.py -q -p no:cacheprovider
```

Expected: the build succeeds, the 3 Relaunch tests pass, and all 3 Python tests pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/platform/relaunch.h native/src/platform/relaunch.cc native/src/platform/CMakeLists.txt native/src/host/host_bindings.cc native/src/host/host_main.cc native/tests/platform/relaunch_test.cc native/tests/platform/CMakeLists.txt engine/host_io.py
git commit -m "feat(native): relaunch request honoured by host_main after Py_FinalizeEx"
```

---

### Task 12: `_run_preboot_panel` (extracted, with keyboard) and the first-run screen moved onto it

**Files:**
- Modify: `engine/host_loop.py` (`_run_first_run_screen` → new `_run_preboot_panel`), `engine/ui/first_run_panel.py` (`teardown_script`)
- Test: `tests/host/test_preboot_panel_loop.py`

**Interfaces:**
- Produces: `_run_preboot_panel(panel, view_w=1280, view_h=720) -> None`. It runs until `panel.outcome is not None` or the window closes. It forwards mouse and text events and handles Escape. On exit it pushes `panel.teardown_script`.
- Panel contract used: `name`, `outcome`, `render_payload()`, `dispatch_event()`, `invalidate()`, `teardown_script`, and optionally `handle_key_esc()`.

- [ ] **Step 1: Write the failing test**

```python
"""_run_preboot_panel: the shared pre-boot pump loop (first-run picker and the
Mods screen). Mouse and page-load behaviour are guarded by
test_first_run_pump_loop.py through _run_first_run_screen; this file covers
what the extraction added -- keyboard forwarding, Escape, teardown."""
import sys
import types

import pytest

from engine import host_loop
from tests.host.test_first_run_pump_loop import _FakeCefState


class _Panel:
    name = "mods"
    teardown_script = "setModsScreen(null);"

    def __init__(self):
        self.outcome = None
        self.esc = 0
        self.events = []

    def render_payload(self): return None
    def dispatch_event(self, a): self.events.append(a); return True
    def invalidate(self): pass
    def handle_key_esc(self): self.esc += 1


@pytest.fixture
def cef(monkeypatch):
    state = _FakeCefState()
    state.sent_keys = []
    state.queue = [(0, ord("a"), 0, 1, 0), (1, 256, 53, 1, 0)]   # 'a', then ESC press
    mod = types.ModuleType("_dauntless_host")
    for n in ("cef_execute_javascript", "cef_set_load_end_handler", "cef_set_event_handler",
              "cef_send_mouse_move", "cef_send_mouse_click", "cursor_pos", "framebuffer_size"):
        setattr(mod, n, getattr(state, n))
    mod.drain_text_events = lambda: [state.queue.pop(0)] if state.queue else []
    mod.cef_send_key_event = lambda *ev: state.sent_keys.append(ev)
    mod.keys = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0, KEY_ESCAPE=256)
    monkeypatch.setitem(sys.modules, "_dauntless_host", mod)
    state.page_loaded = True
    return state


@pytest.fixture
def renderer(monkeypatch):
    calls = {"frames": 0}
    monkeypatch.setattr(host_loop.r, "should_close", lambda: calls["frames"] >= 3)
    monkeypatch.setattr(host_loop.r, "frame", lambda: calls.__setitem__("frames", calls["frames"] + 1))
    monkeypatch.setattr(host_loop.r, "set_hologram_only_mode", lambda on, c: None)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", lambda b: False)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", lambda b: False)
    return calls


def test_text_events_are_forwarded_and_escape_reaches_the_panel(cef, renderer):
    p = _Panel()
    host_loop._run_preboot_panel(p)
    assert cef.sent_keys == [(0, ord("a"), 0, 1, 0), (1, 256, 53, 1, 0)]
    assert p.esc == 1


def test_events_route_by_panel_name(cef, renderer):
    p = _Panel()
    renderer["frames"] = 2
    host_loop._run_preboot_panel(p)
    cef.event_handler("mods/quit")
    cef.event_handler("first-run/continue")
    assert p.events == ["quit"]


def test_teardown_pushes_the_panels_script(cef, renderer):
    p = _Panel()
    host_loop._run_preboot_panel(p)
    assert cef.pushed[-1] == "setModsScreen(null);"


def test_loop_ends_on_outcome(cef, renderer):
    p = _Panel()
    p.outcome = "play"
    host_loop._run_preboot_panel(p)
    assert renderer["frames"] == 0
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/host/test_preboot_panel_loop.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.host_loop' has no attribute '_run_preboot_panel'`.

- [ ] **Step 3: Implement**

In `engine/ui/first_run_panel.py` `FirstRunPanel`, add the class attribute:

```python
    # Pushed by host_loop._run_preboot_panel when the screen ends.
    teardown_script = "setFirstRun(null);"
```

In `engine/host_loop.py`, add `_run_preboot_panel` directly above `_run_first_run_screen`. It is the existing loop body, generalised:

```python
def _run_preboot_panel(panel, view_w=1280, view_h=720):
    """Pump one full-screen CEF panel before the game loop exists, until
    `panel.outcome` is set or the window closes.

    Shared by the first-run picker and the Mods screen. Everything the first
    -run loop learned the hard way applies (see _run_first_run_screen's
    history and tests/host/test_first_run_pump_loop.py): the scene pass is
    off, the page-load handler re-invalidates the panel so its first payload
    lands, and mouse moves/edges are forwarded because run()'s own
    forwarding only exists inside the game loop. Added here: typed text and
    editing keys are drained from the window every frame and forwarded to
    CEF, and Escape is also offered to the panel (handle_key_esc).
    """
    try:
        import _dauntless_host as _h
    except ImportError:
        _h = None

    _set_handler = getattr(_h, "cef_set_event_handler", None) if _h else None
    if _set_handler is not None:
        prefix = panel.name + "/"

        def _dispatch(event: str) -> None:
            if event.startswith(prefix):
                panel.dispatch_event(event[len(prefix):])
        _set_handler(_dispatch)

    _set_load_end = getattr(_h, "cef_set_load_end_handler", None) if _h else None
    if _set_load_end is not None:
        _set_load_end(panel.invalidate)

    _cef_send_mouse_move = getattr(_h, "cef_send_mouse_move", None) if _h else None
    _cef_send_mouse_click = getattr(_h, "cef_send_mouse_click", None) if _h else None
    _drain_text = getattr(_h, "drain_text_events", None) if _h else None
    _send_key = getattr(_h, "cef_send_key_event", None) if _h else None
    _esc_key = getattr(getattr(_h, "keys", None), "KEY_ESCAPE", 256) if _h else 256

    r.set_hologram_only_mode(True, (0.0, 0.0, 0.0))
    try:
        panel.invalidate()
        while not r.should_close() and panel.outcome is None:
            script = panel.render_payload()
            if script is not None and _h is not None:
                _h.cef_execute_javascript(script)
            if _cef_send_mouse_move is not None:
                _mx, _my = _forward_mouse_to_cef(_h, _cef_send_mouse_move, view_w, view_h)
                if _cef_send_mouse_click is not None:
                    if host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                        _cef_send_mouse_click(_mx, _my, 0, True)
                    if host_io.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                        _cef_send_mouse_click(_mx, _my, 0, False)
            if _drain_text is not None and _send_key is not None:
                for ev in _drain_text():
                    _send_key(*ev)
                    # (kind, code, scancode, action, mods): an Escape press.
                    if ev[0] == 1 and ev[1] == _esc_key and ev[3] == 1 \
                            and hasattr(panel, "handle_key_esc"):
                        panel.handle_key_esc()
            r.frame()
    finally:
        r.set_hologram_only_mode(False, (0.0, 0.0, 0.0))
        if _set_load_end is not None:
            _set_load_end(lambda: None)
        if _h is not None:
            try:
                _h.cef_execute_javascript(panel.teardown_script)
            except Exception as _e:
                dev_mode.log_swallowed("pre-boot panel teardown", _e)
```

Replace the body of `_run_first_run_screen` below its docstring with:

```python
    from engine.ui.first_run_panel import FirstRunPanel

    panel = FirstRunPanel(resolution, resolver=resolver)
    _run_preboot_panel(panel, view_w, view_h)
    return panel.resolution
```

Keep the docstring, and add one line to it: "The loop itself is `_run_preboot_panel`."

- [ ] **Step 4: Run the new tests and every first-run test**

Run: `uv run pytest tests/host/test_preboot_panel_loop.py tests/host/test_first_run_pump_loop.py tests/host/test_host_loop_first_run.py tests/unit/test_first_run_panel.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/host_loop.py engine/ui/first_run_panel.py tests/host/test_preboot_panel_loop.py
git commit -m "refactor(host_loop): shared _run_preboot_panel with keyboard forwarding"
```

---

### Task 13: Mods screen orchestration and boot wiring

**Files:**
- Create: `engine/ui/mods_screen.py`
- Modify: `engine/host_loop.py` (`run()`, after the catalog boot line)
- Test: `tests/unit/test_mods_screen_orchestration.py`

**Interfaces:**
- Produces:
  - `decide_mode(argv=None) -> "gate" | "home" | None`
  - `run_mods_screen(run_panel, argv=None) -> "boot" | "quit"`, where `run_panel(panel)` blocks until the panel's outcome or the window closes
- Consumes: Tasks 5, 7, 8 and 12.

- [ ] **Step 1: Write the failing test**

```python
"""Mods screen orchestration: which mode, what each outcome does, and that a
broken screen never stops boot."""
import pytest

from engine import ship_catalog
from engine.ui import mods_screen


class _Rec:
    def __init__(self, ship_id):
        self.ship_id = ship_id
        self.errors = ()
        self.missing = ("era",)


@pytest.fixture(autouse=True)
def _clean():
    ship_catalog.reset_session()
    yield
    ship_catalog.reset_session()


def test_decide_mode(monkeypatch):
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A")])
    assert mods_screen.decide_mode([]) == "gate"
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [])
    assert mods_screen.decide_mode(["--mods"]) == "home"
    assert mods_screen.decide_mode([]) is None


def _panel_outcome(outcome):
    def run(panel):
        panel._outcome = outcome
    return run


def test_no_screen_boots(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: None)
    assert mods_screen.run_mods_screen(lambda p: pytest.fail("no screen")) == "boot"


def test_skip_hides_the_incomplete_ships(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    monkeypatch.setattr(mods_screen, "_build_panel", lambda mode, error="": _FakePanel())
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A"), _Rec("B")])
    assert mods_screen.run_mods_screen(_panel_outcome("skip")) == "boot"
    assert ship_catalog.skipped() == frozenset({"a", "b"})


def test_quit_and_closed_window_quit(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "home")
    monkeypatch.setattr(mods_screen, "_build_panel", lambda mode, error="": _FakePanel())
    assert mods_screen.run_mods_screen(_panel_outcome("quit")) == "quit"
    assert mods_screen.run_mods_screen(_panel_outcome(None)) == "quit"


def test_continue_reshows_once_then_skips(monkeypatch):
    shown = []
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    monkeypatch.setattr(mods_screen, "_build_panel",
                        lambda mode, error="": shown.append(error) or _FakePanel())
    monkeypatch.setattr(mods_screen.ship_catalog, "incomplete_ships", lambda: [_Rec("A")])
    assert mods_screen.run_mods_screen(_panel_outcome("continue")) == "boot"
    assert len(shown) == 2 and shown[1]
    assert ship_catalog.skipped() == frozenset({"a"})


def test_a_broken_screen_boots(monkeypatch):
    monkeypatch.setattr(mods_screen, "decide_mode", lambda argv=None: "gate")
    def boom(mode, error=""):
        raise RuntimeError("x")
    monkeypatch.setattr(mods_screen, "_build_panel", boom)
    assert mods_screen.run_mods_screen(lambda p: None) == "boot"


class _FakePanel:
    def __init__(self):
        self._outcome = None

    @property
    def outcome(self):
        return self._outcome
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_mods_screen_orchestration.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ui.mods_screen'`.

- [ ] **Step 3: Implement** `engine/ui/mods_screen.py`

```python
"""Orchestrate the pre-boot Mods screen (spec 2026-10-01 mod ships §1.2, §3).

run_mods_screen(run_panel) is called once from host_loop.run() after
Foundation plugins load. It never raises: any fault boots as "skip for now".
"""
from __future__ import annotations

from typing import Callable, Optional

from engine import dev_mode, mods, ship_catalog


def decide_mode(argv=None) -> Optional[str]:
    if ship_catalog.incomplete_ships():
        return "gate"
    if mods.mods_screen_requested(argv):
        return "home"
    return None


def _write_rows(rows) -> None:
    from engine.ship_catalog import gate_writer
    for row in rows:
        gate_writer.write_answers(row.mod, row.ship_id, row.attr, row.answers)
    ship_catalog.invalidate()


def _build_panel(mode: str, error: str = ""):
    from engine.ui.mods_screen_panel import ModsScreenPanel
    incomplete = ship_catalog.incomplete_ships() if mode == "gate" else []
    ids = {r.ship_id for r in incomplete}
    readonly = [r for r in ship_catalog.ships("mod") if r.ship_id not in ids]
    stock = [r.values["title"] for r in ship_catalog.ships("stock") if r.values.get("title")]
    return ModsScreenPanel(mode, incomplete, readonly,
                           species=[s.name for s in ship_catalog.species()],
                           stock_classes=stock, writer=_write_rows, error=error)


def run_mods_screen(run_panel: Callable, argv=None) -> str:
    try:
        mode = decide_mode(argv)
        if mode is None:
            return "boot"
        error = ""
        for attempt in (1, 2):
            panel = _build_panel(mode, error)
            run_panel(panel)
            outcome = panel.outcome
            if outcome in (None, "quit"):
                return "quit"
            if outcome == "play":
                return "boot"
            if outcome == "skip":
                ship_catalog.skip_for_session([r.ship_id for r in ship_catalog.incomplete_ships()])
                return "boot"
            # continue: written and re-run; re-check once.
            left = ship_catalog.incomplete_ships()
            if not left:
                return "boot"
            if attempt == 2:
                ship_catalog.skip_for_session([r.ship_id for r in left])
                return "boot"
            error = ("Some answers did not take effect: %s"
                     % "; ".join("%s: %s" % (r.ship_id, ", ".join(r.errors) or ", ".join(r.missing))
                                 for r in left))
        return "boot"
    except Exception as exc:  # noqa: BLE001 -- a gate bug must never stop boot
        dev_mode.log_swallowed("Mods screen", exc)
        try:
            ship_catalog.skip_for_session([r.ship_id for r in ship_catalog.incomplete_ships()])
        except Exception as exc2:  # noqa: BLE001
            dev_mode.log_swallowed("Mods screen skip", exc2)
        return "boot"
```

In `engine/host_loop.py` `run()`, directly after the catalog boot-line block (`_cat_text`), add:

```python
    # Pre-boot Mods screen (sub-project 3): gate mode when mod ships lack
    # metadata, home mode under --mods. Needs a live CEF page; without one
    # the boot line above has already named the incomplete ships and boot
    # proceeds. Quit here must tear CEF and the window down explicitly, like
    # the unresolved-paths exit above -- the try/finally that covers every
    # other exit has not started yet.
    if _cef_ready:
        from engine.ui import mods_screen as _mods_screen
        if _mods_screen.run_mods_screen(
                lambda p: _run_preboot_panel(p, _CEF_VIEW_W, _CEF_VIEW_H)) == "quit":
            r.cef_shutdown()
            r.shutdown()
            return 0
```

- [ ] **Step 4: Run the new tests and the host boot tests**

Run: `uv run pytest tests/unit/test_mods_screen_orchestration.py tests/host/test_host_loop_first_run.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ui/mods_screen.py engine/host_loop.py tests/unit/test_mods_screen_orchestration.py
git commit -m "feat(host): pre-boot Mods screen after Foundation plugins load"
```

---

### Task 14: Pause menu "Quit and Manage Mods"

**Files:**
- Modify: `engine/ui/pause_menu.py` (`default_pause_menu`), `engine/host_loop.py` (the `default_pause_menu(...)` call)
- Test: `tests/unit/test_pause_menu_manage_mods.py`

**Interfaces:**
- Produces: `default_pause_menu(*, on_exit, on_configuration, on_resume, on_quit_manage_mods=None)`. When the handler is given, the row "Quit and Manage Mods" (action `quit-manage-mods`) sits immediately above Exit Program.

- [ ] **Step 1: Write the failing test**

```python
from engine.ui.pause_menu import default_pause_menu


def _ids(m):
    return [it.action_id for it in m._items]


def test_row_sits_just_above_exit_when_wired():
    fired = []
    m = default_pause_menu(on_exit=lambda: None, on_configuration=lambda: None,
                           on_resume=lambda: None, on_quit_manage_mods=lambda: fired.append(1))
    ids = _ids(m)
    assert ids[-2:] == ["quit-manage-mods", "exit"]
    labels = [it.label for it in m._items]
    assert labels[-2] == "Quit and Manage Mods"
    assert m.dispatch_event("quit-manage-mods") is True and fired == [1]


def test_row_absent_without_a_handler():
    m = default_pause_menu(on_exit=lambda: None, on_configuration=lambda: None, on_resume=lambda: None)
    assert "quit-manage-mods" not in _ids(m)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_pause_menu_manage_mods.py -q -p no:cacheprovider`
Expected: FAIL with `TypeError: default_pause_menu() got an unexpected keyword argument 'on_quit_manage_mods'`.

- [ ] **Step 3: Implement**

`engine/ui/pause_menu.py`:
1. Add `on_quit_manage_mods: Optional[_Handler] = None` to the keyword-only parameters, importing `Optional` if needed.
2. Add `"quit-manage-mods"` to the dev `used` seed set.
3. Insert before `m.add_item("Exit Program", ...)`:

```python
    if on_quit_manage_mods is not None:
        # Sub-project 3: shuts down and relaunches into the pre-boot Mods
        # screen (--mods). Destructive like Exit, so it sits beside it.
        m.add_item("Quit and Manage Mods", "quit-manage-mods", on_quit_manage_mods)
```

4. Mention the row in the docstring.

`engine/host_loop.py`: above the `default_pause_menu(` call, add:

```python
        def _quit_and_manage_mods():
            # host_main re-executes us with --mods after a normal shutdown.
            try:
                import _dauntless_host as _hh
                _hh.request_relaunch(["--mods"])
            except Exception as _e:
                dev_mode.log_swallowed("request_relaunch", _e)
            pause.request_quit()
```

and pass `on_quit_manage_mods=_quit_and_manage_mods,` to `default_pause_menu(...)`.

- [ ] **Step 4: Run the new tests and the existing pause-menu tests**

Run: `uv run pytest tests/unit/test_pause_menu_manage_mods.py tests/unit/test_pause_menu_model.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ui/pause_menu.py engine/host_loop.py tests/unit/test_pause_menu_manage_mods.py
git commit -m "feat(pause): Quit and Manage Mods relaunches into the Mods screen"
```

---

### Task 15: End-to-end test, docs, gate, and the live-check list

**Files:**
- Create: `tests/integration/test_mods_screen_e2e.py`
- Modify: `CLAUDE.md` (the "Ship metadata catalog" row), `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md` (sub-project 3 status)

- [ ] **Step 1: Write the end-to-end test**

```python
"""A temp mod with two metadata-less ships sharing a SubMenu: load plugins,
gate panel opens with suggestions, fill era, Continue writes + re-runs, the
catalog is complete with one class and the right default. Skip leaves them
out of the QuickBattle injection."""
import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.ui import mods_screen

SHIP = ("import Foundation\n"
        "Foundation.ShipDef.{a} = Foundation.FedShipDef('{a}', 103, "
        "{{'name': '{n}', 'shipFile': '{a}', 'SubMenu': 'Defiant Class'}})\n"
        "Foundation.ShipDef.{a}.RegisterQBShipMenu('Fed Ships')\n"
        "Foundation.ShipDef.{a}.RegisterQBPlayerShipMenu('Fed Ships')\n")


@pytest.fixture
def mod(tmp_path, monkeypatch):
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session()
    root = tmp_path / "mods" / "DCMPv2" / "scripts"
    (root / "Custom" / "Ships").mkdir(parents=True)
    (root / "ships").mkdir(parents=True)
    for a, n in (("DCMPDefiant", "Defiant"), ("DCMPAvenger", "Avenger")):
        (root / "Custom" / "Ships" / ("%s.py" % a)).write_text(SHIP.format(a=a, n=n))
        (root / "ships" / ("%s.py" % a)).write_text("#")
    mods.configure(mods.build_index(tmp_path / "mods"))
    monkeypatch.setattr("engine.foundation.quickbattle._resolve_qb", lambda: None)
    foundation.load_plugins()
    ship_catalog.invalidate()
    yield root
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session(); mods.configure(None)


def test_gate_continue_makes_one_complete_class(mod):
    assert mods_screen.decide_mode([]) == "gate"

    def fill_and_continue(panel):
        for f in ("DCMPDefiant", "DCMPAvenger"):
            panel.dispatch_event("set:%s:era:all" % f)
        panel.dispatch_event("continue")

    assert mods_screen.run_mods_screen(fill_and_continue, argv=[]) == "boot"
    assert (mod / "Custom" / "Ships" / "zz_Dauntless_DCMPAvenger.py").is_file()
    assert ship_catalog.incomplete_ships() == []
    e = ship_catalog.entry("DCMPDefiant")
    assert e.title == "Defiant" and e.complete
    assert [v.name for v in e.variants] == ["Defiant", "Avenger"]


def test_skip_hides_both_ships(mod):
    assert mods_screen.run_mods_screen(lambda p: p.dispatch_event("skip"), argv=[]) == "boot"
    assert ship_catalog.skipped() == frozenset({"dcmpdefiant", "dcmpavenger"})
    assert ship_catalog.entry("DCMPDefiant") is None
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_mods_screen_e2e.py -q -p no:cacheprovider`
Expected: both pass. If either fails, debug with superpowers:systematic-debugging; do not weaken the assertions.

- [ ] **Step 3: Update the docs**

- In the `CLAUDE.md` "Ship metadata catalog" row, append:

  > Sub-project 3 adds classes by name (`variant_of`, one starred `class_default`), the pre-boot **Mods screen** (`engine/ui/mods_screen{,_panel}.py`; gate mode for incomplete mod ships, read-only home under `--mods` / pause **Quit and Manage Mods**, a relaunch via `platform/relaunch`), and CEF keyboard input (pre-boot only). Spec `2026-10-01-mod-ships-screen-design.md`.

- In the roadmap's sub-project 3 row, change the status to "implemented on `feat/qb-mod-gate`, awaiting live check".

- [ ] **Step 4: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures`. Any new failure is this branch's regression: fix it.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add tests/integration/test_mods_screen_e2e.py CLAUDE.md docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md
git commit -m "test(mods_screen): end-to-end gate; docs and roadmap status"
```

- [ ] **Step 6: Hand over the live checks to Mark** (do not launch the game yourself)

These need a live run from the **main checkout** after merge, and headless tests cannot see them:

1. **Typing on macOS** in the Title and Variant of cells: Backspace, arrows, Enter, Tab.
2. **The gate on the two real mods:** fill the table, press Continue, boot. On the next launch there is no gate.
3. **`./build/dauntless --mods`** opens home mode; Play boots.
4. **Pause → Quit and Manage Mods** relaunches into home mode, and `--developer` survives.
5. **Nested Quick Battle menus** now appear for DCMPv2 ("Defiant Class") and LC ("LC Intrepid Class").
