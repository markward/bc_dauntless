# Quick Battle Setup Screen and Group Battle Start: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Quick Battle setup panel with the approved spike's screen, built on the ship catalog. Replace BC's `GenerateShips` with deterministic group placement: allegiance, direction, distance, per-group difficulty and named ships.

**Architecture:**
- A new pure package, `engine/quickbattle/`, holds the scenario model, presets, naming, placement and stats. It produces a `BattlePlan`.
- `spawn.py` wraps only the SDK's `QuickBattle.GenerateShips` and spawns from the current plan. BC's start chain, AI assignment, win/lose and End Combat stay untouched.
- The CEF panel is a Python-owned state machine. The JS is a stateless renderer ported from the spike.

**Tech Stack:** Python 3 (engine, pytest), the SDK QuickBattle module through the App shim, CEF HTML/CSS/JS (cp-\* modal family).

**Spec:** `docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md`. Read it in full before any task. The roadmap (`docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md`, "Standing decisions → Setup screen") is binding too.

**Design reference:** the spike at `.claude/worktrees/qb-setup-spike/spikes/quickbattle-setup/` (`index.html`, `app.js`, `spike.css`, `data.js`), branch `spike/quickbattle-setup` @ `e11c4af1`. Read-only: never edit it.

## Global Constraints

- **Branch:** `feat/qb-setup-screen`. Never commit to `main`; check `git branch --show-current` before every commit.
- **Shared checkout:**
  - Stage with explicit pathspecs only.
  - Never `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A` or `git add .`.
  - To mutate a file temporarily: `cp` it to `/tmp`, edit, then `cp` it back and `diff` to prove the restore.
- **Never launch the game** (`./build/dauntless`). Live checks are Mark's.
- **Units:** distances are GU inside the engine. km → GU only through `engine.units.GU_TO_KM` (1 GU = 0.175 km). Never name a variable `*_m`.
- **Rotation:** `R.GetCol(0)` = starboard, `GetCol(1)` = fore, `GetCol(2)` = dorsal (right-handed). Never `GetRow`.
- **Paths:** never spell `game` or `sdk` as a path segment. Use `engine.paths`, and resolve at use, never at import.
- **Enums are string ids:**
  - allegiance `friendly|enemy|neutral`
  - direction `fore|aft|port|starboard|dorsal|ventral`
  - distance `close|standard|long|out_of_range`, which is 20/35/80/150 km
  - difficulty `low|medium|high`, which is AI level 0.0/0.5/1.0
- **Off-screen CEF:** no HTML5 drag-and-drop, no `<select>`, no `title=` attributes. Menus, dropdowns and hover text are page-drawn.
- **UX fidelity (spec D11):** as close to the spike as possible. Port markup, layout, spacing, states and copy.
- **Test commands:** `uv run pytest <path> -q`. The merge gate is `scripts/check_tests.sh`. Never call a failure "pre-existing" without running the gate.
- **Commits end with:**

  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  ```

## Review Focus

1. **A preset saved with a mod ship that is later removed.** Loading it must drop that row, keep the rest, and log once. If it was the player ship, the player falls back to the Galaxy. Pinned in Task 3 (`test_reconcile_*`) and Task 9 (`test_preset_load_reconciles`).
2. **Two rows with the same named ship, one of them the player.** The player keeps the bare name and the other gets " (2)". Pinned in Task 2 and Task 3.
3. **XO "Restart Simulation" or "Start Simulation" without opening the screen.** It must spawn the *current* setup, not a stale one. The provider computes at call time. Pinned in Task 7 (`test_generate_ships_reads_provider_at_call_time`).
4. **A ship script that fails to create mid-battle-start.** The rest of the battle must still spawn. Pinned in Task 7 (`test_one_failing_ship_does_not_stop_the_rest`).
5. **The stats probe must not corrupt a live mission's property templates.** The snapshot is restored even when a probe raises. Pinned in Task 6 (`test_probe_restores_templates_on_failure`).

---

### Task 1: Scenario model

**Files:**
- Create: `engine/quickbattle/__init__.py`
- Create: `engine/quickbattle/scenario.py`
- Test: `tests/unit/test_qb_scenario.py`

**Interfaces:**
- Produces:
  - **Constants** in `engine.quickbattle.scenario`: `ALLEGIANCES`, `DIRECTIONS`, `DISTANCE_IDS`, `DISTANCE_KM: dict[str, float]`, `DIFFICULTY_LEVEL: dict[str, float]`, `DEFAULT_PLAYER_SHIP = "Galaxy"`.
  - **Dataclasses:**
    - `Entry(id, ship, variant=None, player=False)`
    - `Group(id, name, allegiance, direction, distance, difficulty="medium", player=False, custom_name=False, entries=[])`
    - `Scenario(groups)`
  - **Functions:**
    - `new_id() -> str`
    - `default_scenario() -> Scenario`
    - `from_json(d: dict) -> Scenario` (raises `ValueError`)
    - `same_setup(a, b) -> bool`
  - **`Scenario` methods:**
    - `to_json()`
    - `group(gid)`
    - `find_entry(eid) -> (Group, Entry) | (None, None)`
    - `player_group()`, `player_entry()`
    - `auto_name(allegiance, exclude_gid=None)`
    - `add_group() -> Group`
    - `delete_group(gid) -> bool`
    - `rename_group(gid, name) -> bool`
    - `update_details(gid, allegiance, direction, distance, difficulty) -> bool`
    - `add_ship(gid, ship) -> Entry | None`
    - `remove_entry(eid) -> bool`
    - `move_entry(eid, gid) -> bool`
    - `set_variant(eid, variant) -> bool`
    - `set_player_ship(ship)`
    - `can_start() -> bool`
    - `first_non_player_group() -> Group | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_qb_scenario.py
"""Scenario model: defaults, invariants, edits, JSON round-trip.
Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md §2"""
import pytest

from engine.quickbattle import scenario as sc


def test_default_scenario_has_player_group_and_empty_enemy_group():
    s = sc.default_scenario()
    assert [g.name for g in s.groups] == ["Friendly group", "Enemy group"]
    pg = s.player_group()
    assert pg.player and pg.allegiance == "friendly"
    assert pg.direction is None and pg.distance is None
    assert [(e.ship, e.player) for e in pg.entries] == [("Galaxy", True)]
    eg = s.groups[1]
    assert (eg.allegiance, eg.direction, eg.distance, eg.difficulty) == \
        ("enemy", "fore", "standard", "medium")
    assert eg.entries == []
    assert not s.can_start()


def test_ids_are_unique_strings():
    s = sc.default_scenario()
    ids = [g.id for g in s.groups] + [e.id for g in s.groups for e in g.entries]
    assert len(set(ids)) == len(ids) and all(isinstance(i, str) and i for i in ids)


def test_add_group_is_enemy_fore_standard_with_first_free_number():
    s = sc.default_scenario()
    g2 = s.add_group()
    g3 = s.add_group()
    assert (g2.allegiance, g2.direction, g2.distance, g2.difficulty) == \
        ("enemy", "fore", "standard", "medium")
    assert g2.name == "Enemy group 2" and g3.name == "Enemy group 3"
    s.delete_group(g2.id)
    assert s.add_group().name == "Enemy group 2"


def test_player_group_cannot_be_deleted_and_player_entry_cannot_move_or_go():
    s = sc.default_scenario()
    pg, pe = s.player_group(), s.player_entry()
    assert not s.delete_group(pg.id)
    assert not s.remove_entry(pe.id)
    assert not s.move_entry(pe.id, s.groups[1].id)
    assert s.player_entry() is pe


def test_add_move_remove_entries_and_can_start():
    s = sc.default_scenario()
    eg = s.groups[1]
    e = s.add_ship(eg.id, "Warbird")
    assert e is not None and s.can_start()
    g2 = s.add_group()
    assert s.move_entry(e.id, g2.id)
    assert eg.entries == [] and g2.entries[-1] is e
    assert s.remove_entry(e.id) and not s.can_start()
    assert s.add_ship("nope", "Warbird") is None


def test_escort_counts_for_can_start():
    s = sc.default_scenario()
    s.add_ship(s.player_group().id, "Akira")
    assert s.can_start()


def test_update_details_follows_allegiance_when_name_unedited():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert s.update_details(eg.id, "neutral", "port", "close", "high")
    assert (eg.allegiance, eg.direction, eg.distance, eg.difficulty) == \
        ("neutral", "port", "close", "high")
    assert eg.name == "Neutral group"
    s.rename_group(eg.id, "Bystanders")
    s.update_details(eg.id, "enemy", "port", "close", "high")
    assert eg.name == "Bystanders" and eg.custom_name


def test_update_details_rejects_bad_values():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert not s.update_details(eg.id, "hostile", "fore", "standard", "medium")
    assert not s.update_details(eg.id, "enemy", "up", "standard", "medium")
    assert not s.update_details(eg.id, "enemy", "fore", "far", "medium")
    assert not s.update_details(eg.id, "enemy", "fore", "standard", "insane")
    assert eg.allegiance == "enemy"


def test_player_group_details_change_only_difficulty():
    s = sc.default_scenario()
    pg = s.player_group()
    assert s.update_details(pg.id, "enemy", "aft", "long", "low")
    assert (pg.allegiance, pg.direction, pg.distance, pg.difficulty) == \
        ("friendly", None, None, "low")


def test_rename_ignores_empty_and_unchanged():
    s = sc.default_scenario()
    eg = s.groups[1]
    assert not s.rename_group(eg.id, "   ")
    assert not s.rename_group(eg.id, "Enemy group")
    assert not eg.custom_name
    assert s.rename_group(eg.id, "  Raiders ")
    assert eg.name == "Raiders" and eg.custom_name


def test_set_player_ship_swaps_in_place_and_resets_variant():
    s = sc.default_scenario()
    pe = s.player_entry()
    s.set_variant(pe.id, "USS Venture")
    s.set_player_ship("Sovereign")
    assert s.player_entry() is pe
    assert (pe.ship, pe.variant) == ("Sovereign", None)


def test_json_round_trip_and_same_setup_ignores_ids():
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "Warbird")
    d = s.to_json()
    t = sc.from_json(d)
    assert sc.same_setup(s, t)
    assert t.to_json() == d
    other = sc.default_scenario()
    other.add_ship(other.groups[1].id, "Warbird")
    assert sc.same_setup(s, other)            # different ids, same setup
    other.groups[1].difficulty = "high"
    assert not sc.same_setup(s, other)


@pytest.mark.parametrize("mutate", [
    lambda d: d["groups"].clear(),
    lambda d: d["groups"][0].update(player=False),
    lambda d: d["groups"][1]["entries"].append(
        {"id": "x", "ship": "Akira", "variant": None, "player": True}),
    lambda d: d["groups"][1].update(allegiance="hostile"),
    lambda d: d["groups"][0].update(allegiance="enemy"),
])
def test_from_json_rejects_broken_invariants(mutate):
    d = sc.default_scenario().to_json()
    mutate(d)
    with pytest.raises(ValueError):
        sc.from_json(d)


