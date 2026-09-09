# Foundation Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mod that registers ships through Foundation has those ships appear in QuickBattle and spawn correctly, with no edit to any stock file and no change to our CEF picker.

**Architecture:** An engine-owned `Foundation` module, shadowing any mod-supplied one via the existing project-root shim precedence. It offers the ~12 names real ship mods call, and registers ships by feeding QuickBattle's five static ship tables — the same tables stock ships use — so modded and stock ships travel one code path. A loader walks `Custom/Autoload/` then `Custom/Ships/` at boot, before QuickBattle builds its panes.

**Tech Stack:** Python 3 (`engine/`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md`

## Global Constraints

- **Never spell `game` or `sdk` as a path segment** outside `engine/paths.py`. Kind-label literals need a `# paths-guard: <reason>` comment. `tests/unit/test_path_indirection.py` parses (not greps) for it.
- **Never capture a path at import.** No module-level constant may hold one.
- **NEVER run destructive git.** Banned: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. This checkout is shared with concurrent sessions and holds deliberately-uncommitted work these destroy with no undo. Stage with explicit pathspecs; never stage `build/`.
- **Do NOT create `game/` or `sdk/` directories** anywhere in this worktree — `engine/paths.py` treats an in-project one as a real BC install root, and a fabricated one previously broke 18 unrelated tests. Fixtures go under `tmp_path`.
- **Tests may not depend on real mod content.** `mods/` is gitignored; all fixtures are synthetic trees in `tmp_path`.
- **A modless / Foundation-less boot must be byte-identical.** With no mods installed, nothing registers and no stock table is mutated.
- **Unknown surface degrades to a report, never a crash.** An unseen `<Race>ShipDef`, an unknown attribute, a tech that is not installed — all are recorded and reported, following the overlay's existing rule that a mod which silently does nothing is a support nightmare.
- Run pytest via `uv run pytest`. The gate is `scripts/check_tests.sh`.
- Current baseline: pytest **1 failure** (`tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`, ledgered); ctest green. `tests/unit/test_ship_death.py::test_blasts_keep_lighting_the_scene_across_the_throes` is known-flaky — re-run it alone before treating it as a regression.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/mods.py` (modify) | `sfx` becomes a placeable content directory. |
| `engine/foundation/__init__.py` (create) | The public surface: `ShipDef`, the `<Race>ShipDef` factory family, `shipList`, `SoundDef`, `load_plugins`. |
| `engine/foundation/shipdef.py` (create) | The ShipDef objects and the dict-like `shipList`. |
| `engine/foundation/quickbattle.py` (create) | `ST_` allocation and injection into QuickBattle's five tables. |
| `engine/foundation/loader.py` (create) | Walks `Custom/Autoload` then `Custom/Ships`; per-script failure isolation; the report. |
| `Foundation.py` (create, project root) | Thin re-export so `import Foundation` resolves ours before any mod's. |
| `engine/host_loop.py` (modify) | Call `load_plugins()` at boot, after the SDK finder is installed. |
| `tests/unit/test_foundation_*.py` (create) | Unit coverage per module. |
| `tests/host/test_foundation_quickbattle_e2e.py` (create) | The pane-build test that proves a registered ship is really selectable. |

---

### Task 1: `sfx/` becomes a placeable content directory

**Files:**
- Modify: `engine/mods.py` (`_TARGET_FOR`, and whatever maps a target to its root)
- Modify: `docs/superpowers/specs/2026-09-08-mod-overlay-design.md` (its `sfx/` non-goal is superseded)
- Test: `tests/unit/test_mods_index.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `_TARGET_FOR` gains `"sfx": "game"`, so a mod's `sfx/**` is indexed and `paths.game_asset("sfx/…")` resolves it

**Why first:** `SoundDef` (Task 6) registers a sound by path, and the only real example points at `sfx/Weapons/ZZ_KlingonTMP2.wav` inside a mod. Without this, `SoundDef` cannot be meaningfully tested — it would register a sound that can never play.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_mods_index.py

def test_sfx_maps_to_the_game_target(tmp_path):
    """A mod's sfx/ tree is placeable content, not an unplaced curiosity.

    The real BC install root holds data/, scripts/ AND sfx/, and
    engine/lip_sync_runtime.py already resolves "sfx/..." through
    game_asset(). A voice or weapon-sound pack ships only sfx/, so without
    this such a mod reports "no BC content found" and contributes nothing.
    """
    _touch(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("sfx/Weapons/zap.wav")
    assert hit is not None
    assert hit.target == "game"
    assert hit.abs_path == tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav"


def test_sfx_is_no_longer_reported_unplaced(tmp_path):
    _touch(tmp_path / "M" / "sfx" / "a.wav")
    idx = mods.build_index(tmp_path)
    status = {m.name: m for m in idx.mods}["M"]
    assert status.unplaced == []
    assert status.placed == 1


def test_sfx_content_root_is_found_from_sfx_alone(tmp_path):
    """A mod shipping ONLY sfx/ must still be recognised as BC content."""
    _touch(tmp_path / "SoundPack" / "sfx" / "Weapons" / "a.wav")
    assert mods.find_content_root(tmp_path / "SoundPack") == tmp_path / "SoundPack"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_index.py -k sfx -v`
Expected: FAIL — `sfx` is neither in `CONTENT_DIRS` nor `_TARGET_FOR`, so the lookup returns None and `unplaced == ["sfx"]`.

- [ ] **Step 3: Write minimal implementation**

In `engine/mods.py`, add `sfx` to both the content-root markers and the target map:

```python
CONTENT_DIRS = frozenset({"data", "scripts", "sfx"})

_TARGET_FOR = {
    "data": "game",     # paths-guard: kind label, keys paths.game_root()
    "scripts": "sdk",   # paths-guard: kind label, keys paths.sdk_scripts()
    "sfx": "game",      # paths-guard: kind label, keys paths.game_root()
}
```

`sfx` keeps its top-level segment exactly as `data` does, because callers pass `"sfx/..."` paths — only the `scripts` target drops its segment (the SDK scripts directory *is* the root). The existing `keep = rel_parts if target == "game" else rel_parts[1:]` already produces this; do not add a third branch.

Then amend the overlay spec: its `sfx/` non-goal is superseded. Replace that bullet with a line recording that `sfx/` is now placeable and why, so the two specs do not contradict each other.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_index.py tests/unit/test_mods_report.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: only the baselined failure.

- [ ] **Step 6: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_index.py docs/superpowers/specs/2026-09-08-mod-overlay-design.md
git commit -m "feat(mods): sfx/ is placeable content"
```

---

### Task 2: The ShipDef family and shipList

**Files:**
- Create: `engine/foundation/__init__.py`, `engine/foundation/shipdef.py`
- Test: `tests/unit/test_foundation_shipdef.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ShipDef` — a bare namespace; mods assign `ShipDef.<Name> = …` and read `ShipDef.__dict__[name]`
  - `FedShipDef(abbrev, species, details=None, dict=None)` and any other `<Race>ShipDef`, synthesised on demand
  - `ShipDefinition` — the object those return
  - `shipList` — dict-like with `has_key`, `__getitem__`, `__setitem__`, `_keyList`
  - `ShipDefinition.race: str`, `.abbrev`, `.species`, `.name`, `.iconName`, `.shipFile`, `.desc`, `.SubMenu`, `.SubSubMenu`, `.hasTGLName`, `.hasTGLDesc`, `.dTechs`, `.friendlyDetails`, `.enemyDetails`, `.unknown_attributes: dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_foundation_shipdef.py
"""Foundation's ship-definition surface, as real mods use it."""

import pytest

from engine import foundation


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    yield
    foundation.reset()


def _make(name="LCintrepidZZ"):
    return foundation.FedShipDef(
        name, 42, {"name": "U.S.S. Intrepid", "iconName": "LCIntrepid",
                   "shipFile": name})


def test_fedshipdef_carries_the_details_dict():
    d = _make()
    assert d.name == "U.S.S. Intrepid"
    assert d.iconName == "LCIntrepid"
    assert d.shipFile == "LCintrepidZZ"
    assert d.abbrev == "LCintrepidZZ"
    assert d.species == 42
    assert d.race == "Fed"


def test_shipdef_namespace_assignment_and_dict_readback():
    # Exactly the shape generated ship scripts use.
    foundation.ShipDef.LCintrepidZZ = _make()
    foundation.ShipDef.LCintrepidZZ.desc = "a ship"
    assert foundation.ShipDef.__dict__["LCintrepidZZ"].desc == "a ship"


def test_borg_shipdef_is_a_distinct_race():
    d = foundation.BorgShipDef("Cube", 7, {"name": "Cube"})
    assert d.race == "Borg"


def test_an_unseen_race_is_synthesised_not_an_error():
    """Foundation has races we have never seen in a mod. A KlingonShipDef
    must not raise AttributeError at import and take the whole mod down."""
    d = foundation.KlingonShipDef("Vorcha", 3, {"name": "Vor'cha"})
    assert d.race == "Klingon"
    assert "KlingonShipDef" in foundation.synthesised_races()


def test_a_non_shipdef_attribute_still_raises():
    # The __getattr__ hook must not swallow genuine typos.
    with pytest.raises(AttributeError):
        foundation.TotallyUnrelatedThing


def test_details_lists_are_indexable_at_two():
    # Generated boilerplate does friendlyDetails[2] = ... unconditionally.
    d = _make()
    d.friendlyDetails[2] = "x"
    d.enemyDetails[2] = "y"
    assert d.friendlyDetails[2] == "x"
    assert d.enemyDetails[2] == "y"


def test_optional_attributes_default_and_accept():
    d = _make()
    assert d.desc == ""
    assert d.SubMenu is None and d.SubSubMenu is None
    assert d.dTechs == {}
    d.SubMenu, d.SubSubMenu = "TNG Ships", "Intrepid Class"
    d.hasTGLName, d.hasTGLDesc = 1, 1
    d.dTechs = {"AutoTargeting": {"Phaser": [2, 1]}}
    assert d.dTechs["AutoTargeting"]["Phaser"] == [2, 1]


def test_unknown_attributes_are_recorded_not_rejected():
    """A third mod will set something these two do not. Record it so the
    report can name it, rather than failing the import."""
    d = _make()
    d.someFutureFlag = 3
    assert d.unknown_attributes["someFutureFlag"] == 3


def test_shiplist_is_dict_like_with_keylist():
    # The generated tail: shipList._keyList.has_key(longName)
    foundation.shipList["U.S.S. Intrepid"] = _make()
    assert foundation.shipList._keyList.has_key("U.S.S. Intrepid")
    assert not foundation.shipList._keyList.has_key("nope")
    assert foundation.shipList.has_key("U.S.S. Intrepid")
    assert foundation.shipList["U.S.S. Intrepid"].shipFile == "LCintrepidZZ"


def test_generated_boilerplate_tail_runs_end_to_end():
    """The exact five lines every Bridge Commander Universal Tool script
    ends with. If this raises, every generated mod fails at import."""
    longName = "U.S.S. Intrepid"
    foundation.ShipDef.LCintrepidZZ = _make()
    foundation.shipList[longName] = foundation.ShipDef.LCintrepidZZ
    foundation.ShipDef.__dict__[longName] = foundation.ShipDef.LCintrepidZZ

    if foundation.shipList._keyList.has_key(longName):
        foundation.ShipDef.__dict__[longName].friendlyDetails[2] = \
            foundation.shipList[longName].friendlyDetails[2]
        foundation.ShipDef.__dict__[longName].enemyDetails[2] = \
            foundation.shipList[longName].enemyDetails[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_shipdef.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.foundation'`

- [ ] **Step 3: Write minimal implementation**

`engine/foundation/shipdef.py`:

```python
"""Foundation's ship-definition objects.

Surface recovered from the call sites of real mods, not from Foundation's
source -- see docs/engine/foundation-api-surface.md for why, and
docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md for
which names and how they were measured.
"""
from __future__ import annotations

# Attributes a ship definition is known to carry. Anything else a mod sets
# is recorded in `unknown_attributes` rather than rejected: our corpus is
# two mods, and a third will set something neither of them does.
_KNOWN = frozenset({
    "race", "abbrev", "species", "name", "iconName", "shipFile", "desc",
    "SubMenu", "SubSubMenu", "hasTGLName", "hasTGLDesc", "dTechs",
    "friendlyDetails", "enemyDetails", "menuGroup", "playerMenuGroup",
})


_ALL_DEFINITIONS: list = []


def all_definitions() -> list:
    return list(_ALL_DEFINITIONS)


class ShipDefinition:
    """One registered ship. Attribute-set is how mods configure it."""

    def __init__(self, race, abbrev, species, details=None, dict=None):
        # `dict` shadows the builtin deliberately: Foundation's own keyword
        # is spelled that way and mods pass it positionally or by name.
        object.__setattr__(self, "unknown_attributes", {})
        # Every definition ever built, so describe() can report declared
        # techs without the caller having to hand them over. Registration
        # into ShipDef is a mod's choice; existing is not.
        _ALL_DEFINITIONS.append(self)
        self.race = race
        self.abbrev = abbrev
        self.species = species
        details = details or {}
        self.name = details.get("name", abbrev)
        self.iconName = details.get("iconName", abbrev)
        self.shipFile = details.get("shipFile", abbrev)
        self.desc = ""
        self.SubMenu = None
        self.SubSubMenu = None
        self.hasTGLName = 0
        self.hasTGLDesc = 0
        self.dTechs = {}
        self.menuGroup = None
        self.playerMenuGroup = None
        # Generated scripts subscript index 2 unconditionally.
        self.friendlyDetails = [None, None, None]
        self.enemyDetails = [None, None, None]
        self.modes = (dict or {}).get("modes", [])

    def __setattr__(self, key, value):
        if key not in _KNOWN and not key.startswith("_") \
                and key not in ("modes", "unknown_attributes"):
            self.unknown_attributes[key] = value
        object.__setattr__(self, key, value)


class _ShipDefNamespace:
    """`Foundation.ShipDef` -- mods assign onto it and read __dict__ back."""


class ShipList:
    """Dict-like, with the `_keyList` generated scripts reach into.

    Every Bridge Commander Universal Tool script ends with
    `if Foundation.shipList._keyList.has_key(longName):`, so _keyList is
    required surface rather than an implementation detail.
    """

    def __init__(self):
        self._items = {}
        self._keyList = self

    def has_key(self, k):
        return k in self._items

    def __contains__(self, k):
        return k in self._items

    def __getitem__(self, k):
        return self._items[k]

    def __setitem__(self, k, v):
        self._items[k] = v

    def keys(self):
        return list(self._items.keys())

    def __len__(self):
        return len(self._items)
```

`engine/foundation/__init__.py`:

```python
"""Foundation compatibility -- the surface real BC ship mods call.

Ours always wins over a mod-supplied Foundation.py: `Foundation.py` at the
project root is checked by _SDKFinder BEFORE the mod index, an ordering the
mod overlay chose deliberately so our own replacements cannot be overridden.

Spec: docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md
"""
from __future__ import annotations

import re

from engine.foundation.shipdef import ShipDefinition, ShipList, _ShipDefNamespace

ShipDef = _ShipDefNamespace()
shipList = ShipList()

_RACE_FACTORY = re.compile(r"^([A-Z][A-Za-z0-9]*)ShipDef$")
_synthesised: set = set()


def synthesised_races():
    """Race factories a mod asked for that we had not anticipated."""
    return set(_synthesised)


def __getattr__(attr):
    """Synthesise `<Race>ShipDef` on demand.

    Foundation has race variants we have never seen in a mod -- Klingon,
    Romulan, Cardassian and more. Hardcoding only the two our corpus uses
    would make an unseen one an AttributeError at import, taking the whole
    mod down for a name we could have handled. The race is only a label
    plus a default side/AI, so synthesising is safe.

    Deliberately narrow: anything not matching <Race>ShipDef still raises,
    so a genuine typo is not swallowed.
    """
    m = _RACE_FACTORY.match(attr)
    if not m:
        raise AttributeError(attr)
    race = m.group(1)
    _synthesised.add(attr)

    def factory(abbrev, species, details=None, dict=None):
        return ShipDefinition(race, abbrev, species, details, dict)

    factory.__name__ = attr
    return factory


def reset():
    """Drop all registered state. Tests only."""
    global ShipDef, shipList
    for k in [k for k in ShipDef.__dict__ if not k.startswith("_")]:
        delattr(ShipDef, k)
    shipList._items.clear()
    _synthesised.clear()
    # Definitions accumulate on construction, so this must be cleared too
    # or they leak between tests and inflate describe()'s tech list.
    from engine.foundation.shipdef import _ALL_DEFINITIONS
    _ALL_DEFINITIONS.clear()
```

Note `FedShipDef` and `BorgShipDef` are not defined explicitly — they come from `__getattr__` like every other race, which is what makes an unseen race work.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_shipdef.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/foundation tests/unit/test_foundation_shipdef.py
git commit -m "feat(foundation): ShipDef family and dict-like shipList"
```

---

### Task 3: QuickBattle registration

**Files:**
- Create: `engine/foundation/quickbattle.py`
- Modify: `engine/foundation/__init__.py` (expose registration on `ShipDefinition`)
- Test: `tests/unit/test_foundation_quickbattle.py`

**Interfaces:**
- Consumes: Task 2's `ShipDefinition`
- Produces:
  - `ST_MOD_BASE = 1000`
  - `allocate_ship_type(name) -> int` — stable per name within a run
  - `register(ship_def, group, player=False) -> int` — injects into all five tables, returns the id
  - `ShipDefinition.RegisterQBShipMenu(group)` / `.RegisterQBPlayerShipMenu(group)`
  - `registered() -> list[tuple[str, int]]`

**The five tables** (read from the module, not from memory):

| Table | Key → value |
|---|---|
| `g_dShipNameToType` | `"Sovereign"` → `ST_SOVEREIGN` |
| `g_dShipNameToIconNumber` | `"Sovereign"` → icon number |
| `g_dFriendlyShipTypeToDetails` | `ST_*` → `[script, label, destroyed_event, ai_module, side]` |
| `g_dEnemyShipTypeToDetails` | `ST_*` → same shape, enemy side |
| `g_dShipTypeToIconNumber` | `ST_*` → icon number |

Two are keyed by **name** and three by **id**; get both directions right.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_foundation_quickbattle.py
"""Registration into QuickBattle's five static ship tables."""

import pytest

from engine import foundation
from engine.foundation import quickbattle


class _FakeQB:
    """Stands in for the SDK QuickBattle module.

    Mirrors the real module's five tables and stock id range so the test
    exercises the same shapes without importing the SDK.
    """

    def __init__(self):
        self.g_dShipNameToType = {"Sovereign": 10, "Galaxy": 9}
        self.g_dShipNameToIconNumber = {"Sovereign": 1, "Galaxy": 2}
        self.g_dFriendlyShipTypeToDetails = {
            10: ["Sovereign", "Sovereign", "QBFriendlySovereignDestroyed",
                 "QuickBattleFriendlyAI", "Friendly"]}
        self.g_dEnemyShipTypeToDetails = {
            10: ["Sovereign", "Sovereign", "QBEnemySovereignDestroyed",
                 "QuickBattleEnemyAI", "Enemy"]}
        self.g_dShipTypeToIconNumber = {10: 1, 9: 2}


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def _ship(name="LCintrepidZZ"):
    return foundation.FedShipDef(
        name, 42, {"name": "U.S.S. Intrepid", "iconName": "LCIntrepid",
                   "shipFile": name})


def test_allocated_ids_cannot_collide_with_stock():
    # Stock occupies 0..30. Anything we mint must be far clear of it.
    ids = [quickbattle.allocate_ship_type("s%d" % i) for i in range(50)]
    assert min(ids) >= quickbattle.ST_MOD_BASE == 1000
    assert len(set(ids)) == 50


def test_the_same_ship_keeps_its_id():
    a = quickbattle.allocate_ship_type("LCintrepidZZ")
    b = quickbattle.allocate_ship_type("LCintrepidZZ")
    assert a == b


def test_register_populates_all_five_tables():
    qb = _FakeQB()
    d = _ship()
    sid = quickbattle.register(d, "Fed Ships", qb=qb)

    assert qb.g_dShipNameToType["U.S.S. Intrepid"] == sid
    assert "U.S.S. Intrepid" in qb.g_dShipNameToIconNumber
    assert sid in qb.g_dShipTypeToIconNumber
    for table, side in ((qb.g_dFriendlyShipTypeToDetails, "Friendly"),
                        (qb.g_dEnemyShipTypeToDetails, "Enemy")):
        row = table[sid]
        assert row[0] == "LCintrepidZZ"        # ship script
        assert row[1] == "U.S.S. Intrepid"     # label
        assert row[4] == side


def test_register_does_not_disturb_stock_rows():
    qb = _FakeQB()
    before = dict(qb.g_dFriendlyShipTypeToDetails)
    quickbattle.register(_ship(), "Fed Ships", qb=qb)
    assert qb.g_dFriendlyShipTypeToDetails[10] == before[10]
    assert qb.g_dShipNameToType["Sovereign"] == 10


def test_registration_is_recorded_for_the_report():
    qb = _FakeQB()
    quickbattle.register(_ship(), "Fed Ships", qb=qb)
    assert ("U.S.S. Intrepid", 1000) in quickbattle.registered()


def test_shipdef_methods_register():
    qb = _FakeQB()
    d = _ship()
    d.RegisterQBShipMenu("Fed Ships", qb=qb)
    d.RegisterQBPlayerShipMenu("Fed Ships", qb=qb)
    assert d.name in qb.g_dShipNameToType


def test_absent_quickbattle_module_is_not_fatal():
    """QuickBattle may not be importable in every context (a bridge-only
    mission, a tool). Registration must record the intent and move on."""
    d = _ship()
    d.RegisterQBShipMenu("Fed Ships", qb=None)
    assert ("U.S.S. Intrepid", 1000) in quickbattle.registered()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_quickbattle.py -v`
Expected: FAIL — `ImportError: cannot import name 'quickbattle'`

- [ ] **Step 3: Write minimal implementation**

`engine/foundation/quickbattle.py`:

```python
"""Register Foundation ships into QuickBattle's static ship tables.

BC's QuickBattle holds literal dicts keyed by ST_* integers (ST_MARAUDER=0
.. ST_TRANSPORT=30), which is why Foundation replaces the file wholesale --
its readme says it "replaces the static indexes of Bridge Commander with
dynamic structures". We instead extend those same tables, so modded and
stock ships travel one code path and everything that reads them (mission
scripts, the AI named in each row, the destroyed-event wiring) sees modded
ships too.

Our CEF picker needs no change: it walks the live widget tree QuickBattle
builds from these tables, not a list of its own.
"""
from __future__ import annotations

# Stock occupies 0..30. Start far clear of it so no future BC content
# addition could close the gap.
ST_MOD_BASE = 1000

_ids: dict = {}
_registered: list = []


def reset():
    _ids.clear()
    _registered.clear()


def allocate_ship_type(key) -> int:
    """A stable id for this ship within the run."""
    if key not in _ids:
        _ids[key] = ST_MOD_BASE + len(_ids)
    return _ids[key]


def registered() -> list:
    return list(_registered)


def _resolve_qb():
    """The live SDK QuickBattle module, or None if not importable."""
    import importlib
    try:
        return importlib.import_module("QuickBattle.QuickBattle")
    except Exception:
        return None


# Distinguishes "caller said nothing" from "caller explicitly said there is
# no QuickBattle module". A plain None default cannot: the tests need to pass
# qb=None meaning "no module", while an omitted qb must resolve the live one.
_UNSET = object()


def register(ship_def, group, player: bool = False, qb=_UNSET) -> int:
    """Inject `ship_def` into QuickBattle's five tables. Returns its id.

    `qb` omitted resolves the live module; pass a module (or a stand-in) to
    inject into it, or an explicit None to record the registration with no
    module present.
    """
    sid = allocate_ship_type(ship_def.name)
    entry = (ship_def.name, sid)
    if entry not in _registered:
        _registered.append(entry)

    module = _resolve_qb() if qb is _UNSET else qb
    if module is None:
        # No QuickBattle in this context (bridge-only mission, a tool).
        # The intent is recorded; nothing to inject into.
        return sid

    icon = getattr(ship_def, "icon_number", 0)
    module.g_dShipNameToType[ship_def.name] = sid
    module.g_dShipNameToIconNumber[ship_def.name] = icon
    module.g_dShipTypeToIconNumber[sid] = icon

    for table_name, side, ai in (
            ("g_dFriendlyShipTypeToDetails", "Friendly", "QuickBattleFriendlyAI"),
            ("g_dEnemyShipTypeToDetails", "Enemy", "QuickBattleEnemyAI")):
        table = getattr(module, table_name)
        table[sid] = [
            ship_def.shipFile,
            ship_def.name,
            "QB%sGenericShipDestroyed" % side,
            ai,
            side,
        ]
    return sid
```

Then on `ShipDefinition` (in `shipdef.py`), add the two methods mods call:

```python
    def RegisterQBShipMenu(self, group=None, **kw):
        # **kw so an omitted qb stays omitted and reaches register()'s own
        # _UNSET default; passing qb=None explicitly must mean "no module".
        from engine.foundation import quickbattle
        self.menuGroup = group
        return quickbattle.register(self, group, player=False, **kw)

    def RegisterQBPlayerShipMenu(self, group=None, **kw):
        from engine.foundation import quickbattle
        self.playerMenuGroup = group
        return quickbattle.register(self, group, player=True, **kw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_quickbattle.py tests/unit/test_foundation_shipdef.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/foundation tests/unit/test_foundation_quickbattle.py
git commit -m "feat(foundation): register ships into QuickBattle's ship tables"
```

---

### Task 4: The plugin loader

**Files:**
- Create: `engine/foundation/loader.py`
- Modify: `engine/foundation/__init__.py` (expose `load_plugins`)
- Test: `tests/unit/test_foundation_loader.py`

**Interfaces:**
- Consumes: Tasks 2-3
- Produces:
  - `load_plugins() -> LoadReport`
  - `LoadReport` with `.autoload: list[str]`, `.ships: list[str]`, `.failures: list[tuple[str, str]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_foundation_loader.py
"""Walking Custom/Autoload and Custom/Ships.

Neither directory is imported by BC itself -- Foundation is what loads
them, which is exactly why an installed mod's ships currently do nothing.
"""

import sys

import pytest

from engine import foundation, mods
from engine.foundation import loader, quickbattle


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def _mod(tmp_path, name="M"):
    return tmp_path / name / "scripts" / "Custom"


def test_autoload_runs_before_ships(tmp_path):
    """Plugins register resources ship definitions may reference, so they
    go first. Order is asserted, not assumed."""
    order = tmp_path / "order.txt"
    _touch(_mod(tmp_path) / "Autoload" / "a_plugin.py",
           "open(%r, 'a').write('autoload\\n')" % str(order))
    _touch(_mod(tmp_path) / "Ships" / "a_ship.py",
           "open(%r, 'a').write('ship\\n')" % str(order))

    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()

    assert order.read_text().split() == ["autoload", "ship"]


def test_filename_order_is_honoured_within_a_directory(tmp_path):
    """Real plugins carry numeric prefixes (FTech ships
    000-Fixes20030305-FoundationTriggers.py) so authors rely on it."""
    order = tmp_path / "order.txt"
    for n in ("300-c.py", "000-a.py", "100-b.py"):
        _touch(_mod(tmp_path) / "Autoload" / n,
               "open(%r, 'a').write('%s\\n')" % (str(order), n))

    mods.configure(mods.build_index(tmp_path))
    loader.load_plugins()

    assert order.read_text().split() == ["000-a.py", "100-b.py", "300-c.py"]


def test_one_raising_script_does_not_stop_the_others(tmp_path):
    ok = tmp_path / "ok.txt"
    _touch(_mod(tmp_path) / "Ships" / "a_bad.py", "raise ValueError('boom')")
    _touch(_mod(tmp_path) / "Ships" / "b_good.py",
           "open(%r, 'a').write('ran\\n')" % str(ok))

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert ok.read_text().strip() == "ran"
    assert any("a_bad" in name and "ValueError" in err
               for name, err in report.failures)


def test_no_mods_loads_nothing_and_does_not_raise(tmp_path):
    mods.configure(mods.build_index(tmp_path / "absent"))
    report = loader.load_plugins()
    assert report.ships == [] and report.autoload == [] and report.failures == []


def test_a_ship_script_can_register_through_the_real_surface(tmp_path):
    _touch(_mod(tmp_path) / "Ships" / "s.py",
           "import Foundation\n"
           "Foundation.ShipDef.X = Foundation.FedShipDef('X', 1, {'name': 'X'})\n"
           "Foundation.ShipDef.X.RegisterQBShipMenu('Fed Ships', qb=None)\n")

    mods.configure(mods.build_index(tmp_path))
    report = loader.load_plugins()

    assert report.failures == []
    assert ("X", 1000) in quickbattle.registered()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'loader'`

- [ ] **Step 3: Write minimal implementation**

`engine/foundation/loader.py`:

```python
"""Walk and execute a mod's Custom/Autoload and Custom/Ships scripts.

Neither directory is imported by BC: Foundation loads them. Ordering is
Autoload first, then Ships, because plugins register resources (sounds,
and later systems and TGL tables) that ship definitions may reference.

⚠️ That ordering is INFERRED, not established -- we do not have
Foundation's own. It is the safe direction, and it is the first assumption
to revisit if a mod misbehaves.

Within a directory, filename order: real plugins carry numeric prefixes
(FTech ships 000-Fixes20030305-FoundationTriggers.py), so authors rely on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoadReport:
    autoload: list = field(default_factory=list)
    ships: list = field(default_factory=list)
    failures: list = field(default_factory=list)   # (script, "Type: msg")


_SUBDIRS = (("Autoload", "autoload"), ("Ships", "ships"))


def _scripts_in(index, subdir):
    """Mod-provided Custom/<subdir>/*.py, folded-key sorted.

    Reads the mod index rather than the filesystem so only enabled mods
    contribute and the overlay's own resolution rules apply.
    """
    prefix = ("custom/%s/" % subdir).lower()
    out = []
    for key, mf in index.files.items():
        if mf.target != "sdk":          # paths-guard: kind label
            continue
        if key.startswith(prefix) and key.endswith(".py"):
            out.append((key, mf))
    out.sort(key=lambda kv: kv[0])
    return out


def load_plugins() -> LoadReport:
    """Execute every enabled mod's Foundation plugin scripts."""
    import runpy

    from engine import mods

    report = LoadReport()
    index = mods.current()

    for subdir, bucket in _SUBDIRS:
        for key, mf in _scripts_in(index, subdir):
            try:
                runpy.run_path(str(mf.abs_path), run_name="__foundation__")
            except Exception as exc:
                # One broken mod must not stop the others registering --
                # the same rule build_index follows for an unreadable mod,
                # and for the same reason: silence is a support nightmare.
                report.failures.append(
                    (key, "%s: %s" % (type(exc).__name__, exc)))
                continue
            getattr(report, bucket).append(key)
    return report
```

Expose it from `engine/foundation/__init__.py`:

```python
def load_plugins():
    from engine.foundation.loader import load_plugins as _lp
    return _lp()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/foundation tests/unit/test_foundation_loader.py
git commit -m "feat(foundation): load Custom/Autoload and Custom/Ships plugins"
```

---

### Task 5: The project-root shim

**Files:**
- Create: `Foundation.py` (project root)
- Test: `tests/unit/test_foundation_shim.py`

**Interfaces:**
- Consumes: Tasks 2-4
- Produces: `import Foundation` resolves to ours, ahead of any mod-supplied `Foundation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_foundation_shim.py
"""`import Foundation` must reach OURS, never a mod's.

_SDKFinder checks PROJECT_ROOT before the mod index -- an ordering the mod
overlay chose deliberately, because project-root shims are our own
replacements and must not be overridable. A mod pack bundling Foundation's
real Foundation.py would otherwise win, and that file is Python 1.5 and
monkeypatches QuickBattle.py and loadspacehelper.py, both of which we have
reimplemented.
"""

import pytest

from engine import mods


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    mods.configure(None)
    yield
    mods.configure(None)


def test_import_foundation_reaches_the_engine_module():
    import Foundation
    from engine import foundation
    assert Foundation.FedShipDef is not None
    assert Foundation.ShipDef is foundation.ShipDef
    assert Foundation.shipList is foundation.shipList


def test_a_mod_supplied_foundation_does_not_win(tmp_path):
    _touch(tmp_path / "M" / "scripts" / "Foundation.py",
           "MARKER = 'from the mod'\n")
    mods.configure(mods.build_index(tmp_path))

    import importlib
    import sys
    sys.modules.pop("Foundation", None)
    try:
        m = importlib.import_module("Foundation")
        assert not hasattr(m, "MARKER"), (
            "a mod-supplied Foundation.py shadowed ours")
    finally:
        sys.modules.pop("Foundation", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_shim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Foundation'`

- [ ] **Step 3: Write minimal implementation**

`Foundation.py` at the project root:

```python
"""Foundation — project-root shim shadowing any mod-supplied Foundation.py.

A thin re-export; the implementation is engine/foundation/. This file exists
at the root for one reason: _SDKFinder checks PROJECT_ROOT before the mod
index, so being here is what makes ours win over a bundled copy.

Joins App.py, LoadBridge.py and LoadDamageHitSounds.py. See the
"Project-root SDK shims" section of CLAUDE.md -- this is the fourth, and
that note asks us to consider grouping them into shims/ at the third.

Spec: docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md
"""
from engine.foundation import *          # noqa: F401,F403
from engine.foundation import (          # noqa: F401
    ShipDef, shipList, load_plugins, reset, synthesised_races,
)


def __getattr__(attr):
    # Forward <Race>ShipDef synthesis to the engine module.
    from engine import foundation
    return getattr(foundation, attr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_shim.py -v`
Expected: PASS

- [ ] **Step 5: Confirm the path-indirection guard still passes**

Run: `uv run pytest tests/unit/test_path_indirection.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Foundation.py tests/unit/test_foundation_shim.py
git commit -m "feat(foundation): project-root shim so ours wins over a bundled copy"
```

---

### Task 6: SoundDef

**Files:**
- Modify: `engine/foundation/__init__.py`
- Test: `tests/unit/test_foundation_sounddef.py`

**Interfaces:**
- Consumes: Task 1 (`sfx/` placeable), Task 4 (loader runs Autoload)
- Produces: `SoundDef(file, name, volume=1.0, dict=None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_foundation_sounddef.py
"""Foundation.SoundDef -- the one Autoload call in the corpus.

The LC Intrepid Pack's Custom/Autoload/ZZ_Intrepid.py is exactly:
    Foundation.SoundDef("sfx/Weapons/ZZ_KlingonTMP2.wav", "VoyPhoton", 1.0)
"""

import pytest

from engine import foundation, mods


def _touch(p, body=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    mods.configure(None)
    yield
    foundation.reset()
    mods.configure(None)


def test_sounddef_registers_through_the_sound_manager(monkeypatch):
    calls = []

    class _FakeMgr:
        def LoadSound(self, path, name, loadspec):
            calls.append((path, name, loadspec))
            return object()

    monkeypatch.setattr(foundation, "_sound_manager", lambda: _FakeMgr())
    foundation.SoundDef("sfx/Weapons/Zap.wav", "VoyPhoton", 1.0)

    assert calls and calls[0][1] == "VoyPhoton"
    assert calls[0][0].endswith("sfx/Weapons/Zap.wav")


def test_sounddef_resolves_a_mod_supplied_file(tmp_path, monkeypatch):
    """The whole point of Task 1: the wav lives in the MOD, not the install."""
    _touch(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav")
    mods.configure(mods.build_index(tmp_path))

    seen = []
    monkeypatch.setattr(
        foundation, "_sound_manager",
        lambda: type("M", (), {"LoadSound": lambda s, p, n, l: seen.append(p)})())
    foundation.SoundDef("sfx/Weapons/Zap.wav", "VoyPhoton", 1.0)

    assert seen and str(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav") in seen[0]


def test_sounddef_failure_is_reported_not_raised(monkeypatch):
    """A missing sound must not abort the Autoload script that declares it."""
    def _boom():
        raise RuntimeError("no audio")
    monkeypatch.setattr(foundation, "_sound_manager", _boom)
    foundation.SoundDef("sfx/nope.wav", "X", 1.0)   # must not raise
    assert any("X" in s for s in foundation.sound_failures())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_sounddef.py -v`
Expected: FAIL — `AttributeError: module 'engine.foundation' has no attribute 'SoundDef'`

- [ ] **Step 3: Write minimal implementation**

In `engine/foundation/__init__.py`:

```python
_sound_failures: list = []


def sound_failures() -> list:
    return list(_sound_failures)


def _sound_manager():
    """The live TGSoundManager. Indirected so tests can substitute one."""
    import App
    return App.g_kSoundManager


def SoundDef(file, name, volume=1.0, dict=None):
    """Register a named sound, as LoadTacticalSounds.py does.

    `file` is install-relative (e.g. "sfx/Weapons/X.wav") and resolves
    through paths.game_asset, so a mod-supplied wav is found -- which is
    why sfx/ had to become placeable content first.

    A failure is recorded, never raised: an unplayable sound must not abort
    the Autoload script that declares it.
    """
    from engine import paths
    try:
        path = str(paths.game_asset(file))
        _sound_manager().LoadSound(path, name, 0)
    except Exception as exc:
        _sound_failures.append("%s (%s): %s: %s"
                               % (name, file, type(exc).__name__, exc))
```

Add `_sound_failures.clear()` to `reset()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_sounddef.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/foundation tests/unit/test_foundation_sounddef.py
git commit -m "feat(foundation): SoundDef registers mod-supplied sounds"
```

---

### Task 7: Boot wiring, reporting, and the end-to-end test

**Files:**
- Modify: `engine/host_loop.py` (call `load_plugins()` after the SDK finder is installed)
- Modify: `engine/mods.py` (`describe()` gains the Foundation lines)
- Test: `tests/unit/test_foundation_report.py`, `tests/host/test_foundation_quickbattle_e2e.py`

**Interfaces:**
- Consumes: every earlier task
- Produces: `foundation.describe(report) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/host/test_foundation_quickbattle_e2e.py
"""A registered ship must be a REAL QuickBattle ship, not just a menu row.

This enters above the tables deliberately: it builds QuickBattle's panes
and asserts the ship is present as a button. Asserting only that the tables
gained a row would pass while the ship remained unspawnable -- "listed but
won't spawn" is the failure this whole design exists to avoid, and entering
one layer lower would not catch it.
"""

import pytest

from engine import foundation, mods
from engine.foundation import quickbattle
from tests.helpers.bc_assets import require_game_dir


def _touch(p, body=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)
    yield
    foundation.reset()
    quickbattle.reset()
    mods.configure(None)


def test_a_foundation_ship_appears_in_the_quickbattle_panes(tmp_path):
    require_game_dir("data/Models/Ships")

    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "s.py",
           "import Foundation\n"
           "Foundation.ShipDef.ZZTest = Foundation.FedShipDef(\n"
           "    'ZZTest', 1, {'name': 'ZZ Test Ship', 'shipFile': 'ZZTest'})\n"
           "Foundation.ShipDef.ZZTest.RegisterQBShipMenu('Fed Ships')\n")

    mods.configure(mods.build_index(tmp_path))
    report = foundation.load_plugins()
    assert report.failures == [], report.failures

    import importlib
    qb = importlib.import_module("QuickBattle.QuickBattle")

    # The tables must know it...
    assert "ZZ Test Ship" in qb.g_dShipNameToType
    sid = qb.g_dShipNameToType["ZZ Test Ship"]
    assert sid in qb.g_dFriendlyShipTypeToDetails

    # ...and the built panes must show it.
    qb.BuildDialog()
    labels = _all_button_labels(qb.g_pShipsPane)
    assert "ZZ Test Ship" in labels, (
        "the ship registered into the tables but never reached the picker; "
        "found: %r" % (labels,))


def _all_button_labels(pane):
    """Every button label under a ship pane, at any depth."""
    from engine.appc.characters import STButton
    out = []
    stack = [pane]
    while stack:
        w = stack.pop()
        for child in getattr(w, "GetChildren", lambda: [])():
            if isinstance(child, STButton):
                out.append(child.GetLabel())
            stack.append(child)
    return out
```

```python
# tests/unit/test_foundation_report.py

from engine import foundation
from engine.foundation.loader import LoadReport


def test_report_names_ships_plugins_and_failures():
    r = LoadReport(autoload=["custom/autoload/a.py"],
                   ships=["custom/ships/s.py"],
                   failures=[("custom/ships/bad.py", "ValueError: boom")])
    text = foundation.describe(r)
    assert "1 ship" in text and "1 plugin" in text
    assert "bad.py" in text and "ValueError" in text


def test_report_is_empty_when_nothing_loaded():
    assert foundation.describe(LoadReport()) == ""


def test_report_names_declared_but_absent_techs():
    """FTech itself logs and continues when a ship declares a tech that is
    not installed, so this is the ecosystem's own behaviour -- we just say
    so instead of staying silent."""
    d = foundation.FedShipDef("X", 1, {"name": "X"})
    d.dTechs = {"AutoTargeting": {}, "Ablative Armour": {}}
    text = foundation.describe(LoadReport(ships=["s.py"]))
    assert "AutoTargeting" in text and "not installed" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_foundation_report.py tests/host/test_foundation_quickbattle_e2e.py -v`
Expected: FAIL — `AttributeError: module 'engine.foundation' has no attribute 'describe'`

- [ ] **Step 3: Write minimal implementation**

In `engine/foundation/__init__.py`:

```python
def describe(report) -> str:
    """The boot report. Empty when nothing loaded, like mods.describe()."""
    if not (report.ships or report.autoload or report.failures):
        return ""

    lines = ["foundation:"]
    if report.ships:
        lines.append("  %d ship script(s), %d registered"
                     % (len(report.ships), len(_registered_names())))
    if report.autoload:
        lines.append("  %d plugin(s) run" % len(report.autoload))

    # Every tech any definition declares is "not installed" while
    # FoundationTech is out of scope. FTech itself logs and continues in
    # this exact case, so this reports the ecosystem's own behaviour
    # rather than announcing a fault of ours.
    from engine.foundation.shipdef import all_definitions
    techs = sorted({t for d in all_definitions() for t in (d.dTechs or {})})
    if techs:
        lines.append("  techs declared but not installed: %s"
                     % ", ".join(techs))

    races = sorted(synthesised_races() - {"FedShipDef", "BorgShipDef"})
    if races:
        lines.append("  unanticipated race factories used: %s"
                     % ", ".join(races))

    for name, err in _sound_failures_as_pairs():
        lines.append("  WARNING sound %s: %s" % (name, err))
    for script, err in report.failures:
        lines.append("  WARNING %s failed: %s" % (script, err))
    return "\n".join(lines)


def _registered_names():
    from engine.foundation import quickbattle
    return [n for n, _sid in quickbattle.registered()]


def _sound_failures_as_pairs():
    return [(s.split(" ", 1)[0], s) for s in _sound_failures]
```

In `engine/host_loop.py`, after the SDK finder is installed and before any mission loads:

```python
    # Foundation plugins register ships into QuickBattle's tables, so this
    # must run before any QuickBattle pane is built. The SDK finder has to
    # be installed first: Custom/Ships scripts do `import Foundation` and
    # import other SDK modules.
    from engine import foundation as _foundation
    _fnd_report = _foundation.load_plugins()
    _fnd_text = _foundation.describe(_fnd_report)
    if _fnd_text:
        print(_fnd_text, file=_sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_foundation_report.py tests/host/test_foundation_quickbattle_e2e.py -v`
Expected: PASS

- [ ] **Step 5: Run the FULL gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure it names that is not the baselined one is a regression this branch introduced — fix it, do not baseline it.

- [ ] **Step 6: Commit**

```bash
git add engine/foundation engine/host_loop.py engine/mods.py tests/unit/test_foundation_report.py tests/host/test_foundation_quickbattle_e2e.py
git commit -m "feat(foundation): load plugins at boot and report what registered"
```

---

## Live verification (Mark only)

The gate cannot see whether a ship is really selectable, and this project's convention is that Claude never launches the game. After Task 7, with both test mods installed:

1. Boot with no mods → no Foundation output at all; QuickBattle unchanged.
2. Boot with the two mods → stderr names 9 ships registered and 1 plugin run.
3. **QuickBattle → the Steamrunner and the three Intrepid variants appear in the ship lists.** This is the acceptance test: it is the thing that has never worked.
4. Select one as the player ship and start the battle — it must spawn, be flyable, and have working AI as an opponent. A ship that appears but will not spawn means the table injection is shaped wrongly, which is exactly the failure the E2E test is built to catch first.
5. The Steamrunner's report line should say its `AutoTargeting` tech is not installed.