def test_first_non_player_group():
    s = sc.default_scenario()
    assert s.first_non_player_group() is s.groups[1]
    s.delete_group(s.groups[1].id)
    assert s.first_non_player_group() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_qb_scenario.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.quickbattle'`.

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/__init__.py
"""Quick Battle setup: scenario model, presets, placement, stats, spawning.

Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md
"""
```

```python
# engine/quickbattle/scenario.py
"""The Quick Battle scenario: groups of ships, the player, placements.

Pure: no App, no catalog, no files. Invariants live HERE, not in the UI:
exactly one player group holding exactly one player entry; the player group is
always friendly with no direction/distance; the player entry never moves or
goes. Every enum is a string id so saved presets survive reordering.

Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md §2
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Optional

ALLEGIANCES = ("friendly", "enemy", "neutral")
DIRECTIONS = ("fore", "aft", "port", "starboard", "dorsal", "ventral")
DISTANCE_IDS = ("close", "standard", "long", "out_of_range")
DISTANCE_KM = {"close": 20.0, "standard": 35.0, "long": 80.0, "out_of_range": 150.0}
DIFFICULTY_LEVEL = {"low": 0.0, "medium": 0.5, "high": 1.0}
DEFAULT_PLAYER_SHIP = "Galaxy"

_ALLEGIANCE_LABEL = {"friendly": "Friendly", "enemy": "Enemy", "neutral": "Neutral"}


def new_id() -> str:
    return secrets.token_hex(4)


@dataclass
class Entry:
    id: str
    ship: str                      # CatalogEntry.ship_id (the class)
    variant: Optional[str] = None  # Variant.name; None = class default
    player: bool = False


@dataclass
class Group:
    id: str
    name: str
    allegiance: str
    direction: Optional[str]
    distance: Optional[str]
    difficulty: str = "medium"
    player: bool = False
    custom_name: bool = False
    entries: list = field(default_factory=list)


@dataclass
class Scenario:
    groups: list

    # ── lookup ──────────────────────────────────────────────────────────
    def group(self, gid) -> Optional[Group]:
        for g in self.groups:
            if g.id == gid:
                return g
        return None

    def find_entry(self, eid):
        for g in self.groups:
            for e in g.entries:
                if e.id == eid:
                    return g, e
        return None, None

    def player_group(self) -> Group:
        return next(g for g in self.groups if g.player)

    def player_entry(self) -> Entry:
        return next(e for e in self.player_group().entries if e.player)

    def first_non_player_group(self) -> Optional[Group]:
        return next((g for g in self.groups if not g.player), None)

    def can_start(self) -> bool:
        return any(not e.player for g in self.groups for e in g.entries)

    # ── naming ──────────────────────────────────────────────────────────
    def auto_name(self, allegiance: str, exclude_gid=None) -> str:
        base = _ALLEGIANCE_LABEL[allegiance] + " group"
        taken = {g.name for g in self.groups if g.id != exclude_gid}
        if base not in taken:
            return base
        n = 2
        while "%s %d" % (base, n) in taken:
            n += 1
        return "%s %d" % (base, n)

    # ── group edits ─────────────────────────────────────────────────────
    def add_group(self) -> Group:
        g = Group(id=new_id(), name=self.auto_name("enemy"), allegiance="enemy",
                  direction="fore", distance="standard")
        self.groups.append(g)
        return g

    def delete_group(self, gid) -> bool:
        g = self.group(gid)
        if g is None or g.player:
            return False
        self.groups.remove(g)
        return True

    def rename_group(self, gid, name) -> bool:
        g = self.group(gid)
        name = (name or "").strip()
        if g is None or not name or name == g.name:
            return False
        g.name, g.custom_name = name, True
        return True

    def update_details(self, gid, allegiance, direction, distance, difficulty) -> bool:
        g = self.group(gid)
        if g is None or difficulty not in DIFFICULTY_LEVEL:
            return False
        if g.player:
            g.difficulty = difficulty
            return True
        if (allegiance not in ALLEGIANCES or direction not in DIRECTIONS
                or distance not in DISTANCE_IDS):
            return False
        changed = allegiance != g.allegiance
        g.allegiance, g.direction, g.distance, g.difficulty = \
            allegiance, direction, distance, difficulty
        if changed and not g.custom_name:
            g.name = self.auto_name(allegiance, exclude_gid=g.id)
        return True

    # ── entry edits ─────────────────────────────────────────────────────
    def add_ship(self, gid, ship) -> Optional[Entry]:
        g = self.group(gid)
        if g is None or not ship:
            return None
        e = Entry(id=new_id(), ship=ship)
        g.entries.append(e)
        return e

    def remove_entry(self, eid) -> bool:
        g, e = self.find_entry(eid)
        if e is None or e.player:
            return False
        g.entries.remove(e)
        return True

    def move_entry(self, eid, gid) -> bool:
        g, e = self.find_entry(eid)
        dest = self.group(gid)
        if e is None or e.player or dest is None or dest is g:
            return False
        g.entries.remove(e)
        dest.entries.append(e)
        return True

    def set_variant(self, eid, variant) -> bool:
        _g, e = self.find_entry(eid)
        if e is None:
            return False
        e.variant = variant or None
        return True

    def set_player_ship(self, ship) -> None:
        pe = self.player_entry()
        pe.ship, pe.variant = ship, None

    # ── JSON ────────────────────────────────────────────────────────────
    def to_json(self) -> dict:
        return {"groups": [{
            "id": g.id, "name": g.name, "custom_name": g.custom_name,
            "player": g.player, "allegiance": g.allegiance,
            "direction": g.direction, "distance": g.distance,
            "difficulty": g.difficulty,
            "entries": [{"id": e.id, "ship": e.ship, "variant": e.variant,
                         "player": e.player} for e in g.entries],
        } for g in self.groups]}


def default_scenario() -> Scenario:
    player = Group(id=new_id(), name="Friendly group", allegiance="friendly",
                   direction=None, distance=None, player=True,
                   entries=[Entry(id=new_id(), ship=DEFAULT_PLAYER_SHIP, player=True)])
    enemy = Group(id=new_id(), name="Enemy group", allegiance="enemy",
                  direction="fore", distance="standard")
    return Scenario(groups=[player, enemy])


def _req(cond, why):
    if not cond:
        raise ValueError(why)


def from_json(d) -> Scenario:
    """Parse and validate. Raises ValueError on any shape or invariant break."""
    _req(isinstance(d, dict) and isinstance(d.get("groups"), list), "no groups")
    groups = []
    for gd in d["groups"]:
        _req(isinstance(gd, dict), "group not a dict")
        player = bool(gd.get("player"))
        allegiance = gd.get("allegiance")
        _req(allegiance in ALLEGIANCES, "bad allegiance")
        _req(gd.get("difficulty", "medium") in DIFFICULTY_LEVEL, "bad difficulty")
        if player:
            _req(allegiance == "friendly", "player group not friendly")
            direction = distance = None
        else:
            direction, distance = gd.get("direction"), gd.get("distance")
            _req(direction in DIRECTIONS and distance in DISTANCE_IDS, "bad placement")
        name = gd.get("name")
        _req(isinstance(name, str) and name.strip(), "bad name")
        entries = []
        for ed in gd.get("entries") or []:
            _req(isinstance(ed, dict) and isinstance(ed.get("ship"), str)
                 and ed["ship"], "bad entry")
            variant = ed.get("variant")
            _req(variant is None or isinstance(variant, str), "bad variant")
            entries.append(Entry(id=str(ed.get("id") or new_id()), ship=ed["ship"],
                                 variant=variant or None, player=bool(ed.get("player"))))
        groups.append(Group(id=str(gd.get("id") or new_id()), name=name.strip(),
                            allegiance=allegiance, direction=direction,
                            distance=distance, difficulty=gd.get("difficulty", "medium"),
                            player=player, custom_name=bool(gd.get("custom_name")),
                            entries=entries))
    pgs = [g for g in groups if g.player]
    _req(len(pgs) == 1, "need exactly one player group")
    pes = [e for g in groups for e in g.entries if e.player]
    _req(len(pes) == 1 and pes[0] in pgs[0].entries, "need exactly one player entry")
    return Scenario(groups=groups)


def _strip_ids(s: Scenario) -> list:
    out = []
    for g in s.to_json()["groups"]:
        g = dict(g)
        g.pop("id")
        g["entries"] = [{k: v for k, v in e.items() if k != "id"} for e in g["entries"]]
        out.append(g)
    return out


def same_setup(a: Scenario, b: Scenario) -> bool:
    return _strip_ids(a) == _strip_ids(b)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_qb_scenario.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/__init__.py engine/quickbattle/scenario.py tests/unit/test_qb_scenario.py
git commit -m "feat(qb): scenario model — groups, player invariants, JSON round-trip"
```

---

### Task 2: Naming

**Files:**
- Create: `engine/quickbattle/naming.py`
- Test: `tests/unit/test_qb_naming.py`

**Interfaces:**
- Produces:
  - `object_name(title: str, n: int) -> str` returns `"<title>-<n>"`.
  - `with_ordinals(names: list[Optional[str]]) -> list[Optional[str]]`. The second and later occurrences of the same non-None name get `" (2)"`, `" (3)"`, … in list order. `None` passes through. The caller puts the player first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_qb_naming.py
from engine.quickbattle import naming


def test_object_name_is_bc_style():
    assert naming.object_name("Bird of Prey", 3) == "Bird of Prey-3"


def test_ordinals_only_on_repeats_in_order_none_passes_through():
    names = ["USS Dauntless", None, "USS Dauntless", "USS Venture", "USS Dauntless", None]
    assert naming.with_ordinals(names) == [
        "USS Dauntless", None, "USS Dauntless (2)", "USS Venture", "USS Dauntless (3)", None]


def test_empty_list():
    assert naming.with_ordinals([]) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_qb_naming.py -q`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/naming.py
"""Spawned ship names. The OBJECT name stays BC-style and unique ("Galaxy-1"):
SDK scripts and AI find ships by it. The DISPLAY name is the named ship, with an
ordinal on repeats. Spec §4.6 / D9."""
from __future__ import annotations

from typing import Optional


def object_name(title: str, n: int) -> str:
    return "%s-%d" % (title, n)


def with_ordinals(names: list) -> list:
    seen: dict = {}
    out: list = []
    for name in names:
        if name is None:
            out.append(None)
            continue
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else "%s (%d)" % (name, seen[name]))
    return out
```

- [ ] **Step 4: Run to verify pass.** Same command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/naming.py tests/unit/test_qb_naming.py
git commit -m "feat(qb): object and display names with ordinals"
```

---

### Task 3: Reconciliation and the battle plan

**Files:**
- Modify: `engine/quickbattle/scenario.py` (append)
- Test: `tests/unit/test_qb_battle_plan.py`

**Interfaces:**
- Consumes:
  - `engine.ship_catalog.CatalogEntry`
  - `engine.ship_catalog.Variant(name, script=None, registry=None, playable=None)`
  - `naming.with_ordinals`
  - `engine.units.GU_TO_KM`
  - `engine.appc.registry_texture.DEFAULT_REGISTRY_BY_CLASS`
- Produces, in `engine.quickbattle.scenario`:
  - `catalog_index(entries) -> dict[str, CatalogEntry]`, keyed by `ship_id.lower()`.
  - `resolve_variant(ce, name) -> Variant | None`. Returns `variants[0]` for `None`, and `None` when the class has no variants or the name is unknown.
  - `can_be_player(ce, variant_name) -> bool`
  - `reconcile(scenario, index) -> list[str]`. Mutates the scenario and returns one message per change.
  - Frozen dataclasses:
    - `PlayerOrder(ship_file, class_id, registry, display_name)`
    - `SpawnOrder(group_id, entry_id, ship_file, class_id, title, registry, display_name, allegiance, direction, distance_gu, ai_level)`
    - `BattlePlan(player: PlayerOrder, orders: tuple)`
  - `battle_plan(scenario, index) -> BattlePlan`
- Rules (spec §4.6):
  - `ship_file` is the variant's `script` if it has one, else `ce.ship_id`.
  - `registry` is a **stem** (e.g. `"Venture"`):
    - For a script variant: its own `registry` or `None`.
    - For the class default: `variants[0].registry`, else the stem of `DEFAULT_REGISTRY_BY_CLASS[ce.ship_id]`, else `None`.
    - For any other variant: its `registry`.
  - The display name before ordinals is the variant's name (the class default's when `variant is None`) if the class has variants, else `None`.
  - Ordinals run over `[player] + orders`.
  - `distance_gu = DISTANCE_KM[d] / GU_TO_KM`.
  - `ai_level = DIFFICULTY_LEVEL[group.difficulty]`.
  - Orders go in group order, then row order. The player entry is excluded.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_qb_battle_plan.py
import pytest

from engine.quickbattle import scenario as sc
from engine.ship_catalog import CatalogEntry, Variant


def _ce(ship_id, title=None, playable=True, variants=(), species="Federation",
        role="tactical"):
    return CatalogEntry(
        ship_id=ship_id, icon=ship_id, source="stock", origins=(), title=title or ship_id,
        species=species, era=("DS9", "DS9"), role=role, playable=playable,
        variants=tuple(variants), missing=(), errors=(), raw_name=title or ship_id,
        raw_race=None)


GALAXY = _ce("Galaxy", variants=[Variant("USS Dauntless", registry="Dauntless"),
                                 Variant("USS Venture", registry="Venture")])
AKIRA = _ce("Akira", variants=[Variant("USS Geronimo", registry="Geronimo"),
                               Variant("USS Enterprise-X", script="EnterpriseX")])
WARBIRD = _ce("Warbird", species="Romulan")
STARBASE = _ce("FedStarbase", title="Fed Starbase", playable=False, role="station")
INDEX = sc.catalog_index([GALAXY, AKIRA, WARBIRD, STARBASE])


def test_catalog_index_is_case_insensitive():
    assert INDEX["galaxy"] is GALAXY and INDEX["fedstarbase"] is STARBASE


def test_resolve_variant():
    assert sc.resolve_variant(GALAXY, None).name == "USS Dauntless"
    assert sc.resolve_variant(GALAXY, "USS Venture").registry == "Venture"
    assert sc.resolve_variant(GALAXY, "USS Nope") is None
    assert sc.resolve_variant(WARBIRD, None) is None


def test_can_be_player_uses_variant_flag_then_entry_flag():
    assert sc.can_be_player(GALAXY, None)
    assert not sc.can_be_player(STARBASE, None)
    member = _ce("Defiant", variants=[Variant("Defiant"), Variant("Valiant", script="Valiant",
                                                                  playable=False)])
    assert sc.can_be_player(member, "Defiant")
    assert not sc.can_be_player(member, "Valiant")


def test_reconcile_drops_unknown_ship_and_variant_keeps_rest():
    s = sc.default_scenario()
    eg = s.groups[1]
    keep = s.add_ship(eg.id, "warbird")
    gone = s.add_ship(eg.id, "ModShipRemoved")
    named = s.add_ship(eg.id, "Galaxy")
    s.set_variant(named.id, "USS Removed")
    msgs = sc.reconcile(s, INDEX)
    assert [e.id for e in eg.entries] == [keep.id, named.id]
    assert named.variant is None
    assert len(msgs) == 2 and all(isinstance(m, str) for m in msgs)
    assert sc.reconcile(s, INDEX) == []


def test_reconcile_unknown_or_unplayable_player_becomes_galaxy():
    s = sc.default_scenario()
    s.set_player_ship("ModShipRemoved")
    assert sc.reconcile(s, INDEX)
    assert (s.player_entry().ship, s.player_entry().variant) == ("Galaxy", None)
    s.set_player_ship("FedStarbase")
    sc.reconcile(s, INDEX)
    assert s.player_entry().ship == "Galaxy"


def test_battle_plan_orders_names_registries_and_levels():
    s = sc.default_scenario()
    pg, eg = s.player_group(), s.groups[1]
    s.update_details(eg.id, "enemy", "port", "long", "high")
    esc = s.add_ship(pg.id, "Galaxy")           # escort, class default -> "USS Dauntless (2)"
    w = s.add_ship(eg.id, "Warbird")
    v = s.add_ship(eg.id, "Galaxy")
    s.set_variant(v.id, "USS Venture")
    x = s.add_ship(eg.id, "Akira")
    s.set_variant(x.id, "USS Enterprise-X")
    plan = sc.battle_plan(s, INDEX)

    assert plan.player == sc.PlayerOrder(ship_file="Galaxy", class_id="Galaxy",
                                         registry="Dauntless", display_name="USS Dauntless")
    ids = [o.entry_id for o in plan.orders]
    assert ids == [esc.id, w.id, v.id, x.id]
    o_esc, o_w, o_v, o_x = plan.orders
    assert (o_esc.allegiance, o_esc.direction, o_esc.distance_gu) == ("friendly", None, None)
    assert o_esc.display_name == "USS Dauntless (2)"
    assert o_esc.ai_level == 0.5
    assert (o_w.ship_file, o_w.registry, o_w.display_name, o_w.title) == \
        ("Warbird", None, None, "Warbird")
    assert o_w.direction == "port" and o_w.ai_level == 1.0
    assert o_w.distance_gu == pytest.approx(80.0 / 0.175)
    assert (o_v.registry, o_v.display_name) == ("Venture", "USS Venture")
    assert (o_x.ship_file, o_x.class_id, o_x.registry) == ("EnterpriseX", "Akira", None)


def test_class_default_registry_falls_back_to_bc_default_table():
    plain_galaxy = _ce("Galaxy", variants=[Variant("USS Dauntless")])
    plan = sc.battle_plan(sc.default_scenario(), sc.catalog_index([plain_galaxy]))
    assert plan.player.registry == "Dauntless"
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_qb_battle_plan.py -q`. Expected: FAIL (`AttributeError: ... has no attribute 'catalog_index'`).

- [ ] **Step 3: Implement (append to `scenario.py`)**

```python
# ── Catalog-aware: reconciliation and the battle plan (spec §2, §4.6) ──────

import logging
import os

_log = logging.getLogger(__name__)


def catalog_index(entries) -> dict:
    return {e.ship_id.lower(): e for e in entries}


def _lookup(index, ship_id):
    return index.get((ship_id or "").lower())


def resolve_variant(ce, name):
    if not ce.variants:
        return None
    if name is None:
        return ce.variants[0]
    return next((v for v in ce.variants if v.name == name), None)


def can_be_player(ce, variant_name) -> bool:
    v = resolve_variant(ce, variant_name)
    if v is not None and v.playable is not None:
        return bool(v.playable)
    return bool(ce.playable)


def reconcile(scenario: "Scenario", index) -> list:
    msgs = []
    pe = scenario.player_entry()
    ce = _lookup(index, pe.ship)
    if ce is None or not can_be_player(ce, pe.variant):
        msgs.append("player ship %r unavailable; using %s" % (pe.ship, DEFAULT_PLAYER_SHIP))
        pe.ship, pe.variant = DEFAULT_PLAYER_SHIP, None
    for g in scenario.groups:
        for e in list(g.entries):
            ce = _lookup(index, e.ship)
            if ce is None:
                msgs.append("ship %r is no longer installed; removed from %r" % (e.ship, g.name))
                g.entries.remove(e)
                continue
            e.ship = ce.ship_id
            if e.variant is not None and resolve_variant(ce, e.variant) is None:
                msgs.append("named ship %r not found on %s; using class default"
                            % (e.variant, ce.ship_id))
                e.variant = None
    for m in msgs:
        _log.warning("quickbattle: %s", m)
    return msgs


@dataclass(frozen=True)
class PlayerOrder:
    ship_file: str
    class_id: str
    registry: Optional[str]
    display_name: Optional[str]


@dataclass(frozen=True)
class SpawnOrder:
    group_id: str
    entry_id: str
    ship_file: str
    class_id: str
    title: str
    registry: Optional[str]
    display_name: Optional[str]
    allegiance: str
    direction: Optional[str]
    distance_gu: Optional[float]
    ai_level: float


@dataclass(frozen=True)
class BattlePlan:
    player: PlayerOrder
    orders: tuple


def _bc_default_stem(class_id):
    from engine.appc.registry_texture import DEFAULT_REGISTRY_BY_CLASS
    rel = DEFAULT_REGISTRY_BY_CLASS.get(class_id)
    return os.path.splitext(os.path.basename(rel))[0] if rel else None


def _resolve(ce, variant_name):
    """(ship_file, registry_stem, display_name_before_ordinals) for one row."""
    v = resolve_variant(ce, variant_name)
    if v is not None and v.script:
        return v.script, v.registry, v.name
    if v is None or v is ce.variants[0]:
        reg = (v.registry if v is not None else None) or _bc_default_stem(ce.ship_id)
        return ce.ship_id, reg, (v.name if v is not None else None)
    return ce.ship_id, v.registry, v.name


def battle_plan(scenario: "Scenario", index) -> BattlePlan:
    from engine.quickbattle import naming
    from engine.units import GU_TO_KM

    pe = scenario.player_entry()
    pce = _lookup(index, pe.ship)
    p_file, p_reg, p_name = _resolve(pce, pe.variant)
    rows = []
    for g in scenario.groups:
        for e in g.entries:
            if e.player:
                continue
            ce = _lookup(index, e.ship)
            if ce is None:
                continue
            rows.append((g, e, ce) + _resolve(ce, e.variant))
    names = naming.with_ordinals([p_name] + [r[5] for r in rows])
    orders = []
    for (g, e, ce, f, reg, _n), disp in zip(rows, names[1:]):
        orders.append(SpawnOrder(
            group_id=g.id, entry_id=e.id, ship_file=f, class_id=ce.ship_id,
            title=ce.title or ce.ship_id, registry=reg, display_name=disp,
            allegiance=g.allegiance, direction=g.direction,
            distance_gu=(DISTANCE_KM[g.distance] / GU_TO_KM) if g.distance else None,
            ai_level=DIFFICULTY_LEVEL[g.difficulty]))
    return BattlePlan(player=PlayerOrder(p_file, pce.ship_id, p_reg, names[0]),
                      orders=tuple(orders))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_qb_battle_plan.py tests/unit/test_qb_scenario.py -q`. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/scenario.py tests/unit/test_qb_battle_plan.py
git commit -m "feat(qb): reconcile scenarios against the catalog; derive the battle plan"
```

---

### Task 4: Presets file

**Files:**
- Create: `engine/quickbattle/presets.py`
- Test: `tests/unit/test_qb_presets.py`

**Interfaces:**
- Consumes: `engine.settings_store.SettingsStore`, `settings_store.default_settings_path()`, and `scenario.from_json` / `to_json`.
- Produces:
  - `default_presets_path() -> Path`, which returns `<settings dir>/quickbattle_presets.json`.
  - `PresetStore(store)` with:
    - `names() -> list[str]` (sorted case-insensitively)
    - `exists(name) -> bool`
    - `load(name) -> Scenario | None` (raw, **not** reconciled; the caller reconciles)
    - `save(name, scenario) -> bool`
    - `delete(name) -> bool`
  - `load_presets(path=None) -> PresetStore`.
- File shape: `{"version": 1, "presets": {"<name>": {"saved_at": "<ISO>", "scenario": {...}}}}`. The `presets` section is written with `set_section`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_qb_presets.py
import json

from engine.quickbattle import presets, scenario as sc


def _store(tmp_path):
    return presets.load_presets(tmp_path / "quickbattle_presets.json")


def test_absent_file_has_no_presets(tmp_path):
    p = _store(tmp_path)
    assert p.names() == [] and not p.exists("x") and p.load("x") is None


def test_save_load_round_trip_and_sorted_names(tmp_path):
    p = _store(tmp_path)
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "Warbird")
    assert p.save("  zeta ", s)
    assert p.save("Alpha", sc.default_scenario())
    assert p.names() == ["Alpha", "zeta"]
    again = _store(tmp_path)                      # re-read from disk
    assert sc.same_setup(again.load("zeta"), s)
    raw = json.loads((tmp_path / "quickbattle_presets.json").read_text())
    assert raw["presets"]["zeta"]["saved_at"]


def test_empty_name_refused_overwrite_and_delete(tmp_path):
    p = _store(tmp_path)
    assert not p.save("   ", sc.default_scenario())
    p.save("A", sc.default_scenario())
    s2 = sc.default_scenario()
    s2.add_ship(s2.groups[1].id, "Akira")
    p.save("A", s2)
    assert sc.same_setup(p.load("A"), s2)
    assert p.delete("A") and not p.exists("A") and not p.delete("A")


def test_corrupt_file_quarantined_and_broken_preset_skipped(tmp_path):
    f = tmp_path / "quickbattle_presets.json"
    f.write_text("{not json")
    p = presets.load_presets(f)
    assert p.names() == []
    f.write_text(json.dumps({"version": 1, "presets": {
        "bad": {"saved_at": "x", "scenario": {"groups": []}}}}))
    p = presets.load_presets(f)
    assert p.load("bad") is None


def test_default_path_is_beside_settings_and_resolved_at_use(monkeypatch, tmp_path):
    from engine import settings_store
    monkeypatch.setattr(settings_store, "default_settings_path",
                        lambda: tmp_path / "settings.json")
    assert presets.default_presets_path() == tmp_path / "quickbattle_presets.json"
```

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/unit/test_qb_presets.py -q`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/presets.py
"""Quick Battle presets: quickbattle_presets.json beside settings.json.

Only presets live on disk -- the current setup is per-run (spec D8). The
bridge_selection pattern: a SettingsStore underneath (atomic writes, corrupt
file quarantined), a small wrapper above. Spec §6.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from engine.quickbattle import scenario as sc

_log = logging.getLogger(__name__)
_SECTION = "presets"


def default_presets_path() -> Path:
    from engine import settings_store
    return settings_store.default_settings_path().parent / "quickbattle_presets.json"


class PresetStore:
    def __init__(self, store):
        self.store = store

    def _all(self) -> dict:
        d = self.store._section(_SECTION) if self.store.has_section(_SECTION) else {}
        return dict(d)

    def names(self) -> list:
        return sorted(self._all(), key=lambda n: (n.lower(), n))

    def exists(self, name) -> bool:
        return (name or "").strip() in self._all()

    def load(self, name):
        rec = self._all().get((name or "").strip())
        if not isinstance(rec, dict):
            return None
        try:
            return sc.from_json(rec.get("scenario"))
        except ValueError as e:
            _log.warning("quickbattle preset %r unreadable: %s", name, e)
            return None

    def save(self, name, scenario) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        allp = self._all()
        allp[name] = {"saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                      "scenario": scenario.to_json()}
        self.store.set_section(_SECTION, allp)
        return True

    def delete(self, name) -> bool:
        allp = self._all()
        name = (name or "").strip()
        if name not in allp:
            return False
        del allp[name]
        self.store.set_section(_SECTION, allp)
        return True


def load_presets(path=None) -> PresetStore:
    from engine.settings_store import SettingsStore
    store = SettingsStore(path if path is not None else default_presets_path())
    store.load()
    return PresetStore(store)
```

Before relying on `_section`, read `engine/settings_store.py:126-160`. If `_section` returns a live dict, keep the `dict(...)` copy. If `SettingsStore` migrates unknown sections (`_migrate`), check that a `presets` section survives a reload. The round-trip test proves both.

- [ ] **Step 4: Run to verify pass.** Same command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/presets.py tests/unit/test_qb_presets.py
git commit -m "feat(qb): presets file beside settings.json"
```

---

### Task 5: Placement maths

**Files:**
- Create: `engine/quickbattle/placement.py`
- Test: `tests/unit/test_qb_placement.py`

**Interfaces:**
- Produces (pure, plain `(x, y, z)` tuples, no App):
  - `MARGIN_GU = 2.0`, `ROW_SIZE = 5`
  - `axis_for(direction, cols) -> Vec`, where `cols = (starboard, fore, dorsal)`, i.e. the player's `GetCol(0..2)` as tuples
  - `lateral_for(direction, cols) -> Vec`: starboard for fore/aft/dorsal/ventral, fore for port/starboard
  - `slot_offsets(radii) -> list[float]`: lateral offsets for ONE row, slot order 0, +1, −1, +2, −2, …, packed by radii plus the margin
  - `group_positions(player_pos, cols, direction, distance_gu, radii) -> list[Vec]`, in input order
  - `escort_positions(player_pos, cols, player_radius, radii) -> list[Vec]`: slot 1 starboard, slot 2 port, alternating outwards
  - `faces_player(allegiance) -> bool`: True only for `"enemy"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_qb_placement.py
import pytest

from engine.quickbattle import placement as pl

COLS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))   # identity: stbd, fore, dorsal
ORIGIN = (10.0, 20.0, 30.0)


@pytest.mark.parametrize("direction,axis", [
    ("fore", (0, 1, 0)), ("aft", (0, -1, 0)), ("starboard", (1, 0, 0)),
    ("port", (-1, 0, 0)), ("dorsal", (0, 0, 1)), ("ventral", (0, 0, -1))])
def test_axis_for_each_direction(direction, axis):
    assert pl.axis_for(direction, COLS) == pytest.approx(axis)


def test_axis_follows_a_rotated_player():
    rot = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))   # yawed 90 degrees
    assert pl.axis_for("fore", rot) == pytest.approx((-1, 0, 0))
    assert pl.lateral_for("fore", rot) == pytest.approx((0, 1, 0))


def test_lateral_axis_choice():
    assert pl.lateral_for("fore", COLS) == pytest.approx((1, 0, 0))
    assert pl.lateral_for("dorsal", COLS) == pytest.approx((1, 0, 0))
    assert pl.lateral_for("port", COLS) == pytest.approx((0, 1, 0))


def test_slot_offsets_alternate_and_pack_by_radii():
    m = pl.MARGIN_GU
    assert pl.slot_offsets([1.0]) == [0.0]
    off = pl.slot_offsets([1.0, 1.0, 1.0])
    assert off == pytest.approx([0.0, 2.0 + m, -(2.0 + m)])
    big = pl.slot_offsets([1.0, 5.0])        # a station next to a shuttle
    assert big[1] == pytest.approx(1.0 + 5.0 + m)


def test_single_ship_sits_on_the_anchor():
    [p] = pl.group_positions(ORIGIN, COLS, "fore", 200.0, [1.0])
    assert p == pytest.approx((10.0, 220.0, 30.0))


def test_rows_of_five_then_further_away():
    pos = pl.group_positions(ORIGIN, COLS, "fore", 200.0, [1.0] * 7)
    assert all(p[1] == pytest.approx(220.0) for p in pos[:5])
    gap = 1.0 + 1.0 + pl.MARGIN_GU
    assert all(p[1] == pytest.approx(220.0 + gap) for p in pos[5:])
    assert pos[5][0] == pytest.approx(10.0)          # second row restarts at the centre


def test_deterministic():
    a = pl.group_positions(ORIGIN, COLS, "aft", 457.0, [1.0, 2.0, 3.0])
    b = pl.group_positions(ORIGIN, COLS, "aft", 457.0, [1.0, 2.0, 3.0])
    assert a == b


def test_escorts_beside_player_starboard_first():
    m = pl.MARGIN_GU
    pos = pl.escort_positions(ORIGIN, COLS, 2.0, [1.0, 1.0, 1.0])
    assert pos[0] == pytest.approx((10.0 + 2.0 + 1.0 + m, 20.0, 30.0))
    assert pos[1] == pytest.approx((10.0 - (2.0 + 1.0 + m), 20.0, 30.0))
    assert pos[2][0] > pos[0][0]


def test_only_enemies_face_the_player():
    assert pl.faces_player("enemy")
    assert not pl.faces_player("friendly") and not pl.faces_player("neutral")
```

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/unit/test_qb_placement.py -q`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/placement.py
"""Deterministic group placement around the player. Pure: plain tuples in GU.

Spec §4.4: axes from the player's columns (stbd = GetCol(0), fore = GetCol(1),
dorsal = GetCol(2); right-handed); anchor = player + axis * distance (centre to
centre); line abreast across the lateral axis, slots 0, +1, -1, +2, -2 packed
by radii plus MARGIN_GU; rows of ROW_SIZE, each further row one row-gap further
along the axis. No randomness.
"""
from __future__ import annotations

MARGIN_GU = 2.0
ROW_SIZE = 5

_AXIS = {"starboard": (0, 1.0), "port": (0, -1.0), "fore": (1, 1.0),
         "aft": (1, -1.0), "dorsal": (2, 1.0), "ventral": (2, -1.0)}


def _scale(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def _add(*vs):
    return (sum(v[0] for v in vs), sum(v[1] for v in vs), sum(v[2] for v in vs))


def axis_for(direction, cols):
    i, sign = _AXIS[direction]
    return _scale(cols[i], sign)


def lateral_for(direction, cols):
    return cols[1] if direction in ("port", "starboard") else cols[0]


def faces_player(allegiance) -> bool:
    return allegiance == "enemy"


def slot_offsets(radii) -> list:
    """Lateral offset per ship of one row, in input order. Slot k>0 alternates
    +, -; each side packs outward: prev offset + prev radius + this radius + margin."""
    out = [0.0] * len(radii)
    if not radii:
        return out
    edge = {1: (0.0, radii[0]), -1: (0.0, radii[0])}   # side -> (last offset, last radius)
    for i in range(1, len(radii)):
        side = 1 if i % 2 == 1 else -1
        last_off, last_r = edge[side]
        off = abs(last_off) + last_r + radii[i] + MARGIN_GU
        out[i] = side * off
        edge[side] = (out[i], radii[i])
    return out


def group_positions(player_pos, cols, direction, distance_gu, radii) -> list:
    axis = axis_for(direction, cols)
    lat = lateral_for(direction, cols)
    out = []
    depth = float(distance_gu)
    prev_row_max = None
    for start in range(0, len(radii), ROW_SIZE):
        row = radii[start:start + ROW_SIZE]
        if prev_row_max is not None:
            depth += prev_row_max + max(row) + MARGIN_GU
        for off in slot_offsets(row):
            out.append(_add(player_pos, _scale(axis, depth), _scale(lat, off)))
        prev_row_max = max(row)
    return out


def escort_positions(player_pos, cols, player_radius, radii) -> list:
    """Escorts line abreast with the player as slot 0."""
    offs = slot_offsets([player_radius] + list(radii))[1:]
    return [_add(player_pos, _scale(cols[0], off)) for off in offs]
```

- [ ] **Step 4: Run to verify pass.** Same command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/placement.py tests/unit/test_qb_placement.py
git commit -m "feat(qb): deterministic group and escort placement"
```

---

### Task 6: Stats probe and ship bios

**Files:**
- Create: `engine/quickbattle/stats.py`
- Create: `engine/quickbattle/bios.py`
- Test: `tests/host/test_qb_stats.py`, `tests/unit/test_qb_bios.py`

**Interfaces:**
- Consumes:
  - `App.g_kModelPropertyManager`, whose `_local` dict is the local templates (`engine/appc/properties.py:1012-1050`);
  - `engine.appc.properties.TGModelPropertySet`, `HullProperty`, `ShieldProperty`;
  - SDK `ships.<id>.GetShipStats()["HardpointFile"]`;
  - `engine.missions.tgl_reader.read_tgl`;
  - `engine.paths.game_asset`.
- Produces:
  - `stats.ShipStats(hull: float, shields: float)` (frozen).
  - `stats.probe(ship_file) -> ShipStats | None`. It never raises, and **always** restores the templates.
  - `stats.StatsCache()` with:
    - `get(ship_file) -> ShipStats | None` (memoised, failures included);
    - `maxima(entries) -> (hull_max, shield_max)` over `playable` entries' class `ship_id`, with 0.0 when none;
    - `reset()`.
  - `bios.ship_bio(ce) -> str | None`. It reads `Ships.tgl` key `"<raw_name> Description"`, then `"<title> Description"`, then `"<ship_id> Description"`, drops lines starting with `"Shield Rating"` / `"Hull Rating"`, and caches the parsed TGL. `bios.reset()` clears the cache.

- [ ] **Step 1: Write the failing tests**

```python
# tests/host/test_qb_stats.py
"""Stats probe against real SDK hardpoints. Values: roadmap 'Scale-bar reference
values' (Warbird hull 24,000; Sovereign shield total 49,500)."""
import pytest

pytest.importorskip("_dauntless_host")


@pytest.fixture
def sdk():
    from tools import mission_harness
    mission_harness.setup_sdk()
    import App
    return App


def test_stock_values(sdk):
    from engine.quickbattle import stats
    assert stats.probe("Warbird").hull == pytest.approx(24000.0)
    assert stats.probe("Sovereign").shields == pytest.approx(49500.0)


def test_probe_restores_local_templates(sdk):
    from engine.quickbattle import stats
    mgr = sdk.g_kModelPropertyManager
    sentinel = sdk.HullProperty_Create("SentinelHull")
    mgr.RegisterLocalTemplate(sentinel)
    before = dict(mgr._local)
    stats.probe("Galaxy")
    assert mgr._local == before


def test_probe_restores_templates_on_failure(sdk, monkeypatch):
    from engine.quickbattle import stats
    mgr = sdk.g_kModelPropertyManager
    mgr.RegisterLocalTemplate(sdk.HullProperty_Create("SentinelHull"))
    before = dict(mgr._local)
    assert stats.probe("NoSuchShipScript") is None
    assert mgr._local == before


def test_cache_and_playable_maxima(sdk):
    from engine.quickbattle import stats
    from engine import ship_catalog
    cache = stats.StatsCache()
    assert cache.get("Warbird") is cache.get("Warbird")
    hull_max, shield_max = cache.maxima(ship_catalog.entries())
    assert hull_max == pytest.approx(24000.0)       # Warbird: largest playable hull
    assert shield_max == pytest.approx(49500.0)     # Sovereign: largest playable shields
```

```python
# tests/unit/test_qb_bios.py
from engine.quickbattle import bios
from engine.ship_catalog import CatalogEntry


def _ce(ship_id, raw_name, title):
    return CatalogEntry(ship_id=ship_id, icon=ship_id, source="stock", origins=(),
                        title=title, species="Federation", era=("DS9", "DS9"),
                        role="tactical", playable=True, variants=(), missing=(),
                        errors=(), raw_name=raw_name, raw_race=None)


def test_bio_strips_rating_lines_and_falls_back(monkeypatch):
    table = {"Galaxy Description": "A big ship.\nShield Rating: 9\nHull Rating: 5\nWeapons: lots",
             "Hybrid Description": "Odd."}
    monkeypatch.setattr(bios, "_strings", lambda: table)
    assert bios.ship_bio(_ce("Galaxy", "Galaxy", "Galaxy")) == "A big ship.\nWeapons: lots"
    assert bios.ship_bio(_ce("CardHybrid", "Card Hybrid", "Hybrid")) == "Odd."
    assert bios.ship_bio(_ce("Mod", "Mod", "Mod")) is None
```

- [ ] **Step 2: Run to verify fail.**

Run: `uv run pytest tests/host/test_qb_stats.py tests/unit/test_qb_bios.py -q`. Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/stats.py
"""Hull and shield totals for the scale bars, read from LOADED properties.

Runs BC's own loader sequence (loadspacehelper.py:88-91) into a scratch set:
ClearLocalTemplates -> reload the hardpoint module (our override pass fires in
the SDK loader here) -> LoadPropertySet. So the values are mod- and
override-aware, never parsed from hardpoint text. The primary hull is the FIRST
HullProperty (engine/appc/ships.py:1238). The manager's local templates are
snapshotted and restored in a finally: a live mission must never notice. Spec §5.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShipStats:
    hull: float
    shields: float


def probe(ship_file) -> Optional[ShipStats]:
    import App
    from engine.appc.properties import HullProperty, ShieldProperty, TGModelPropertySet
    mgr = App.g_kModelPropertyManager
    snapshot = dict(mgr._local)
    try:
        ship_mod = importlib.import_module("ships." + ship_file)
        hp_file = ship_mod.GetShipStats()["HardpointFile"]
        mgr.ClearLocalTemplates()
        hp_mod = importlib.reload(importlib.import_module("ships.Hardpoints." + hp_file))
        pset = TGModelPropertySet()
        hp_mod.LoadPropertySet(pset)
        props = [p for _n, p in pset._entries]
        hull = next((p for p in props if isinstance(p, HullProperty)), None)
        shield = next((p for p in props if isinstance(p, ShieldProperty)), None)
        if hull is None:
            return None
        total = sum(float(shield.GetMaxShields(f) or 0.0) for f in range(6)) if shield else 0.0
        return ShipStats(hull=float(hull.GetMaxCondition() or 0.0), shields=total)
    except Exception as e:                       # one bad ship costs only itself
        _log.info("quickbattle stats probe failed for %s: %s", ship_file, e)
        return None
    finally:
        mgr._local.clear()
        mgr._local.update(snapshot)


class StatsCache:
    def __init__(self):
        self._memo: dict = {}

    def reset(self) -> None:
        self._memo.clear()

    def get(self, ship_file):
        if ship_file not in self._memo:
            self._memo[ship_file] = probe(ship_file)
        return self._memo[ship_file]

    def maxima(self, entries):
        hull = shields = 0.0
        for ce in entries:
            if not ce.playable:
                continue
            st = self.get(ce.ship_id)
            if st is not None:
                hull, shields = max(hull, st.hull), max(shields, st.shields)
        return hull, shields
```

```python
# engine/quickbattle/bios.py
"""Ship sheet bio text from Ships.tgl ('<name> Description'), with BC's
'Shield Rating' / 'Hull Rating' lines dropped: they don't match the game's
values (roadmap). Resolved at use; parsed TGL cached until reset()."""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)
_cache: dict = {}


def reset() -> None:
    _cache.clear()


def _strings() -> dict:
    if "strings" not in _cache:
        table = {}
        try:
            from engine import paths
            from engine.missions.tgl_reader import read_tgl
            tgl = read_tgl(paths.game_asset("data/TGL/Ships.tgl"))
            table = dict(tgl.strings)
        except Exception as e:
            _log.info("Ships.tgl unreadable: %s", e)
        _cache["strings"] = table
    return _cache["strings"]


def ship_bio(ce) -> Optional[str]:
    table = _strings()
    for key in (ce.raw_name, ce.title, ce.ship_id):
        text = table.get("%s Description" % key) if key else None
        if text:
            lines = [ln for ln in text.replace("\r", "\n").split("\n")
                     if not ln.strip().startswith(("Shield Rating", "Hull Rating"))]
            return "\n".join(lines).strip() or None
    return None
```

Before writing `bios._strings`, check `engine/missions/tgl_reader.py:59-79` for the real attribute name holding the strings on `TGLFile`, and use it. Check `TGModelPropertySet`'s storage too (`properties.py:1103`, `_entries` holds `(node, prop)` pairs). If `HullProperty_Create` isn't on the App shim, use `engine.appc.properties.HullProperty("SentinelHull")` in the test.

- [ ] **Step 4: Run to verify pass.** Same command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/stats.py engine/quickbattle/bios.py tests/host/test_qb_stats.py tests/unit/test_qb_bios.py
git commit -m "feat(qb): hull/shield probe from loaded properties; ship bios"
```

---

### Task 7: Spawning (provider, SDK sync, `GenerateShips` hook)

**Files:**
- Create: `engine/quickbattle/spawn.py`
- Test: `tests/host/test_qb_spawn.py`

**Interfaces:**
- Consumes:
  - `scenario.BattlePlan`, `PlayerOrder`, `SpawnOrder` (Task 3);
  - `placement.*` (Task 5);
  - the SDK QuickBattle globals `g_pSet`, `pFriendlies`, `pEnemies`, `g_kShips`, `g_iNumEnemies`, `g_iNumFriends`, `g_kFriendList`, `g_kEnemyList`, `g_sPlayerType`, `bInSimulation`, `g_pXOMenu`, `g_pMissionDatabase`, `g_dFriendlyShipTypeToDetails`, `g_dEnemyShipTypeToDetails`;
  - `loadspacehelper.CreateShip`;
  - `engine.appc.registry_texture.DEFAULT_REGISTRY_BY_CLASS` and `REGISTRY_OLD_NAME`.
- Produces, in `engine.quickbattle.spawn`:
  - `set_provider(fn | None)` and `current_plan() -> BattlePlan | None` (it calls the provider and swallows exceptions to `None`).
  - `registry_path(class_id, stem) -> str`. The BC default path when the stem matches the class default; otherwise `"Data/Models/Ships/<class_id>/<stem>.tga"`.
  - `sync_sdk(qb, plan) -> None`. It sets `g_sPlayerType` and writes the 6-tuple manifests. Unless `bInSimulation`, it also enables or disables the XO "Start Simulation" button. A `plan` of `None` is a no-op.
  - `install_generate_ships_hook(qb) -> bool`. Idempotent: the wrapper carries `_dauntless_qb_spawn_orig`. It returns True when it installed.
  - `generate_ships(qb, plan) -> None`, the body.

- [ ] **Step 1: Write the failing tests**

```python
# tests/host/test_qb_spawn.py
"""The GenerateShips hook against the real SDK QuickBattle, headless.
Pattern: tests/host/test_quickbattle_boot.py."""
import math

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def qb(monkeypatch):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import spawn
    spawn.install_generate_ships_hook(QB)      # Task 8 moves this into boot; idempotent
    yield hl, controller, QB
    spawn.set_provider(None)


def _plan(groups):
    """groups: list of (allegiance, direction, distance, difficulty, [ship ids])."""
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.delete_group(s.groups[1].id)
    for alleg, d, dist, diff, ships in groups:
        g = s.add_group()
        s.update_details(g.id, alleg, d, dist, diff)
        for ship in ships:
            s.add_ship(g.id, ship)
    return s, sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))


def _start(hl, controller):
    import App
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()


def _ship(name):
    import App
    import QuickBattle.QuickBattle as QB
    return App.ShipClass_GetObject(QB.g_pSet, name)


def test_groups_spawn_with_membership_ai_and_levels(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "high", ["Warbird", "Galor"]),
                      ("neutral", "port", "close", "medium", ["Transport"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    assert QB.bInSimulation == 1
    assert QB.g_iNumEnemies == 2
    sides = sorted(v[2] for v in QB.g_kShips.values())
    assert sides == ["Enemy", "Enemy"]                       # neutral: no g_kShips entry
    assert all(v[3] == 1.0 for v in QB.g_kShips.values())   # high
    import App
    mission = App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()
    assert mission.GetNeutralGroup().IsNameInGroup("Transport-3")
    assert QB.pEnemies.IsNameInGroup("Warbird-1")


def test_positions_follow_direction_and_distance(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "aft", "long", "medium", ["Warbird"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pp, fwd = player.GetWorldLocation(), player.GetWorldRotation().GetCol(1)
    wp = _ship("Warbird-1").GetWorldLocation()
    d = (wp.x - pp.x, wp.y - pp.y, wp.z - pp.z)
    dist = math.sqrt(sum(c * c for c in d))
    assert dist == pytest.approx(80.0 / 0.175, rel=0.05)
    assert (d[0] * fwd.x + d[1] * fwd.y + d[2] * fwd.z) / dist < -0.95   # behind


def test_enemies_face_player_friendlies_keep_heading(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("friendly", "starboard", "close", "medium", ["Akira"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    pf = player.GetWorldRotation().GetCol(1)
    ef = _ship("Warbird-1").GetWorldRotation().GetCol(1)
    ff = _ship("Akira-2").GetWorldRotation().GetCol(1)
    assert ef.x * pf.x + ef.y * pf.y + ef.z * pf.z < -0.99
    assert ff.x * pf.x + ff.y * pf.y + ff.z * pf.z > 0.99


def test_named_ship_registry_queued_and_display_name(qb):
    hl, controller, QB = qb
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    s, _ = _plan([("enemy", "fore", "standard", "medium", ["Galaxy"])])
    e = s.groups[1].entries[0]
    s.set_variant(e.id, "USS Venture")
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    plan = sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    ship = _ship("Galaxy-1")
    assert ship.GetDisplayName().GetCString() == "USS Venture"
    reps = registry_texture.replacements_for(ship)
    assert any(p.endswith("Venture.tga") for p in reps.values())


def test_generate_ships_reads_provider_at_call_time(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    _s, first = _plan([("enemy", "fore", "standard", "medium", ["Warbird"])])
    _s, second = _plan([("enemy", "fore", "standard", "medium", ["Galor", "Keldon"])])
    box = {"plan": first}
    spawn.set_provider(lambda: box["plan"])
    _start(hl, controller)
    QB.EndSimulation()
    hl._process_object_deletions()
    box["plan"] = second                    # e.g. XO Restart without opening the screen
    _start(hl, controller)
    assert QB.g_iNumEnemies == 2


def test_one_failing_ship_does_not_stop_the_rest(qb, monkeypatch):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    import loadspacehelper
    real = loadspacehelper.CreateShip

    def flaky(ship_file, *a, **k):
        if ship_file == "Galor":
            raise RuntimeError("broken mod ship")
        return real(ship_file, *a, **k)

    monkeypatch.setattr(loadspacehelper, "CreateShip", flaky)
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Galor", "Warbird"])])
    spawn.set_provider(lambda: plan)
    _start(hl, controller)
    assert QB.g_iNumEnemies == 1 and _ship("Warbird-2") is not None


def test_no_provider_falls_back_to_bc(qb):
    hl, controller, QB = qb
    from engine.quickbattle import spawn
    spawn.set_provider(None)
    QB.g_kEnemyList = [("Galaxy", "Galaxy", "msg", "QuickBattleAI", "Enemy", 0.5)]
    _start(hl, controller)
    assert len(QB.g_kShips) == 1


def test_install_is_idempotent(qb):
    _hl, _c, QB = qb
    from engine.quickbattle import spawn
    first = QB.GenerateShips
    assert not spawn.install_generate_ships_hook(QB)       # already installed by boot
    assert QB.GenerateShips is first


def test_sync_sdk_sets_player_manifests_and_xo_start(qb):
    _hl, _c, QB = qb
    from engine.quickbattle import spawn
    _s, plan = _plan([("enemy", "fore", "standard", "medium", ["Warbird"]),
                      ("neutral", "port", "close", "medium", ["Transport"])])
    spawn.sync_sdk(QB, plan)
    assert QB.g_sPlayerType == "Galaxy"
    assert [t[0] for t in QB.g_kEnemyList + QB.g_kFriendList] == ["Warbird", "Transport"]
    btn = QB.g_pXOMenu.GetButtonW(QB.g_pMissionDatabase.GetString("Start Simulation"))
    assert btn.IsEnabled()
```

The `qb` fixture installs the hook itself. Task 8 moves the install into boot, and `test_install_is_idempotent` keeps passing because install is idempotent. Check the real names before relying on them: `registry_texture.replacements_for`, and the button methods `IsEnabled` / `SetEnabled` / `SetDisabled` on the App shim (`grep -n "def IsEnabled\|def SetDisabled" engine/appc/*.py`). Adapt the test to the real surface, not the other way round.

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/host/test_qb_spawn.py -q`. Expected: FAIL (`engine.quickbattle.spawn` missing).

- [ ] **Step 3: Implement**

```python
# engine/quickbattle/spawn.py
"""Spawn a Quick Battle from the BattlePlan: only GenerateShips is replaced.

BC's chain is untouched: StartSimulation -> preload -> StartSimulation2 ->
RecreatePlayer -> GenerateShips (OURS) -> AI from g_kShips -> red alert;
ShipDestroyed's win/lose and EndSimulation's cleanup read the same g_kShips /
g_iNumEnemies BC's own GenerateShips writes. Neutrals get no g_kShips entry, so
they run no AI and never count (spec D6). With no provider -- or a provider that
returns None -- BC's original runs, which keeps headless tests that fill
g_kEnemyList working. Spec §4.
"""
from __future__ import annotations

import logging
import os

from engine.quickbattle import placement

_log = logging.getLogger(__name__)
_provider = None
_SIDE = {"friendly": "Friendly", "enemy": "Enemy"}
_FALLBACK = {"Friendly": ("QuickBattleFriendlyAI", "QBFriendlyGenericShipDestroyed"),
             "Enemy": ("QuickBattleAI", "QBEnemyGenericShipDestroyed")}
_MAX_NUDGES = 8


def set_provider(fn) -> None:
    global _provider
    _provider = fn


def current_plan():
    if _provider is None:
        return None
    try:
        return _provider()
    except Exception as e:
        _log.warning("quickbattle plan provider failed: %s", e)
        return None


def registry_path(class_id, stem) -> str:
    from engine.appc.registry_texture import DEFAULT_REGISTRY_BY_CLASS
    rel = DEFAULT_REGISTRY_BY_CLASS.get(class_id)
    if rel and os.path.splitext(os.path.basename(rel))[0] == stem:
        return rel
    return "Data/Models/Ships/%s/%s.tga" % (class_id, stem)


def _details(qb, class_id, side):
    table = qb.g_dFriendlyShipTypeToDetails if side == "Friendly" else \
        qb.g_dEnemyShipTypeToDetails
    for row in table.values():
        if str(row[0]).lower() == class_id.lower():
            return row[3], row[2]
    return _FALLBACK[side]


def _manifest(qb, order):
    side = _SIDE.get(order.allegiance, "Friendly")
    ai, msg = _details(qb, order.class_id, side)
    return (order.ship_file, order.title, msg, ai, side, order.ai_level)


def _set_xo_start(qb, enabled) -> None:
    try:
        menu = qb.g_pXOMenu
        for key in ("Start Simulation", "Restart Simulation"):
            btn = menu.GetButtonW(qb.g_pMissionDatabase.GetString(key))
            if btn is not None:
                btn.SetEnabled() if enabled else btn.SetDisabled()
                return
    except Exception as e:
        _log.info("quickbattle XO start sync skipped: %s", e)


def sync_sdk(qb, plan) -> None:
    if plan is None:
        return
    qb.g_sPlayerType = plan.player.ship_file
    enemies = [_manifest(qb, o) for o in plan.orders if o.allegiance == "enemy"]
    others = [_manifest(qb, o) for o in plan.orders if o.allegiance != "enemy"]
    qb.g_kEnemyList, qb.g_kFriendList = enemies, others
    if not getattr(qb, "bInSimulation", 0):
        _set_xo_start(qb, bool(plan.orders))


def _vec(p):
    return (p.x, p.y, p.z)


def _cols(rot):
    return tuple(_vec(rot.GetCol(i)) for i in range(3))


def _place(qb, ship, pos, lateral):
    import App
    pt = App.TGPoint3()
    r = ship.GetRadius()
    for k in range(_MAX_NUDGES + 1):
        off = r * k
        pt.SetXYZ(pos[0] + lateral[0] * off, pos[1] + lateral[1] * off,
                  pos[2] + lateral[2] * off)
        if qb.g_pSet.IsLocationEmptyTG(pt, 2.0 * r, 1):
            break
    ship.SetTranslate(pt)


def _face(ship, player, allegiance):
    import App
    if placement.faces_player(allegiance):
        ship.AlignToVectors(player.GetWorldBackwardTG(), player.GetWorldUpTG())
    else:
        ship.SetMatrixRotation(player.GetWorldRotation())


def generate_ships(qb, plan) -> None:
    import App
    import loadspacehelper
    from engine.appc.registry_texture import REGISTRY_OLD_NAME
    from engine.quickbattle import naming

    qb.g_iNumFriends = qb.g_iNumEnemies = 0
    qb.g_kShips = {}
    mission = App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()
    neutrals = mission.GetNeutralGroup()
    for grp in (qb.pEnemies, qb.pFriendlies, neutrals):
        grp.RemoveAllNames()
    player = App.Game_GetCurrentGame().GetPlayer()
    qb.pFriendlies.AddName(player.GetName())

    created = []                               # (order, ship)
    for n, order in enumerate(plan.orders, start=1):
        name = naming.object_name(order.title, n)
        try:
            ship = loadspacehelper.CreateShip(order.ship_file, qb.g_pSet, name, "")
            if ship is None or App.IsNull(ship):
                raise RuntimeError("CreateShip returned null")
            if order.display_name:
                ship.SetDisplayName(App.TGString(order.display_name))
            else:
                ship.SetDisplayName(App.TGString(name))
            if order.registry:
                ship.ReplaceTexture(registry_path(order.class_id, order.registry),
                                    REGISTRY_OLD_NAME)
            created.append((order, ship))
        except Exception as e:
            _log.error("quickbattle: could not spawn %s (%s): %s", name, order.ship_file, e)

    ppos = _vec(player.GetWorldLocation())
    cols = _cols(player.GetWorldRotation())
    by_group: dict = {}
    for order, ship in created:
        by_group.setdefault(order.group_id, []).append((order, ship))
    for members in by_group.values():
        o0 = members[0][0]
        radii = [s.GetRadius() for _o, s in members]
        try:
            if o0.direction is None:
                positions = placement.escort_positions(ppos, cols, player.GetRadius(), radii)
                lateral = cols[0]
            else:
                positions = placement.group_positions(ppos, cols, o0.direction,
                                                      o0.distance_gu, radii)
                lateral = placement.lateral_for(o0.direction, cols)
        except Exception as e:
            _log.error("quickbattle: placement failed: %s", e)
            continue
        for (order, ship), pos in zip(members, positions):
            try:
                _place(qb, ship, pos, lateral)
                _face(ship, player, order.allegiance)
                ship.UpdateNodeOnly()
                pm = qb.g_pSet.GetProximityManager()
                if pm:
                    pm.UpdateObject(ship)
                side = _SIDE.get(order.allegiance)
                if side is None:
                    neutrals.AddName(ship.GetName())
                    continue
                (qb.pEnemies if side == "Enemy" else qb.pFriendlies).AddName(ship.GetName())
                ai, msg = _details(qb, order.class_id, side)
                qb.g_kShips[ship.GetObjID()] = (ai, msg, side, order.ai_level)
                if side == "Enemy":
                    qb.g_iNumEnemies = qb.g_iNumEnemies + 1
                else:
                    qb.g_iNumFriends = qb.g_iNumFriends + 1
            except Exception as e:
                _log.error("quickbattle: could not place %s: %s", ship.GetName(), e)


def install_generate_ships_hook(qb) -> bool:
    current = getattr(qb, "GenerateShips", None)
    if current is None or getattr(current, "_dauntless_qb_spawn_orig", None) is not None:
        return False
    orig = current

    def GenerateShips():
        plan = current_plan()
        if plan is None:
            return orig()
        try:
            return generate_ships(qb, plan)
        except Exception as e:
            _log.error("quickbattle: GenerateShips hook failed, falling back to BC: %s", e)
            return orig()

    GenerateShips._dauntless_qb_spawn_orig = orig
    qb.GenerateShips = GenerateShips
    return True
```

Before implementing, check these against the shim and the SDK (`grep` in `engine/appc/` and `QuickBattle.py:2738-2836`):
- The real names `SetMatrixRotation`, `TGPoint3.SetXYZ`, `App.TGString(<str>)` and `GetWorldBackwardTG`. BC itself uses `SetTranslate(kPoint)`, `kPoint.Set(...)` and `AlignToVectors`. Use whatever setter exists to copy the player's rotation; `SetMatrixRotation` is the BC name.
- That `StartSimulation2` calls `GenerateShips()` as a **module global**. It must, for the wrap to work.
- BC's `GenerateShips` returns early when a ship fails. Ours deliberately doesn't (spec §4.5).

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/host/test_qb_spawn.py tests/host/test_quickbattle_boot.py -q`. Expected: pass. The boot tests still pass because there's no provider there, so BC's original runs.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/spawn.py tests/host/test_qb_spawn.py
git commit -m "feat(qb): GenerateShips hook — group placement, neutrals, named ships"
```

---

### Task 8: Host wiring (boot hook, player identity, start, remove revert)

**Files:**
- Modify: `engine/quickbattle/spawn.py` (add `apply_player_identity`)
- Modify: `engine/host_loop.py`:
  - `load_quickbattle`: after `install_quickbattle_hook`, also `spawn.install_generate_ships_hook(_QB)`
  - `start_quickbattle`: call `spawn.sync_sdk(QB, spawn.current_plan())` before posting the event
  - the `session.mission_name == "QuickBattle"` block in `_reconcile_runtime_ships`, around line 6290: replace `registry_texture.apply_class_default(_p)` with `spawn.apply_player_identity(_p)`
  - delete `_sync_quickbattle_player_revert` (around line 6712) and its call in the tick loop (around line 10786)
- Modify: `tests/host/test_quickbattle_boot.py`: delete the three revert tests (`test_player_ship_reverts_to_original_on_end_combat`, `test_no_revert_when_player_ship_unchanged`, `test_player_ship_reverts_through_real_end_combat`) and add the tests below
- Test: `tests/host/test_qb_player_identity.py`

**Interfaces:**
- Consumes: `spawn.current_plan()` and `registry_texture.apply_class_default`.
- Produces: `spawn.apply_player_identity(ship) -> bool`. It queues the player order's registry via `registry_path` and sets the display name. With no plan it falls back to `apply_class_default(ship)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/host/test_qb_player_identity.py
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def qb(monkeypatch):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import spawn
    yield hl, controller, QB
    spawn.set_provider(None)


def _scenario_with_player(ship, variant):
    from engine import ship_catalog
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.set_player_ship(ship)
    s.set_variant(s.player_entry().id, variant)
    s.add_ship(s.groups[1].id, "Warbird")
    return sc.battle_plan(s, sc.catalog_index(ship_catalog.entries()))


def test_boot_installs_generate_ships_hook(qb):
    _hl, _c, QB = qb
    assert getattr(QB.GenerateShips, "_dauntless_qb_spawn_orig", None) is not None


def test_player_keeps_ship_and_name_through_end_combat(qb):
    hl, controller, QB = qb
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    plan = _scenario_with_player("Ambassador", "USS Excalibur")
    spawn.set_provider(lambda: plan)
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert QB.g_sPlayerType == "Ambassador"
    QB.EndSimulation()                                   # End Combat
    player = App.Game_GetCurrentGame().GetPlayer()
    assert QB.g_sPlayerType == "Ambassador"              # no revert
    assert spawn.apply_player_identity(player)
    reps = registry_texture.replacements_for(player)
    assert any(p.endswith("Excalibur.tga") for p in reps.values())
    assert player.GetDisplayName().GetCString() == "USS Excalibur"


def test_no_plan_falls_back_to_class_default(qb):
    import App
    from engine.appc import registry_texture
    from engine.quickbattle import spawn
    spawn.set_provider(None)
    player = App.Game_GetCurrentGame().GetPlayer()
    spawn.apply_player_identity(player)
    reps = registry_texture.replacements_for(player)
    assert any(p.endswith("Dauntless.tga") for p in reps.values())


def test_revert_hook_is_gone():
    from engine import host_loop
    assert not hasattr(host_loop, "_sync_quickbattle_player_revert")
```

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/host/test_qb_player_identity.py -q`. Expected: FAIL (no `apply_player_identity`, the revert hook is still present, the hook isn't installed at boot).

- [ ] **Step 3: Implement**

Append to `engine/quickbattle/spawn.py`:

```python
def apply_player_identity(ship) -> bool:
    """Registry + display name for a freshly created player (called from
    host_loop's QuickBattle reconcile block). No plan -> BC's class default."""
    from engine.appc import registry_texture
    plan = current_plan()
    if plan is None:
        return registry_texture.apply_class_default(ship)
    try:
        import App
        p = plan.player
        if p.registry:
            ship.ReplaceTexture(registry_path(p.class_id, p.registry),
                                registry_texture.REGISTRY_OLD_NAME)
        if p.display_name:
            ship.SetDisplayName(App.TGString(p.display_name))
        return True
    except Exception as e:
        _log.warning("quickbattle: player identity failed: %s", e)
        return False
```

In `engine/host_loop.py`:
1. In `load_quickbattle`, right after `_bs.install_quickbattle_hook(_QB, self._c.bridge_pins)`, add:
   ```python
   from engine.quickbattle import spawn as _qb_spawn
   _qb_spawn.install_generate_ships_hook(_QB)
   ```
2. In `start_quickbattle`, after `self._sync_quickbattle_spawn_set()`, add:
   ```python
   from engine.quickbattle import spawn as _qb_spawn
   _qb_spawn.sync_sdk(QB, _qb_spawn.current_plan())
   ```
3. In the QuickBattle reconcile block, replace `registry_texture.apply_class_default(_p)` with:
   ```python
   from engine.quickbattle import spawn as _qb_spawn
   _qb_spawn.apply_player_identity(_p)
   ```
   Keep the guard (`not registry_texture.has_replacements(_p)`), and update the comment to say it now applies the scenario's named player ship.
4. Delete `_sync_quickbattle_player_revert` and its tick-loop call with its comment. Leave `_sync_quick_battle_panel` alone.
5. In `tests/host/test_quickbattle_boot.py`, delete the three revert tests named above.

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/host/test_qb_player_identity.py tests/host/test_qb_spawn.py tests/host/test_quickbattle_boot.py tests/host/test_hull_decals_realize.py tests/unit/test_reconcile_runtime_ships.py -q`. Expected: pass.

Also run `grep -rn "_sync_quickbattle_player_revert\|_qb_original_player_type" engine tests`. Expected: no hits.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/spawn.py engine/host_loop.py tests/host/test_quickbattle_boot.py tests/host/test_qb_player_identity.py
git commit -m "feat(qb): boot installs the spawn hook; named player identity; drop the revert hook"
```

---

### Task 9: The panel (Python state machine)

**Files:**
- Rewrite: `engine/ui/quick_battle_setup_panel.py`
- Modify: `engine/host_loop.py`, at the panel construction (around line 9997): construct it as before. It registers itself as the spawn provider.
- Delete and replace: `tests/unit/test_quick_battle_setup_panel.py`
- Check: `tests/host/test_crew_menu_cursor.py` builds the panel. Keep it passing with the new constructor (`QuickBattleSetupPanel()` with no args must work).

**Interfaces:**
- Consumes: Tasks 1–7, `engine.ship_catalog` (`entries`, `species`, `insignia_path`, `ERAS`, `ROLES`, `DEFAULT_ERAS`), `engine.ui.ship_icons.icon_path_for_species`, and `spawn.set_provider` / `sync_sdk`.
- Produces:
  - **The class:**

    ```
    class QuickBattleSetupPanel(Panel):
        name = "quick-battle-setup"
        __init__(self, on_start=None, *, catalog_fn=None, presets=None, stats=None,
                 bio_fn=None, qb_module=_UNSET)
        scenario: Scenario            (property)
        is_open() / open() / close()
        render_payload() -> str | None
        dispatch_event(action) -> bool
        handle_key_esc() -> None
        invalidate() -> None
        current_plan() -> BattlePlan | None      # registered via spawn.set_provider
    _presets: PresetStore                    # tests seed presets through it
    ```

  - **Setup payload** (`setQuickBattleSetup(...)`):

    ```
    {"open": true,
     "groups": [{"id","name","player","allegiance","direction","distance","difficulty",
                 "summary","entries":[{"id","ship","title","variant","variant_label",
                                       "player","out_of_era","has_menu"}]}],
     "target": gid, "selected": ship_id|null,
     "draft": {"group","allegiance","direction","distance","difficulty"}|null,
     "confirm": {"title","body","ok"}|null,
     "eras": [ids on], "species": [names on],
     "presets": [names], "preset": name|null, "dirty": bool,
     "can_start": bool, "counts": {"<species>": n}, "summary": "2 groups · 1 ship"}
    ```

    When closed it is `{"open": false}`.
  - **Catalog payload** (`setQuickBattleCatalog(...)`), pushed on open and on a catalog change:

    ```
    {"ships": [{"id","title","species","role","era":[from,to]|"all","playable",
                "variants":[{"name","playable"}],"icon","bio","hull","shields"}],
     "hull_max","shield_max",
     "eras":[{"id","name","tag","start","end"}], "roles":[{"id","label"}],
     "species":[{"name","insignia","flagship_icon"}],
     "directions":[...], "distances":[{"id","label","km"}], "difficulties":[...]}
    ```

- **Behaviour.** Each item below is a test:
  - **Construction:** `default_scenario()`; target = the Enemy group; eras = `DEFAULT_ERAS`; species = `{"Federation"}`; `spawn.set_provider(self.current_plan)`.
  - **Catalog:** a catalog entry is listed only if `complete` and not in `ship_catalog.skipped()`. The catalog generation is `tuple(entries)`. A change re-reconciles the scenario, resets the stats cache and re-pushes the catalog.
  - **Changes:** every scenario-changing verb ends with `spawn.sync_sdk(qb, self.current_plan())` when the qb module is available.
  - **`select:<ship>`** toggles `selected`. An era or species change that hides the selected ship clears it.
  - **`add:<ship>`** adds to the target.
  - **`set-player:<ship>`** works only if `can_be_player(ce, None)`.
  - **`target:<gid>`** sets the add target.
  - **`group-new`** adds a group and targets it.
  - **`details:<gid>`** opens a draft (one at a time). Deleting a group also drops a draft that belongs to it. `draft:<field>:<value>` edits the draft. `draft-update` applies it through `update_details`; `draft-cancel` drops it.
  - **`rename:<gid>:<urlenc>`** renames.
  - **`group-delete:<gid>`** deletes straight away if the group is empty, and otherwise sets a confirmation ("Delete group?", "Delete ‹name› and its N ship(s)?", "Delete"). After a delete the target falls back to the first non-player group, else the player group.
  - **Ship rows:** `variant:<eid>:<urlenc|empty>`, `move:<eid>:<gid>`, `remove:<eid>`. A player variant must pass `can_be_player`.
  - **`preset-save:<urlenc>`** confirms first if the name exists ("Overwrite preset?" / "A preset named ‹X› already exists. Replace it with the current scenario?" / "Overwrite"), then saves. It sets `preset` and makes `dirty` False.
  - **`preset-load:<urlenc>`** confirms first if `dirty` ("Load preset?" / "Your current setup has unsaved changes. Load ‹X› anyway?" / "Load"), then loads, reconciles, retargets and clears the draft and selection.
  - **`preset-delete:<urlenc>`** always confirms ("Delete preset?" / "Delete preset ‹X›?" / "Delete"). Deleting the current preset clears `preset`.
  - **`confirm`** runs the pending action; **`cancel`** drops it.
  - **`dirty`:** `preset is None` → `can_start()`; otherwise `not same_setup(scenario, presets.load(preset))`.
  - **`start`:** if `can_start`, `_fire_close_dialog()` (kept from the old panel), `on_start()`, `close()`.
  - **`close`:** `_fire_close_dialog()`, `close()`.
  - **`esc`:** pops the innermost of confirm → draft → selected → close.
  - **`handle_key_esc()`:** sets a pending `"qbEscape();"` that the next `render_payload` prepends, then marks the panel due.
  - **Counts:** per species, the complete catalog entries whose `in_eras(eras)` is true, regardless of the species filter (as the spike does).
  - **`out_of_era`** = not `ce.in_eras(eras)`.
  - **Group summary:** player group → `"Friendly · escorts form up beside you"`; others → e.g. `"Enemy · Fore · Standard (35 km)"`. A non-medium difficulty appends `" · High"` / `" · Low"`.
  - **Footer summary:** `"%d group(s) · %d ship(s)"`, counting the player.
  - **Unknown verbs and ids** return False and log.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_quick_battle_setup_panel.py`, replace the file entirely. Build the panel with a fake catalog (reuse `_ce` from Task 3's tests: copy it, don't import across test files), a `PresetStore` on `tmp_path`, a stub stats object (`get` returns `ShipStats(1000, 2000)`; `maxima` returns `(24000, 49500)`), `bio_fn=lambda ce: "bio"`, and `qb_module=None` (no SDK). Parse payloads with `json.loads(out[len("setQuickBattleSetup("):-2])`; when both pushes are present, split on `");"` first.

```python
# tests/unit/test_quick_battle_setup_panel.py
import json

import pytest

from engine.quickbattle import presets as presets_mod
from engine.quickbattle.stats import ShipStats
from engine.ship_catalog import CatalogEntry, Variant
from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel


def _ce(ship_id, title=None, playable=True, variants=(), species="Federation",
        role="tactical", era=("DS9", "DS9")):
    return CatalogEntry(ship_id=ship_id, icon=ship_id, source="stock", origins=(),
                        title=title or ship_id, species=species, era=era, role=role,
                        playable=playable, variants=tuple(variants), missing=(),
                        errors=(), raw_name=title or ship_id, raw_race=None)


CATALOG = [
    _ce("Galaxy", variants=[Variant("USS Dauntless", registry="Dauntless"),
                            Variant("USS Venture", registry="Venture")]),
    _ce("Sovereign", variants=[Variant("USS Sovereign", registry="Sovereign")]),
    _ce("Warbird", species="Romulan"),
    _ce("FedStarbase", title="Fed Starbase", playable=False, role="station"),
    _ce("Excelsior", era=("MOV", "MOV")),
]


class _Stats:
    def get(self, f): return ShipStats(1000.0, 2000.0)
    def maxima(self, entries): return (24000.0, 49500.0)
    def reset(self): pass


@pytest.fixture
def panel(tmp_path):
    p = QuickBattleSetupPanel(
        on_start=lambda: started.append(1), catalog_fn=lambda: list(CATALOG),
        presets=presets_mod.load_presets(tmp_path / "p.json"), stats=_Stats(),
        bio_fn=lambda ce: "bio", qb_module=None)
    p.open()
    return p


started = []


def _setup(p):
    out = p.render_payload() or ""
    for chunk in out.split(");"):
        if "setQuickBattleSetup(" in chunk:
            return json.loads(chunk.split("setQuickBattleSetup(", 1)[1])
    p.invalidate()
    return _setup(p)


def _enemy(p):
    return p.scenario.groups[1]


def test_initial_state(panel):
    s = _setup(panel)
    assert s["open"] and s["target"] == _enemy(panel).id
    assert s["eras"] == ["DS9"] and s["species"] == ["Federation"]
    assert not s["can_start"] and s["preset"] is None
    assert s["summary"] == "2 groups · 1 ship"


def test_catalog_push_has_stats_bios_and_tables(panel):
    out = panel.render_payload()
    cat = json.loads(out.split("setQuickBattleCatalog(", 1)[1].split(");", 1)[0])
    ids = [s["id"] for s in cat["ships"]]
    assert "Galaxy" in ids and cat["hull_max"] == 24000.0
    g = next(s for s in cat["ships"] if s["id"] == "Galaxy")
    assert (g["hull"], g["shields"], g["bio"]) == (1000.0, 2000.0, "bio")
    assert [v["name"] for v in g["variants"]] == ["USS Dauntless", "USS Venture"]


def test_add_to_target_and_start(panel):
    started.clear()
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["can_start"]
    panel.dispatch_event("start")
    assert started == [1] and not panel.is_open()


def test_set_player_refuses_unplayable(panel):
    panel.dispatch_event("set-player:FedStarbase")
    assert panel.scenario.player_entry().ship == "Galaxy"
    panel.dispatch_event("set-player:Sovereign")
    assert panel.scenario.player_entry().ship == "Sovereign"


def test_group_new_targets_it_and_delete_with_ships_confirms(panel):
    panel.dispatch_event("group-new")
    g = panel.scenario.groups[-1]
    assert _setup(panel)["target"] == g.id
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("group-delete:" + g.id)
    s = _setup(panel)
    assert s["confirm"]["ok"] == "Delete" and panel.scenario.group(g.id) is not None
    panel.dispatch_event("confirm")
    assert panel.scenario.group(g.id) is None
    assert _setup(panel)["target"] == _enemy(panel).id


def test_empty_group_deletes_without_confirm(panel):
    panel.dispatch_event("group-delete:" + _enemy(panel).id)
    s = _setup(panel)
    assert s["confirm"] is None and len(panel.scenario.groups) == 1
    assert s["target"] == panel.scenario.player_group().id


def test_details_draft_update_and_cancel(panel):
    gid = _enemy(panel).id
    panel.dispatch_event("details:" + gid)
    panel.dispatch_event("draft:allegiance:neutral")
    panel.dispatch_event("draft:difficulty:high")
    panel.dispatch_event("draft-cancel")
    assert _enemy(panel).allegiance == "enemy"
    panel.dispatch_event("details:" + gid)
    panel.dispatch_event("draft:allegiance:neutral")
    panel.dispatch_event("draft:difficulty:high")
    panel.dispatch_event("draft-update")
    assert (_enemy(panel).allegiance, _enemy(panel).difficulty) == ("neutral", "high")
    assert _setup(panel)["draft"] is None


def test_rename_variant_move_remove(panel):
    gid = _enemy(panel).id
    panel.dispatch_event("rename:%s:%s" % (gid, "Raiders%20One"))
    assert _enemy(panel).name == "Raiders One"
    panel.dispatch_event("add:Galaxy")
    e = _enemy(panel).entries[0]
    panel.dispatch_event("variant:%s:%s" % (e.id, "USS%20Venture"))
    assert e.variant == "USS Venture"
    panel.dispatch_event("variant:%s:" % e.id)
    assert e.variant is None
    panel.dispatch_event("move:%s:%s" % (e.id, panel.scenario.player_group().id))
    assert e in panel.scenario.player_group().entries
    panel.dispatch_event("remove:" + e.id)
    assert e not in panel.scenario.player_group().entries


def test_presets_save_overwrite_load_dirty_delete(panel):
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("preset-save:Alpha")
    s = _setup(panel)
    assert s["preset"] == "Alpha" and not s["dirty"] and s["presets"] == ["Alpha"]
    panel.dispatch_event("add:Warbird")
    assert _setup(panel)["dirty"]
    panel.dispatch_event("preset-save:Alpha")
    assert _setup(panel)["confirm"]["ok"] == "Overwrite"
    panel.dispatch_event("cancel")
    panel.dispatch_event("preset-load:Alpha")
    assert _setup(panel)["confirm"]["ok"] == "Load"
    panel.dispatch_event("confirm")
    assert len(_enemy(panel).entries) == 1 and not _setup(panel)["dirty"]
    panel.dispatch_event("preset-delete:Alpha")
    panel.dispatch_event("confirm")
    s = _setup(panel)
    assert s["presets"] == [] and s["preset"] is None


def test_preset_load_reconciles(panel, tmp_path):
    from engine.quickbattle import scenario as sc
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "RemovedModShip")
    s.add_ship(s.groups[1].id, "Warbird")
    panel._presets.save("Old", s)
    panel.dispatch_event("preset-load:Old")
    assert [e.ship for e in _enemy(panel).entries] == ["Warbird"]


def test_filters_counts_out_of_era_and_selection_cleared(panel):
    panel.dispatch_event("add:Excelsior")
    s = _setup(panel)
    assert s["counts"]["Federation"] == 3       # Galaxy, Sovereign, Fed Starbase (DS9 only)
    row = _enemy(panel).entries[0]
    assert next(e for g in s["groups"] for e in g["entries"]
                if e["id"] == row.id)["out_of_era"]
    panel.dispatch_event("select:Galaxy")
    assert _setup(panel)["selected"] == "Galaxy"
    panel.dispatch_event("species:Federation")      # toggles Federation off
    assert _setup(panel)["selected"] is None


def test_esc_layers(panel):
    panel.dispatch_event("select:Galaxy")
    panel.dispatch_event("details:" + _enemy(panel).id)
    panel.dispatch_event("group-delete:" + _enemy(panel).id)  # empty -> deletes, no confirm
    panel.dispatch_event("esc")      # draft is gone with the group; closes the sheet
    assert _setup(panel)["selected"] is None
    panel.dispatch_event("esc")
    assert not panel.is_open()


def test_handle_key_esc_asks_the_page_first(panel):
    panel.render_payload()
    panel.handle_key_esc()
    assert (panel.render_payload() or "").startswith("qbEscape();")


def test_provider_and_unknown_verbs(panel):
    from engine.quickbattle import spawn
    panel.dispatch_event("add:Warbird")
    assert spawn.current_plan().orders[0].class_id == "Warbird"
    assert not panel.dispatch_event("nonsense")
    assert not panel.dispatch_event("remove:nope")


def test_closed_payload(panel):
    panel.close()
    assert '{"open": false}' in panel.render_payload()
```

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/unit/test_quick_battle_setup_panel.py -q`. Expected: FAIL (the old panel has no `scenario`, the constructor kwargs differ).

- [ ] **Step 3: Implement** `engine/ui/quick_battle_setup_panel.py` to the interface and behaviour list above. Structure:
  - **Keep:** `_fire_close_dialog` (read it from the old file first and keep it verbatim), the `_qb()` lazy import, `invalidate`, the `visible` setter idiom.
  - **Remove:** all widget-tree code, `_id_to_widget`, and the roster verbs.
  - **Parse verbs** with `verb, _, arg = action.partition(":")`, then `urllib.parse.unquote` for text args. Use a dispatch dict `{verb: handler}`. Each handler returns bool.
  - **Pending confirmation:** `self._confirm = {"title","body","ok","action": callable}`. `confirm` calls `action()` then clears it.
  - **Catalog generation:** `_refresh_catalog()` runs at the top of `render_payload` while open. It compares `tuple(catalog_fn())` with the cached generation; on a change it re-indexes, reconciles, resets stats and flags a catalog push.
  - **`render_payload`:** build `prefix = pending_js + catalog_push`, then the setup push (skipped when unchanged, as before). Return `None` when everything is empty.
  - **Insignia URL:** `insignia_path(name)` → `Path.as_uri()`, else `None`. `flagship_icon` = `ship_icons.icon_path_for_species(flagship) or None`. Ship `icon` = `ship_icons.icon_path_for_species(ce.icon) or None`.
  - **Defaults for injected dependencies:**
    - `catalog_fn`: `ship_catalog.entries`, with a filter of `complete and ship_id not in skipped()`.
    - `presets`: `presets.load_presets()` (lazy, first use).
    - `stats`: `stats.StatsCache()`.
    - `bio_fn`: `bios.ship_bio`.
  - **After every scenario mutation:** call `self._after_change()`. It invalidates `_last_pushed`, and if a qb module is present and not `bInSimulation`, calls `spawn.sync_sdk(qb, self.current_plan())`.
  - **`current_plan()`:** returns `None` when the catalog index is empty; otherwise `battle_plan(self.scenario, self._index)`.

  In `engine/host_loop.py`, the construction site needs no change beyond the constructor still accepting `on_start=`. Read the comment block above it and update its now-wrong lines: "Ships tab", "the panel's Add buttons".

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/unit/test_quick_battle_setup_panel.py tests/host/test_crew_menu_cursor.py tests/host/test_qb_spawn.py -q`. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/quick_battle_setup_panel.py engine/host_loop.py tests/unit/test_quick_battle_setup_panel.py
git commit -m "feat(qb): setup panel state machine over the scenario and catalog"
```

---

### Task 10: The page (port of the spike)

**Files:**
- Rewrite: `native/assets/ui-cef/js/quick_battle_setup.js`
- Rewrite: `native/assets/ui-cef/css/quick_battle_setup.css`
- Modify: `native/assets/ui-cef/index.html`: the `<section id="quick-battle-setup">` block (around lines 177-201) and its comment
- Test: `tests/unit/test_quick_battle_setup_page.py`

**Interfaces:**
- Consumes: the two payloads and the event verbs from Task 9, `text_capture.js` (already loaded by `index.html`), and `dauntlessEvent`.
- Produces three globals: `setQuickBattleCatalog(payload)`, `setQuickBattleSetup(payload)` and `qbEscape()`.

**Port rules** (spec §3, D11). The spike is the source of truth for every visual and every copy string:
1. **Markup:** port `index.html` lines 14-36 of the spike into the section. Use the spike's element ids with a `qbs-` prefix: `qbs-groups`, `qbs-eras`, `qbs-species`, `qbs-catalog`, `qbs-sheet`, `qbs-menu`, `qbs-overlay`, `qbs-preset-btn`, `qbs-save-btn`, `qbs-summary`, `qbs-close`, `qbs-start`. The section root carries **`data-panel="quick-battle-setup"`** (keyboard-capture contract).
2. **CSS:** port `spike.css` whole into `quick_battle_setup.css`:
   - rename the `qbx-` prefix to `qbs-`;
   - drop the spike-only rules: the body starfield background, `.missing-assets` banner and `MOCK` tag;
   - scope everything under `#quick-battle-setup`;
   - keep the allegiance colours (BC radar palette) and every size and spacing value.
3. **JS:** port `app.js`'s render functions one for one. Each takes its data from the latest payloads instead of local `state`:

   | spike `app.js` | page function | change |
   |---|---|---|
   | `renderGroups` / `renderGroup` / `renderRow` (≈120-194) | same names | read `setup.groups`, `setup.target`, `setup.draft`; group summary text comes from Python (`summary`) |
   | Details form (≈151-162) | `renderDetails` | add a **Difficulty** segmented row (Low / Medium / High) after Distance; for the player group render **only** that row |
   | `renderEras` / `renderSpecies` (≈197-220) | same | pill state from `setup.eras` / `setup.species`; counts from `setup.counts` |
   | `renderCatalog` (≈223-255) | same | ships from `catalog.ships`, filtered client-side by `setup.eras` / `setup.species` exactly as the spike filters (role order from `catalog.roles`, species-pill order within a role) |
   | `renderSheet` + scale bars (≈257-304, 21-29) | same | `catalog.hull_max` / `shield_max`; same clamp (1.5–100%), gold + "OFF SCALE" above max, "None" for 0, "No hardpoint data for this entry." for null |
   | `renderFooter` (≈307-314) | same | `setup.summary`, `setup.can_start`, the preset label "Preset: ‹name› ▾" or "Load preset ▾" |
   | menus (≈335-468) | same | the Load preset menu adds a **×** per row → `preset-delete:`; menu items fire events instead of mutating state |
   | overlay (Overwrite preset?) | `renderConfirm` | drawn from `setup.confirm` (title, body, ok); buttons fire `confirm` / `cancel` |
   | toast (≈470-477) | `toast` | shown on preset save/load: compare the `setup.preset` and `setup.presets` changes between pushes |
   | wheel→horizontal on pill rows (≈650-657) | same | unchanged |
   | rename input, preset-name input | same | commit on **`change`** with `dauntlessEvent('quick-battle-setup/rename:'+gid+':'+encodeURIComponent(v))` / `preset-save:`; never on `keydown` |

   - **Every click** sends `dauntlessEvent('quick-battle-setup/<verb>')`. Only the popover menu's open/closed state is page-local.
   - **`qbEscape()`:** if a popover is open, close it; else `dauntlessEvent('quick-battle-setup/esc')`.
   - **`setQuickBattleSetup({open:false})`:** hides the section and closes any popover.
   - **Escape `msEsc`-style:** HTML-escape every catalog or scenario string (mod titles are untrusted text). Copy the helper pattern from `mods_screen.js`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_quick_battle_setup_page.py
"""Source-shape guards for the ported page (no JS runtime, as the keyboard
capture work decided: spec 2026-10-02-cef-text-input-keyboard-capture-design D6)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
JS = (ROOT / "js" / "quick_battle_setup.js").read_text()
CSS = (ROOT / "css" / "quick_battle_setup.css").read_text()
HTML = (ROOT / "index.html").read_text()
SECTION = HTML.split('<section id="quick-battle-setup"', 1)[1].split("</section>", 1)[0]


def test_entry_points_exist():
    for fn in ("setQuickBattleCatalog", "setQuickBattleSetup", "qbEscape"):
        assert re.search(r"function\s+%s\s*\(" % fn, JS), fn


def test_section_declares_panel_for_key_capture():
    assert 'data-panel="quick-battle-setup"' in SECTION


def test_no_forbidden_offscreen_cef_constructs():
    for text in (JS, SECTION):
        assert "<select" not in text
        assert "draggable" not in text
        assert not re.search(r"\btitle\s*=", text)


def test_text_inputs_commit_on_change_not_keydown():
    assert "'change'" in JS or '"change"' in JS
    assert "keydown" not in JS


def test_every_event_verb_python_handles_is_used():
    verbs = ["era:", "species:", "select:", "add:", "set-player:", "target:", "group-new",
             "details:", "draft:", "draft-update", "draft-cancel", "rename:", "group-delete:",
             "variant:", "move:", "remove:", "preset-load:", "preset-save:", "preset-delete:",
             "confirm", "cancel", "start", "close", "esc"]
    for v in verbs:
        assert "quick-battle-setup/" + v in JS, v


def test_difficulty_row_and_spike_copy_present():
    for copy in ("Difficulty", "Low", "Medium", "High", "+ New group", "ADDING HERE",
                 "No ships yet", "Load preset", "Out of era", "OFF SCALE",
                 "No hardpoint data for this entry.", "Start Battle"):
        assert copy in JS or copy in SECTION or copy in CSS, copy


def test_css_scoped_and_prefixed():
    assert "qbx-" not in CSS and "qbs-" in CSS
```

- [ ] **Step 2: Run to verify fail.** `uv run pytest tests/unit/test_quick_battle_setup_page.py -q`. Expected: FAIL (the old JS lacks the entry points and verbs).

- [ ] **Step 3: Implement** the port as specified. The spike's copy uses CSS `text-transform` for upper case. If a string such as "ADDING HERE" appears in upper case only through CSS, put the literal the spike's JS uses into the JS, and adjust the copy test's string to the spike's literal. Never weaken the test to pass.

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/unit/test_quick_battle_setup_page.py tests/unit/test_quick_battle_setup_panel.py -q`, then `grep -rn "text_capture" native/assets/ui-cef/index.html`. Expected: pass, and `text_capture.js` is loaded once, before `quick_battle_setup.js` is used.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/js/quick_battle_setup.js native/assets/ui-cef/css/quick_battle_setup.css native/assets/ui-cef/index.html tests/unit/test_quick_battle_setup_page.py
git commit -m "feat(qb): port the approved spike's setup screen to the CEF page"
```

---

### Task 11: End-to-end, docs, gate

**Files:**
- Test: `tests/integration/test_quickbattle_setup_e2e.py`
- Modify: `CLAUDE.md`: add one key-reference row, "Quick Battle setup + group spawning" (see Step 3)
- Modify: `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md`: set sub-project 2's status to "implemented on `feat/qb-setup-screen`, awaiting live check"
- Modify: `docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md`: change Status to "implemented, awaiting live check"

**Interfaces:**
- Consumes everything above. The E2E drives the real panel's `dispatch_event` → `start` → the SDK chain, headless.

- [ ] **Step 1: Write the failing E2E**

```python
# tests/integration/test_quickbattle_setup_e2e.py
"""Headless: panel -> start -> spawn -> win / loss -> End Combat keeps the setup."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def world(monkeypatch, tmp_path):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    from engine.quickbattle import presets
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    panel = QuickBattleSetupPanel(on_start=lambda: controller.loader.start_quickbattle(),
                                  presets=presets.load_presets(tmp_path / "p.json"))
    panel.open()
    panel.render_payload()
    import QuickBattle.QuickBattle as QB
    yield hl, controller, panel, QB
    from engine.quickbattle import spawn
    spawn.set_provider(None)


def _go(hl, panel):
    import App
    panel.dispatch_event("start")
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()


def _destroy(QB, ship):
    import App
    evt = App.TGEvent_Create()
    evt.SetDestination(ship)
    QB.ShipDestroyed(None, evt)


def _ships(QB):
    import App
    return {s.GetName(): s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)}


def test_enemy_and_neutral_groups_then_win(world):
    hl, _c, panel, QB = world
    enemy = panel.scenario.groups[1]
    panel.dispatch_event("add:Warbird")
    panel.dispatch_event("group-new")
    g = panel.scenario.groups[-1]
    panel.dispatch_event("details:" + g.id)
    for f, v in (("allegiance", "neutral"), ("direction", "port"), ("distance", "close")):
        panel.dispatch_event("draft:%s:%s" % (f, v))
    panel.dispatch_event("draft-update")
    panel.dispatch_event("add:Transport")
    _go(hl, panel)
    ships = _ships(QB)
    assert "Warbird-1" in ships and "Transport-2" in ships
    assert QB.g_iNumEnemies == 1
    _destroy(QB, ships["Transport-2"])               # a neutral: no effect on the win
    assert QB.bWonOrLost == 0
    _destroy(QB, ships["Warbird-1"])
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1
    assert enemy is panel.scenario.groups[1]


def test_player_death_is_a_loss(world):
    hl, _c, panel, QB = world
    import App
    panel.dispatch_event("add:Warbird")
    _go(hl, panel)
    _destroy(QB, App.Game_GetCurrentGame().GetPlayer())
    assert QB.g_idTimer                               # loss timer posted (QuickBattle.py:3304)


def test_end_combat_keeps_player_ship_and_setup(world):
    hl, _c, panel, QB = world
    import App
    panel.dispatch_event("set-player:Sovereign")
    panel.dispatch_event("add:Warbird")
    before = panel.scenario.to_json()
    _go(hl, panel)
    QB.EndSimulation()
    hl._process_object_deletions()
    assert QB.g_sPlayerType == "Sovereign"
    assert panel.scenario.to_json() == before
    assert App.Game_GetCurrentGame().GetPlayer() is not None
```

- [ ] **Step 2: Run to verify.** `uv run pytest tests/integration/test_quickbattle_setup_e2e.py -q`. Expected: pass if Tasks 1–10 are right. If a test fails, find the cause (superpowers:systematic-debugging) and fix the owning task's code, not this test.

- [ ] **Step 3: Docs.**
  - **CLAUDE.md:** add one row to the Key reference table, matching the style of neighbouring rows. Name: "Quick Battle setup + group spawning". Location: `engine/quickbattle/`, `engine/ui/quick_battle_setup_panel.py`, `docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md`. Content, in one paragraph:
    - Only `GenerateShips` is wrapped (`spawn.install_generate_ships_hook`), and it reads the panel's plan through `spawn.set_provider` at call time. With no provider, BC's original runs.
    - Neutrals have no `g_kShips` entry.
    - ⚠️ The setup is per-run; only presets are on disk (`quickbattle_presets.json`).
    - ⚠️ The revert-on-End-Combat hook is gone on purpose.
    - Placement is deterministic (`placement.py`).
    - The player's name is applied in host_loop's QuickBattle reconcile block via `spawn.apply_player_identity`.
  - Roadmap and spec status lines as listed above.

- [ ] **Step 4: Run the gate.**

Run: `scripts/check_tests.sh`. Expected: exit 0. If it names a failure not in `tests/known_failures.txt`, it's a regression from this branch. Fix it; never baseline it. A test elsewhere that still drove the old panel's roster verbs or the revert hook is updated in the task that owns it, here.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_quickbattle_setup_e2e.py CLAUDE.md docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md
git commit -m "test(qb): setup-to-win/loss E2E; docs for the new Quick Battle setup"
```

---

## Live checks (Mark, after Task 11)

These are spec §8:
1. The screen beside the spike: layout, pills, catalog, sheet, scale bars, group menus, presets.
2. Enemy fore Standard and Neutral port Close: placement, facing, neutral colours, neutrals inert.
3. Ambassador USS Excalibur as the player: hull name and display name.
4. Win → End Combat → reopen: same setup, same player ship.
5. Typing in Rename and preset names fires no game keys.
