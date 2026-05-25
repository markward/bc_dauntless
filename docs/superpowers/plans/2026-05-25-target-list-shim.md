# Target List — Shim + Panel Framework + First Visible Panel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a visible LCARS-styled target list panel in the CEF overlay, populated from a Python shim that satisfies the SDK contract, using the minimum panel framework needed to let two CEF panels coexist (pause menu + target list).

**Architecture (four layers):**

1. **SDK shim** (`engine/appc/target_menu.py`) — provides `STTargetMenu`, `STSubsystemMenu`, `STComponentMenu`, the module-level singleton, factory and cast helpers, and the affiliation resolver. Sized exactly to the SDK call surface (5 mutators + child traversal + `GetObjectEntry`), nothing speculative.
2. **Panel framework** (`engine/ui/panel.py`, `engine/ui/panel_registry.py`) — a `Panel` base class with `render_payload()`/`dispatch_event()`/`visible` and a `PanelRegistry` that pumps registered panels each tick and routes slash-prefixed JS events (`target/<ship>`) to the right panel, falling back to the legacy pause-menu handler for unprefixed events. **Pause menu is not refactored** — it stays as the existing reference implementation; the registry just wraps its dispatch as the legacy fallback.
3. **Target list panel** — Python view `engine/ui/target_list_view.py` reads `STTargetMenu_GetTargetMenu()` each tick and builds a JSON state payload; JS file `native/assets/ui-cef/js/target_list.js` consumes it and rebuilds the DOM; HTML markup added to `hello.html`; CSS in `native/assets/ui-cef/css/target_list.css` matching `docs/ui_designs/02-tactical-cluster.html`.
4. **Host integration** — `engine/host_loop.py` constructs the panel registry, wires it as the single CEF event handler, pumps `render_payload` on every tick (not just while paused), forwards mouse to CEF whenever any non-pause panel needs interaction, and injects three demo ships at startup so the panel is non-empty until engine auto-population lands.

**What's visible at the end:** Launch `./build/dauntless`. The target list panel is drawn in the upper-left corner of the screen, showing three demo ship names tinted by affiliation (friendly = blue, enemy = red, neutral = yellow). Clicking a row fires `pPlayer.SetTarget(ship_name)` and the row is visibly marked as selected (chosen styling).

**What's still deferred to a follow-up plan:**

- Engine auto-population: ships entering the bridge set should automatically appear in the list; this requires set-manager event hooks not yet present.
- Sensor visibility integration: `STSubsystemMenu.IsVisible()` should reflect sensor-range gating.
- Subsystem rows: each ship's targetable subsystems shown as expandable children.
- Keyboard cycling: `T`/`Y` bindings → `App.ET_INPUT_TARGET_NEXT` → `TacticalInterfaceHandlers.TargetNext`. The shim supports it; the host loop wiring of input events doesn't.
- Reticule rendering in the 3D scene (parked by the user — separate project).

**Tech stack:** Python 3, pytest, vanilla JS, CSS, existing CEF infrastructure (`native/src/ui_cef/`). No new third-party dependencies.

**Spec references:**
- Target-list SDK contract derivation: this conversation; key SDK callsites at
  `sdk/Build/scripts/App.py:8051-8201`,
  `sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:489-502`,
  `sdk/Build/scripts/TacticalInterfaceHandlers.py:683-733`,
  `sdk/Build/scripts/MissionLib.py:2186-2225`.
- Visual reference: `docs/ui_designs/02-tactical-cluster.md` and `.html` (palette, chrome).
- Existing patterns: `engine/ui/pause_menu.py` (Python view), `native/assets/ui-cef/js/pause_menu.js` (JS render fn), `native/assets/ui-cef/hello.html` (host page).

---

## File Structure

**New files**

- `engine/appc/target_menu.py` — three shim classes + module-level singleton/factory/cast/affiliation helper. ~200 lines.
- `engine/ui/panel.py` — `Panel` abstract base class. ~50 lines.
- `engine/ui/panel_registry.py` — `PanelRegistry` with prefix routing + legacy fallback. ~80 lines.
- `engine/ui/target_list_view.py` — Python view that reads the singleton and emits state payloads. ~120 lines.
- `native/assets/ui-cef/js/target_list.js` — `setTargetList(state)` render function + `dauntlessEvent` reuse. ~50 lines.
- `native/assets/ui-cef/css/target_list.css` — LCARS chrome + row styling. ~80 lines.
- `tests/unit/test_target_menu_shim.py` — shim API tests.
- `tests/unit/test_panel_registry.py` — framework tests.
- `tests/unit/test_target_list_view.py` — view state-payload tests.
- `tests/integration/test_target_list_sdk_integration.py` — load real SDK scripts against the shim.

**Modified files**

- `App.py` — re-export the new symbols (lines 95-103 area).
- `native/assets/ui-cef/hello.html` — add the target list panel container element + `<script src="js/target_list.js">` + `<link rel="stylesheet" href="css/target_list.css">`.
- `engine/host_loop.py` — construct the panel registry at startup; replace the direct `_cef_set_event_handler(pause_menu.dispatch_event)` call with `_cef_set_event_handler(registry.dispatch)`; pump registry render on every tick.
- `docs/ui_designs/SDK_UI_API.md` — fix the §3 events table (remove fictional `ET_TARGET_SELECTED`).

---

## Task 1: STSubsystemMenu + STComponentMenu stubs

**Files:**
- Create: `engine/appc/target_menu.py`
- Modify: `App.py`
- Create: `tests/unit/test_target_menu_shim.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_target_menu_shim.py
"""Unit tests for the target-list SDK shim (engine/appc/target_menu.py)."""
import App
from engine.appc.ships import ShipClass


def test_st_subsystem_menu_records_ship_and_defaults_visible():
    ship = ShipClass()
    ship.SetName("Test Ship")
    menu = App.STSubsystemMenu(ship)
    assert menu.GetShip() is ship
    assert menu.IsVisible() == 1


def test_st_subsystem_menu_show_name_methods_are_noops():
    """ShowUnknownName / ShowRealName never called by SDK; must not raise."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    menu.ShowUnknownName()
    menu.ShowRealName()


def test_st_component_menu_is_st_menu_subclass():
    """STComponentMenu never invoked from SDK Python; bare subclass is enough."""
    from engine.appc.characters import STMenu
    assert issubclass(App.STComponentMenu, STMenu)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: FAIL with `AttributeError: module 'App' has no attribute 'STSubsystemMenu'`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/target_menu.py`:

```python
"""SDK target-list shim — STTargetMenu / STSubsystemMenu / STComponentMenu.

Mirrors the SDK surface at sdk/Build/scripts/App.py:8051-8201 with only
the calls SDK Python scripts actually make. Engine-internal methods
(ShowUnknownName / ShowRealName) are no-ops; the engine layer drives
sensor identification state directly in a later phase.

Plan: docs/superpowers/plans/2026-05-25-target-list-shim.md
"""
from __future__ import annotations

from engine.appc.characters import STMenu, STTopLevelMenu


class STSubsystemMenu(STMenu):
    """One row in the target list — represents a single ship.

    SDK pattern: target_menu's children are STSubsystemMenu siblings,
    each subsystem-menu's children are per-subsystem rows. CycleTarget
    reads GetShip() and IsVisible() on each STSubsystemMenu sibling.
    """

    def __init__(self, ship, label: str = ""):
        super().__init__(label or (ship.GetName() if ship else ""))
        self._ship = ship

    def GetShip(self):
        return self._ship

    def IsVisible(self) -> int:
        return 1 if self._visible else 0

    def ShowUnknownName(self, *args) -> None:
        """Engine-internal — sensor ID state. SDK never calls."""
        pass

    def ShowRealName(self, *args) -> None:
        """Engine-internal — sensor ID state. SDK never calls."""
        pass


class STComponentMenu(STMenu):
    """Per-component sub-row inside STSubsystemMenu.

    Never invoked from SDK Python; empty subclass satisfies isinstance
    checks if they ever appear in code we load.
    """
    pass
```

Add to `App.py` immediately after the `from engine.appc.characters import (...)` block (around line 103):

```python
from engine.appc.target_menu import (
    STSubsystemMenu,
    STComponentMenu,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_shim.py App.py
git commit -m "$(cat <<'EOF'
target_menu: STSubsystemMenu + STComponentMenu shim stubs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: STTargetMenu + sibling traversal + GetObjectEntry

**Files:**
- Modify: `engine/appc/target_menu.py`
- Modify: `App.py`
- Modify: `tests/unit/test_target_menu_shim.py`

`STTargetMenu` extends `STTopLevelMenu` (per SDK). CycleTarget at
`TacticalInterfaceHandlers.py:700-732` walks children via `GetFirstChild`,
`GetLastChild`, `GetNextChild`, `GetPrevChild`. `GetObjectEntry(ship)` at
line 711 finds the row whose `GetShip() is ship`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_menu_shim.py`:

```python
def test_st_target_menu_inherits_st_top_level_menu():
    from engine.appc.characters import STTopLevelMenu
    menu = App.STTargetMenu("Targets")
    assert isinstance(menu, STTopLevelMenu)
    assert menu.GetLabel() == "Targets"


def test_st_target_menu_child_traversal():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b, ship_c = ShipClass(), ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B"); ship_c.SetName("C")
    sub_a, sub_b, sub_c = (
        App.STSubsystemMenu(ship_a),
        App.STSubsystemMenu(ship_b),
        App.STSubsystemMenu(ship_c),
    )
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    target_menu.AddChild(sub_c)

    assert target_menu.GetFirstChild() is sub_a
    assert target_menu.GetLastChild() is sub_c
    assert target_menu.GetNextChild(sub_a) is sub_b
    assert target_menu.GetNextChild(sub_c) is None
    assert target_menu.GetPrevChild(sub_c) is sub_b
    assert target_menu.GetPrevChild(sub_a) is None


def test_st_target_menu_get_object_entry_by_ship_identity():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b = ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B")
    sub_a = App.STSubsystemMenu(ship_a)
    sub_b = App.STSubsystemMenu(ship_b)
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    assert target_menu.GetObjectEntry(ship_a) is sub_a
    assert target_menu.GetObjectEntry(ship_b) is sub_b
    stranger = ShipClass(); stranger.SetName("?")
    assert target_menu.GetObjectEntry(stranger) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: FAIL — `module 'App' has no attribute 'STTargetMenu'`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/target_menu.py`:

```python
class STTargetMenu(STTopLevelMenu):
    """The whole target list — children are STSubsystemMenu rows."""

    def __init__(self, label: str = ""):
        super().__init__(label)
        # The last ship the player manually selected. Survives across
        # mission saves so a reload restores the selection. SDK callers
        # mutate via ClearPersistentTarget; engine sets it on real clicks.
        self._persistent_target_name: str | None = None

    # ── Sibling traversal required by CycleTarget ──
    def GetFirstChild(self):
        return self._children[0] if self._children else None

    def GetLastChild(self):
        return self._children[-1] if self._children else None

    def GetNextChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i + 1] if i + 1 < len(self._children) else None

    def GetPrevChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i - 1] if i > 0 else None

    def GetObjectEntry(self, ship):
        """Return the STSubsystemMenu whose GetShip() is ``ship``.

        SDK: TacticalInterfaceHandlers.py:711 (CycleTarget). Identity
        comparison — the SDK passes the actual ShipClass object.
        """
        for child in self._children:
            if isinstance(child, STSubsystemMenu) and child.GetShip() is ship:
                return child
        return None
```

Update the `App.py` import block:

```python
from engine.appc.target_menu import (
    STSubsystemMenu,
    STComponentMenu,
    STTargetMenu,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_shim.py App.py
git commit -m "$(cat <<'EOF'
target_menu: STTargetMenu with traversal and GetObjectEntry for CycleTarget

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Factory + singleton + cast helpers + Clear* mutators

**Files:**
- Modify: `engine/appc/target_menu.py`
- Modify: `App.py`
- Modify: `tests/unit/test_target_menu_shim.py`

Five things grouped here because each is tiny and they share the same
commit theme ("SDK lookup + lifecycle"):
- `STTargetMenu_CreateW(label)` — factory used at `Bridge/TacticalMenuHandlers.py:492`.
- `STTargetMenu_GetTargetMenu()` — singleton accessor at `App.py:11992`.
- `STSubsystemMenu_Cast` and `STComponentMenu_Cast` — lenient casts matching the existing `STMenu_Cast` pattern.
- `STTargetMenu.ClearTargetList()` — `Multiplayer/MissionShared.py:353`.
- `STTargetMenu.ClearPersistentTarget()` — three callsites; drops the persistent-target hint.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_menu_shim.py`:

```python
def test_create_w_installs_singleton():
    App._reset_target_menu_singleton()
    assert App.STTargetMenu_GetTargetMenu() is None

    menu = App.STTargetMenu_CreateW("Targets")
    assert isinstance(menu, App.STTargetMenu)
    assert menu.GetLabel() == "Targets"
    assert App.STTargetMenu_GetTargetMenu() is menu


def test_subsystem_menu_cast_lenient_passthrough():
    """Mirrors STMenu_Cast — real instance → self; None → None; other → pass through."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    assert App.STSubsystemMenu_Cast(menu) is menu
    assert App.STSubsystemMenu_Cast(None) is None
    sentinel = object()
    assert App.STSubsystemMenu_Cast(sentinel) is sentinel


def test_clear_target_list_removes_all_rows():
    target_menu = App.STTargetMenu("Targets")
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.ClearTargetList()
    assert target_menu.GetFirstChild() is None


def test_clear_persistent_target_drops_hint():
    target_menu = App.STTargetMenu("Targets")
    target_menu.SetPersistentTarget("USS Enterprise")
    assert target_menu.GetPersistentTarget() == "USS Enterprise"
    target_menu.ClearPersistentTarget()
    assert target_menu.GetPersistentTarget() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 4 new failures with `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

Append to `engine/appc/target_menu.py`:

```python
# ── Module-level singleton + factory ─────────────────────────────────────────

_target_menu_singleton: STTargetMenu | None = None


def STTargetMenu_CreateW(label: str = "") -> STTargetMenu:
    """SDK factory — Bridge/TacticalMenuHandlers.py:492."""
    global _target_menu_singleton
    _target_menu_singleton = STTargetMenu(str(label))
    return _target_menu_singleton


def STTargetMenu_GetTargetMenu() -> "STTargetMenu | None":
    """SDK accessor — TacticalInterfaceHandlers + MissionLib + others."""
    return _target_menu_singleton


def _reset_target_menu_singleton() -> None:
    """Test-only — clear singleton between tests."""
    global _target_menu_singleton
    _target_menu_singleton = None


# ── Lenient cast helpers ─────────────────────────────────────────────────────

def STSubsystemMenu_Cast(obj):
    """Mirrors STMenu_Cast lenient pass-through in characters.py."""
    if isinstance(obj, STSubsystemMenu):
        return obj
    if obj is None:
        return None
    return obj


def STComponentMenu_Cast(obj):
    if isinstance(obj, STComponentMenu):
        return obj
    if obj is None:
        return None
    return obj
```

Append to `STTargetMenu` (after `GetObjectEntry`):

```python
    # ── Mutators SDK scripts actually call ──

    def ClearTargetList(self) -> None:
        """SDK: Multiplayer/MissionShared.py:353."""
        self.KillChildren()

    def ClearPersistentTarget(self) -> None:
        """SDK: TacticalInterfaceHandlers.py:656, HelmMenuHandlers.py:947,
        MissionShared.py:354."""
        self._persistent_target_name = None

    def SetPersistentTarget(self, name) -> None:
        self._persistent_target_name = str(name) if name else None

    def GetPersistentTarget(self) -> "str | None":
        return self._persistent_target_name
```

Update the `App.py` import block:

```python
from engine.appc.target_menu import (
    STSubsystemMenu, STSubsystemMenu_Cast,
    STComponentMenu, STComponentMenu_Cast,
    STTargetMenu,
    STTargetMenu_CreateW, STTargetMenu_GetTargetMenu,
    _reset_target_menu_singleton,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_shim.py App.py
git commit -m "$(cat <<'EOF'
target_menu: factory, singleton, casts, ClearTargetList, ClearPersistentTarget

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Affiliation resolver + ResetAffiliationColors

**Files:**
- Modify: `engine/appc/target_menu.py`
- Modify: `tests/unit/test_target_menu_shim.py`

Mission groups override the ship's static `Affiliation` integer property
(confirmed: `E2M2.py:789`, `E2M6.py:1066` call `ResetAffiliationColors()`
after `AddToFriendlyGroup`/`AddToEnemyGroup` — never after `SetAffiliation()`).
Resolution order: FRIENDLY group → ENEMY group → NEUTRAL group → UNKNOWN.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_menu_shim.py`:

```python
def _make_mission_with_groups(friendly=(), enemy=(), neutral=()):
    from engine.core.game import Mission
    m = Mission()
    for name in friendly:
        m.GetFriendlyGroup().AddName(name)
    for name in enemy:
        m.GetEnemyGroup().AddName(name)
    for name in neutral:
        m.GetNeutralGroup().AddName(name)
    return m


def test_resolve_affiliation_uses_mission_groups():
    from engine.appc.target_menu import resolve_affiliation
    mission = _make_mission_with_groups(
        friendly=["F"], enemy=["E"], neutral=["N"]
    )
    f = ShipClass(); f.SetName("F")
    e = ShipClass(); e.SetName("E")
    n = ShipClass(); n.SetName("N")
    u = ShipClass(); u.SetName("U")
    assert resolve_affiliation(f, mission) == "FRIENDLY"
    assert resolve_affiliation(e, mission) == "ENEMY"
    assert resolve_affiliation(n, mission) == "NEUTRAL"
    assert resolve_affiliation(u, mission) == "UNKNOWN"


def test_reset_affiliation_colors_recomputes_each_row():
    from engine.core.game import Game, Episode, _set_current_game

    mission = _make_mission_with_groups(friendly=["Dauntless"], enemy=["Kor"])
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    _set_current_game(game)
    try:
        a = ShipClass(); a.SetName("Dauntless")
        b = ShipClass(); b.SetName("Kor")
        target_menu = App.STTargetMenu("Targets")
        sub_a, sub_b = App.STSubsystemMenu(a), App.STSubsystemMenu(b)
        target_menu.AddChild(sub_a); target_menu.AddChild(sub_b)

        target_menu.ResetAffiliationColors()
        assert sub_a.GetAffiliation() == "FRIENDLY"
        assert sub_b.GetAffiliation() == "ENEMY"

        # Defection: Kor changes sides mid-mission.
        mission.GetEnemyGroup().RemoveName("Kor")
        mission.GetFriendlyGroup().AddName("Kor")
        target_menu.ResetAffiliationColors()
        assert sub_b.GetAffiliation() == "FRIENDLY"
    finally:
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: FAIL — `cannot import name 'resolve_affiliation'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/target_menu.py`, add to `STSubsystemMenu.__init__` (after `self._ship = ship`):

```python
        self._affiliation: str = "UNKNOWN"
```

Add to `STSubsystemMenu`:

```python
    def GetAffiliation(self) -> str:
        return self._affiliation

    def SetAffiliation(self, token: str) -> None:
        self._affiliation = token
```

Append to module:

```python
def resolve_affiliation(ship, mission) -> str:
    """Mission groups override static ship-property affiliation.

    Returns one of "FRIENDLY", "ENEMY", "NEUTRAL", "UNKNOWN" — the
    engine layer maps these to the radar colour palette from
    docs/ui_designs/SDK_UI_API.md §1.4.
    """
    if mission is None or ship is None:
        return "UNKNOWN"
    name = ship.GetName()
    if mission.GetFriendlyGroup().IsNameInGroup(name):
        return "FRIENDLY"
    if mission.GetEnemyGroup().IsNameInGroup(name):
        return "ENEMY"
    if mission.GetNeutralGroup().IsNameInGroup(name):
        return "NEUTRAL"
    return "UNKNOWN"
```

Add to `STTargetMenu` (after the `Clear*` methods):

```python
    def ResetAffiliationColors(self) -> None:
        """Recompute every row's affiliation token. SDK callsites:
        Maelstrom/Episode2/E2M2.py:789, E2M6.py:1066 — invoked after
        a mission reassigns ships between groups."""
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        mission = None
        if game is not None:
            ep = game.GetCurrentEpisode()
            if ep is not None:
                mission = ep.GetCurrentMission()
        for child in self._children:
            if isinstance(child, STSubsystemMenu):
                child.SetAffiliation(resolve_affiliation(child.GetShip(), mission))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_shim.py
git commit -m "$(cat <<'EOF'
target_menu: affiliation resolver + ResetAffiliationColors

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: RebuildShipMenu + RebuildShipMenus

**Files:**
- Modify: `engine/appc/target_menu.py`
- Modify: `tests/unit/test_target_menu_shim.py`

`RebuildShipMenu(pShip)` is the SDK's per-ship add/refresh path
(`MissionLib.HideSubsystems`/`ShowSubsystems` at lines 2200/2225).
`RebuildShipMenus()` (plural) is engine-internal — never called from
Python — but the API must exist so the next phase's auto-population
hooks have an entry point.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_target_menu_shim.py`:

```python
def test_rebuild_ship_menu_creates_row_for_new_ship():
    target_menu = App.STTargetMenu("Targets")
    ship = ShipClass(); ship.SetName("Dauntless")
    assert target_menu.GetObjectEntry(ship) is None

    target_menu.RebuildShipMenu(ship)

    row = target_menu.GetObjectEntry(ship)
    assert isinstance(row, App.STSubsystemMenu)
    assert row.GetShip() is ship


def test_rebuild_ship_menu_reuses_existing_row():
    target_menu = App.STTargetMenu("Targets")
    ship = ShipClass(); ship.SetName("Dauntless")
    target_menu.RebuildShipMenu(ship)
    first = target_menu.GetObjectEntry(ship)
    target_menu.RebuildShipMenu(ship)
    second = target_menu.GetObjectEntry(ship)
    assert first is second


def test_rebuild_ship_menus_walks_bridge_set():
    target_menu = App.STTargetMenu("Targets")
    bridge_set = App.g_kSetManager.GetSet("bridge")
    a = ShipClass(); a.SetName("A"); bridge_set.AddObjectToSet(a, "A")
    b = ShipClass(); b.SetName("B"); bridge_set.AddObjectToSet(b, "B")

    target_menu.RebuildShipMenus()

    assert target_menu.GetObjectEntry(a) is not None
    assert target_menu.GetObjectEntry(b) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: FAIL — `AttributeError: 'STTargetMenu' object has no attribute 'RebuildShipMenu'`.

- [ ] **Step 3: Write minimal implementation**

Add to `STTargetMenu`:

```python
    def RebuildShipMenu(self, ship) -> None:
        """Add or refresh the row for ``ship``. SDK callsites:
        MissionLib.py:2200, MissionLib.py:2225.

        Phase 1: include every subsystem regardless of IsTargetable —
        the per-subsystem targetable filter arrives with the engine
        integration phase.
        """
        if ship is None:
            return
        row = self.GetObjectEntry(ship)
        if row is None:
            row = STSubsystemMenu(ship, ship.GetName())
            self.AddChild(row)
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch()
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            label = sub.GetName() if hasattr(sub, "GetName") else ""
            row.AddChild(STMenu(label))
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)

    def RebuildShipMenus(self) -> None:
        """Bulk rebuild. Never called from SDK Python; included so the
        engine auto-population hook has a single entry point."""
        import App as _App
        bridge = _App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            return
        for obj in list(bridge.GetObjectList()):
            if hasattr(obj, "StartGetSubsystemMatch"):
                self.RebuildShipMenu(obj)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_shim.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_shim.py
git commit -m "$(cat <<'EOF'
target_menu: RebuildShipMenu + RebuildShipMenus (subsystem iteration)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: SDK integration tests (CreateTargetList + CycleTarget)

**Files:**
- Create: `tests/integration/test_target_list_sdk_integration.py`

End-to-end check that real SDK code runs against the shim without
crashing. Two scenarios: the bridge-load `CreateTargetList` factory
and the `CycleTarget` cycling loop.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_target_list_sdk_integration.py
"""Load real SDK scripts against the target_menu shim."""
import App
from engine.appc.ships import ShipClass


def test_sdk_create_target_list_constructs_singleton():
    App._reset_target_menu_singleton()
    import Bridge.TacticalMenuHandlers as TMH
    pTacticalWindow = App.TacticalControlWindow_GetTacticalControlWindow()

    pPane = TMH.CreateTargetList(pTacticalWindow)

    assert pPane is not None
    assert isinstance(App.STTargetMenu_GetTargetMenu(), App.STTargetMenu)


def _populate_target_menu(target_menu, names):
    ships = []
    for n in names:
        ship = ShipClass(); ship.SetName(n)
        target_menu.AddChild(App.STSubsystemMenu(ship, n))
        ships.append(ship)
    return ships


def test_sdk_cycle_target_walks_visible_ships():
    from engine.core.game import Game, Episode, Mission, _set_current_game

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    ships = _populate_target_menu(target_menu, ["A", "B", "C"])

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)

    try:
        import TacticalInterfaceHandlers as TIH
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[1]
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[2]
        TIH.CycleTarget(1)  # wrap
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(0)  # reverse
        assert player.GetTarget() is ships[2]
    finally:
        _set_current_game(None)


def test_sdk_cycle_target_skips_invisible():
    from engine.core.game import Game, Episode, Mission, _set_current_game

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    ships = _populate_target_menu(target_menu, ["A", "B", "C"])
    target_menu.GetObjectEntry(ships[1]).SetNotVisible()

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)

    try:
        import TacticalInterfaceHandlers as TIH
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(1)
        # B hidden → skip to C.
        assert player.GetTarget() is ships[2]
    finally:
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it passes (or surfaces a gap)**

Run: `uv run pytest tests/integration/test_target_list_sdk_integration.py -v`
Expected: 3 passed.

**If FAIL**: read the traceback to find the missing shim surface.
Likely causes and fixes:
- `ShipClass.SetTarget not storing properly` → check `engine/appc/ships.py`; SetTarget should find the named ship in the bridge set and store the reference. Add the bridge-set lookup if missing.
- `_SDKFinder cannot find Bridge.TacticalMenuHandlers` → verify the import path; `tests/conftest.py:329` should already install it.
- `App.TacticalControlWindow_GetTacticalControlWindow().SetTargetMenu()` raises → the NamedStub fallback should absorb arbitrary method calls; if not, check `App.py:479`.

Fix the gap in the relevant shim, add a focused unit test covering it, and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_target_list_sdk_integration.py engine/
git commit -m "$(cat <<'EOF'
target_list: integration tests against real SDK scripts

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Panel abstract base class

**Files:**
- Create: `engine/ui/panel.py`
- Create: `tests/unit/test_panel.py`

The base class establishes the contract all CEF-rendered panels honour:
- `name` (string, used as the event-routing prefix)
- `visible` (bool, panel may render markup but be hidden via CSS)
- `render_payload()` → optional JS string, or `None` if nothing changed
- `dispatch_event(action)` → bool, True if the panel handled the event

Pause menu predates this and intentionally does not subclass — it stays
as the existing implementation; the framework only needs to coexist with it.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_panel.py
"""Unit tests for the abstract panel base."""
import pytest


def test_panel_subclass_must_implement_render_payload():
    from engine.ui.panel import Panel

    class Bad(Panel):
        @property
        def name(self):
            return "bad"

    with pytest.raises(TypeError):
        Bad()  # render_payload + dispatch_event still abstract


def test_panel_subclass_minimal_implementation():
    from engine.ui.panel import Panel

    class Minimal(Panel):
        @property
        def name(self):
            return "minimal"
        def render_payload(self):
            return None
        def dispatch_event(self, action):
            return False

    p = Minimal()
    assert p.name == "minimal"
    assert p.visible is True
    p.visible = False
    assert p.visible is False
    assert p.render_payload() is None
    assert p.dispatch_event("foo") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.panel'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/ui/panel.py
"""Abstract base class for CEF-rendered UI panels.

Every Panel has:
  - ``name`` — string identifier used as the event-routing prefix in
    the JS→Python channel (e.g. clicking a row in the "target" panel
    fires `dauntlessEvent('target/USS Enterprise')`, which the
    PanelRegistry routes to the panel whose ``name`` is "target").
  - ``visible`` — Python-side flag. The host loop maps this to a CSS
    class toggle in the corresponding HTML container.
  - ``render_payload()`` — return a JS snippet to execute in CEF, or
    ``None`` if nothing has changed since the last call. Idempotency
    is the contract (matches PauseMenuModel.render_payload pattern).
  - ``dispatch_event(action)`` — return True if the action was handled.

PauseMenuModel predates this base class and is intentionally not a
Panel subclass — the registry treats unprefixed events as legacy and
falls back to the pause menu's existing dispatch.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Panel(ABC):
    def __init__(self):
        self._visible: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Routing prefix; lower-case, no slashes."""

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = bool(value)

    @abstractmethod
    def render_payload(self) -> Optional[str]:
        """Return JS to execute, or None if no change since last call."""

    @abstractmethod
    def dispatch_event(self, action: str) -> bool:
        """Handle a JS-originated event. Return True if handled."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_panel.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/panel.py tests/unit/test_panel.py
git commit -m "$(cat <<'EOF'
ui/panel: abstract base class for CEF-rendered panels

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: PanelRegistry with prefix routing + legacy fallback

**Files:**
- Create: `engine/ui/panel_registry.py`
- Create: `tests/unit/test_panel_registry.py`

The registry holds N panels. Each tick the host loop calls
`render_all()` to gather JS snippets; the registry's `dispatch()` method
is set as the single CEF event handler. Slash-prefixed events
(`target/...`) route to the matching panel; unprefixed events fall
through to a legacy handler (pause menu).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_panel_registry.py
from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry


class _RecordingPanel(Panel):
    """Test fixture — records render and dispatch calls."""

    def __init__(self, name, payload="setX();"):
        super().__init__()
        self._name = name
        self._payload = payload
        self.dispatched = []
        self.render_calls = 0

    @property
    def name(self):
        return self._name

    def render_payload(self):
        self.render_calls += 1
        return self._payload

    def dispatch_event(self, action):
        self.dispatched.append(action)
        return True


def test_registry_collects_render_payloads_from_all_panels():
    a = _RecordingPanel("a", "setA();")
    b = _RecordingPanel("b", "setB();")
    reg = PanelRegistry()
    reg.register(a)
    reg.register(b)

    payloads = reg.render_all()

    assert "setA();" in payloads
    assert "setB();" in payloads


def test_registry_skips_panels_returning_none():
    a = _RecordingPanel("a", None)
    b = _RecordingPanel("b", "setB();")
    reg = PanelRegistry()
    reg.register(a); reg.register(b)
    payloads = reg.render_all()
    assert payloads == ["setB();"]


def test_registry_dispatch_routes_by_slash_prefix():
    a = _RecordingPanel("target")
    b = _RecordingPanel("other")
    reg = PanelRegistry()
    reg.register(a); reg.register(b)

    handled = reg.dispatch("target/USS Enterprise")

    assert handled is True
    assert a.dispatched == ["USS Enterprise"]
    assert b.dispatched == []


def test_registry_dispatch_falls_through_to_legacy_handler():
    """Unprefixed events route to the legacy handler (pause menu)."""
    a = _RecordingPanel("target")
    legacy_calls = []
    reg = PanelRegistry(legacy_handler=legacy_calls.append)
    reg.register(a)

    reg.dispatch("exit")

    assert a.dispatched == []
    assert legacy_calls == ["exit"]


def test_registry_dispatch_returns_false_when_unknown_and_no_legacy():
    reg = PanelRegistry()
    assert reg.dispatch("nobody/action") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_panel_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.panel_registry'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/ui/panel_registry.py
"""Coordinates CEF-rendered panels — render pump + event dispatch.

The host loop owns one PanelRegistry instance. Each tick:
  scripts = registry.render_all()
  for s in scripts: _h.cef_execute_javascript(s)

The registry's dispatch() is wired as the single CEF event handler;
slash-prefixed events route to the matching panel (`target/USS X` →
panel "target", action "USS X"), unprefixed events fall through to the
optional legacy handler (used for the pre-framework pause menu).
"""
from __future__ import annotations

from typing import Callable, List, Optional

from engine.ui.panel import Panel


class PanelRegistry:
    def __init__(self, legacy_handler: Optional[Callable[[str], None]] = None):
        self._panels: List[Panel] = []
        self._legacy = legacy_handler

    def register(self, panel: Panel) -> None:
        if any(p.name == panel.name for p in self._panels):
            raise ValueError("duplicate panel name: " + panel.name)
        self._panels.append(panel)

    def render_all(self) -> List[str]:
        out: List[str] = []
        for p in self._panels:
            payload = p.render_payload()
            if payload is not None:
                out.append(payload)
        return out

    def dispatch(self, event_name: str) -> bool:
        """Route a JS event to the right panel.

        Slash-prefixed: ``"target/USS Enterprise"`` → panel "target",
        action "USS Enterprise". Unprefixed: routed to the legacy
        handler if one was provided. Returns True if any handler ran.
        """
        if "/" in event_name:
            prefix, _, action = event_name.partition("/")
            for p in self._panels:
                if p.name == prefix:
                    return p.dispatch_event(action)
            return False
        if self._legacy is not None:
            self._legacy(event_name)
            return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_panel_registry.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/panel_registry.py tests/unit/test_panel_registry.py
git commit -m "$(cat <<'EOF'
ui/panel_registry: prefix routing + legacy fallback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: TargetListView Python panel

**Files:**
- Create: `engine/ui/target_list_view.py`
- Create: `tests/unit/test_target_list_view.py`

The view reads `STTargetMenu_GetTargetMenu()` each tick and produces an
idempotent JSON payload describing the rows. Click events (action =
ship name) call `pPlayer.SetTarget(name)`.

State shape sent to JS:
```json
{
  "visible": true,
  "selected": "USS Enterprise",   // or null
  "rows": [
    {"name": "USS Enterprise", "affiliation": "FRIENDLY"},
    {"name": "IKS Kor",         "affiliation": "ENEMY"}
  ]
}
```

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_target_list_view.py
import json
import App
from engine.appc.ships import ShipClass


def _setup_game_with_player():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def test_view_payload_lists_rows_with_affiliations():
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        mission.GetFriendlyGroup().AddName("Dauntless")
        mission.GetEnemyGroup().AddName("Kor")

        a = ShipClass(); a.SetName("Dauntless")
        b = ShipClass(); b.SetName("Kor")
        target_menu.RebuildShipMenu(a)
        target_menu.RebuildShipMenu(b)
        target_menu.ResetAffiliationColors()

        view = TargetListView()
        script = view.render_payload()
        assert script is not None
        # Payload is `setTargetList({...});`
        assert script.startswith("setTargetList(")
        # Extract the JSON between parens to verify shape.
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        assert state["visible"] is True
        names = [r["name"] for r in state["rows"]]
        assert names == ["Dauntless", "Kor"]
        affiliations = [r["affiliation"] for r in state["rows"]]
        assert affiliations == ["FRIENDLY", "ENEMY"]
        assert state["selected"] is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_payload_is_idempotent_until_state_changes():
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    _setup_game_with_player()
    try:
        view = TargetListView()
        first = view.render_payload()
        assert first is not None
        # Nothing changed — must return None.
        assert view.render_payload() is None

        # A row added → next call re-emits.
        a = ShipClass(); a.SetName("X")
        target_menu.RebuildShipMenu(a)
        assert view.render_payload() is not None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_dispatch_event_sets_player_target():
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        a = ShipClass(); a.SetName("Dauntless")
        target_menu.RebuildShipMenu(a)
        bridge = App.g_kSetManager.GetSet("bridge")
        bridge.AddObjectToSet(a, "Dauntless")

        view = TargetListView()
        handled = view.dispatch_event("Dauntless")
        assert handled is True
        assert player.GetTarget() is a
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.target_list_view'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/ui/target_list_view.py
"""CEF view for the target list panel.

Reads the STTargetMenu singleton each tick, builds a state dict, and
emits a `setTargetList({...})` JS call. Idempotent — only re-emits
when the state snapshot changes from the previous call.

Click events from JS (action = ship name) translate to
``pPlayer.SetTarget(name)``, which fires ET_SET_TARGET and
ET_TARGET_WAS_CHANGED via the engine's existing event machinery.

Plan: docs/superpowers/plans/2026-05-25-target-list-shim.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class TargetListView(Panel):
    @property
    def name(self) -> str:
        return "target"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        import App
        target_menu = App.STTargetMenu_GetTargetMenu()
        if target_menu is None:
            return (self._visible, None, ())
        from engine.appc.target_menu import STSubsystemMenu
        rows = []
        for child in target_menu._children:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                rows.append((ship.GetName(), child.GetAffiliation(), child.IsVisible()))
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        selected = None
        if game is not None:
            player = game.GetPlayer()
            if player is not None and player.GetTarget() is not None:
                selected = player.GetTarget().GetName()
        return (self._visible, selected, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, selected, rows = snapshot
        payload = {
            "visible": visible,
            "selected": selected,
            "rows": [
                {"name": name, "affiliation": aff}
                for (name, aff, is_vis) in rows
                if is_vis
            ],
        }
        return "setTargetList(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        """Action is the ship name (verbatim from the JS row data attr)."""
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        if game is None:
            return False
        player = game.GetPlayer()
        if player is None:
            return False
        player.SetTarget(action)
        return True

    def invalidate(self) -> None:
        """Force the next render_payload to re-emit."""
        self._last_snapshot = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_list_view.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_list_view.py tests/unit/test_target_list_view.py
git commit -m "$(cat <<'EOF'
ui/target_list_view: Python panel reads shim singleton, emits CEF state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: CSS for target list panel

**Files:**
- Create: `native/assets/ui-cef/css/target_list.css`

LCARS-inspired styling matching `docs/ui_designs/02-tactical-cluster.html`.
Uses the palette tokens from `docs/ui_designs/SDK_UI_API.md §1`. Panel
positioned upper-left, anchored to screen edge with 24 px inset.

- [ ] **Step 1: Create the CSS file**

```css
/* native/assets/ui-cef/css/target_list.css
 *
 * LCARS chrome for the target list panel.
 * Spec: docs/ui_designs/02-tactical-cluster.html + SDK_UI_API.md §1.
 */

:root {
    --bc-menu1-base: rgb(216, 94, 86);
    --bc-menu1-accent: rgb(216, 132, 80);
    --bc-radar-friendly: rgb(80, 112, 230);
    --bc-radar-enemy: rgb(216, 43, 43);
    --bc-radar-neutral: rgb(255, 255, 175);
    --bc-radar-unknown: rgb(128, 128, 128);
    --bc-chosen-gold: rgb(255, 210, 90);
    --bc-label-text: rgb(235, 225, 255);
    --bc-body-bg: rgba(10, 10, 16, 0.85);
}

#target-list-panel {
    position: absolute;
    top: 24px;
    left: 24px;
    width: 280px;
    font-family: "Antonio", "Antonio-Regular", sans-serif;
    font-weight: 600;
    color: var(--bc-label-text);
    pointer-events: auto;
}

#target-list-panel.target-list--hidden {
    display: none;
}

.target-list__header {
    background: linear-gradient(90deg, var(--bc-menu1-base), var(--bc-menu1-accent));
    color: rgb(0, 0, 0);
    padding: 6px 14px 6px 18px;
    border-top-right-radius: 14px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 14px;
}

.target-list__body {
    background: var(--bc-body-bg);
    border-left: 4px solid var(--bc-menu1-base);
    padding: 8px 0;
}

.target-list__row {
    display: flex;
    align-items: center;
    padding: 6px 12px;
    cursor: pointer;
    border-left: 3px solid transparent;
}

.target-list__row:hover {
    background: rgba(216, 94, 86, 0.15);
}

.target-list__row--chosen {
    background: rgba(255, 210, 90, 0.18);
    border-left-color: var(--bc-chosen-gold);
}

.target-list__row--chosen .target-list__caret {
    color: var(--bc-chosen-gold);
}

.target-list__caret {
    margin-right: 8px;
    font-size: 14px;
    line-height: 1;
}

.target-list__row--FRIENDLY .target-list__caret { color: var(--bc-radar-friendly); }
.target-list__row--ENEMY    .target-list__caret { color: var(--bc-radar-enemy); }
.target-list__row--NEUTRAL  .target-list__caret { color: var(--bc-radar-neutral); }
.target-list__row--UNKNOWN  .target-list__caret { color: var(--bc-radar-unknown); }

.target-list__name {
    font-size: 13px;
    letter-spacing: 0.04em;
}
```

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui-cef/css/target_list.css
git commit -m "$(cat <<'EOF'
ui-cef: LCARS CSS for target list panel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: target_list.js render function

**Files:**
- Create: `native/assets/ui-cef/js/target_list.js`

Mirrors the pause_menu.js pattern — define a single global render
function that consumes the state payload and rebuilds the DOM.

- [ ] **Step 1: Create the JS file**

```js
// native/assets/ui-cef/js/target_list.js
//
// Target-list render fn. Driven by Python via cef_execute_javascript:
//   setTargetList({visible: true, selected: "USS X", rows: [{name, affiliation}, ...]});
//
// Click on a row emits `dauntlessEvent('target/<ship name>')`; the
// PanelRegistry routes it to TargetListView.dispatch_event(ship name).
// Spec: docs/ui_designs/02-tactical-cluster.md

function setTargetList(state) {
    const panel = document.getElementById('target-list-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('target-list--hidden');
        return;
    }
    panel.classList.remove('target-list--hidden');

    const body = document.getElementById('target-list-body');
    if (!body) return;

    const rows = state.rows || [];
    const selected = state.selected || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        // dauntlessEvent uses console.info channel — same as pause menu.
        const safe = name.replace(/'/g, "\\'");
        html += '<div class="target-list__row target-list__row--' + aff + chosen + '"'
              +   ' onclick="dauntlessEvent(\'target/' + safe + '\')">'
              +   '<span class="target-list__caret">&#9656;</span>'
              +   '<span class="target-list__name">' + name + '</span>'
              + '</div>';
    }
    body.innerHTML = html;
}
```

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui-cef/js/target_list.js
git commit -m "$(cat <<'EOF'
ui-cef: setTargetList JS render fn

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Add target list markup to hello.html

**Files:**
- Modify: `native/assets/ui-cef/hello.html`

Add the CSS link, the script tag, and the panel container.

- [ ] **Step 1: Read the current hello.html**

Run: `cat native/assets/ui-cef/hello.html`

- [ ] **Step 2: Modify hello.html**

In the `<head>` block, after the existing `<link rel="stylesheet" href="css/hello.css">`, add:

```html
    <link rel="stylesheet" href="css/target_list.css">
```

In the `<body>` block, after the closing `</div>` of `#pause-menu` and BEFORE the `<script src="js/pause_menu.js">` tag, add:

```html
    <!-- Target list panel.
         State pushed via setTargetList({visible, selected, rows});
         row clicks fire dauntlessEvent('target/<ship>'); PanelRegistry
         routes to TargetListView.dispatch_event in Python.
         Spec: docs/ui_designs/02-tactical-cluster.md -->
    <div id="target-list-panel" class="target-list--hidden">
        <div class="target-list__header">Targets</div>
        <div class="target-list__body" id="target-list-body"></div>
    </div>
```

After `<script src="js/pause_menu.js"></script>`, add:

```html
    <script src="js/target_list.js"></script>
```

- [ ] **Step 3: Verify the change**

Run: `grep -n "target-list" native/assets/ui-cef/hello.html`
Expected: 4 matches — link, panel div, header, body div, script tag (some may share lines).

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/hello.html
git commit -m "$(cat <<'EOF'
ui-cef: add target-list panel container to hello.html

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Wire PanelRegistry into host_loop

**Files:**
- Modify: `engine/host_loop.py`

Construct the registry at startup, register `TargetListView`, and wire
its `dispatch` as the single CEF event handler (with the existing
`pause_menu.dispatch_event` as the legacy fallback). Pump
`render_all()` every tick. Forward mouse to CEF whenever any non-pause
panel needs interaction — for Phase 1 this is simply "always while not
paused" (the target list is the only non-pause panel, and it's
always visible).

- [ ] **Step 1: Inspect the existing wiring**

Run:
```bash
grep -n "_cef_set_event_handler\|cef_execute_javascript\|pause_menu" engine/host_loop.py | head -20
```

Confirm the lines you'll be modifying — likely around 1975-2050 based
on the prior survey. The key edits:
1. Construct `PanelRegistry(legacy_handler=pause_menu.dispatch_event)`
2. Register `TargetListView()`
3. Change `_cef_set_event_handler(pause_menu.dispatch_event)` → `_cef_set_event_handler(registry.dispatch)`
4. Add a per-tick block that calls `registry.render_all()` and pushes each script via `_h.cef_execute_javascript(...)`. This runs **unconditionally** (paused or not), because the target list is visible during normal gameplay.
5. Add mouse-forwarding to CEF when not paused (so target-list rows are clickable).

- [ ] **Step 2: Modify host_loop.py**

Add imports near the top of the function that builds the pause menu (the existing pattern uses an in-function import — match it):

```python
        from engine.ui.panel_registry import PanelRegistry
        from engine.ui.target_list_view import TargetListView
```

After `pause_menu = default_pause_menu(...)` (around line 1976), add:

```python
        registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)
        target_list_view = TargetListView()
        registry.register(target_list_view)
```

Change the line:

```python
            _cef_set_event_handler(pause_menu.dispatch_event)
```

to:

```python
            _cef_set_event_handler(registry.dispatch)
```

In the main loop body, after the existing `pause.apply(_h)` and side-effect calls, add an UNCONDITIONAL panel-pump block (placed AFTER the `if pause.is_open: ... else: ...` block):

```python
            # Pump all CEF panels (target list, etc.) every tick. The
            # registry returns only payloads whose state changed since
            # the last call, so this is cheap when nothing's moving.
            if _h is not None:
                for _panel_script in registry.render_all():
                    _h.cef_execute_javascript(_panel_script)

                # Forward mouse to CEF outside the pause overlay so
                # non-pause panels (target list) are clickable. The
                # pause-open branch above already forwards mouse for
                # the pause menu's own clicks; here we cover the
                # unpaused path. cursor_pos returns framebuffer pixels;
                # convert to CEF view space (same scaling as the paused
                # branch).
                if not pause.is_open and _cef_send_mouse_move is not None:
                    _mx_fb, _my_fb = _h.cursor_pos()
                    _fb_w, _fb_h = _h.framebuffer_size()
                    _sx = (_CEF_VIEW_W / _fb_w) if _fb_w > 0 else 1.0
                    _sy = (_CEF_VIEW_H / _fb_h) if _fb_h > 0 else 1.0
                    _mx = int(_mx_fb * _sx)
                    _my = int(_my_fb * _sy)
                    _cef_send_mouse_move(_mx, _my)
                    if _cef_send_mouse_click is not None:
                        if _h.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if _h.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)
```

- [ ] **Step 3: Verify the changes build and tests still pass**

Build native: `cmake --build build -j`
Run tests: `uv run pytest -q`
Expected: all tests pass; native build clean.

If the bindings don't expose `_cef_send_mouse_move` (older builds), the
existing `_cef_send_mouse_move is not None` guard already covers it
— the panel just won't be clickable on those builds.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
host_loop: wire PanelRegistry; pump target list every tick

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Inject demo ships at startup + run it

**Files:**
- Modify: `engine/host_loop.py`

Until engine auto-population lands, the target list will be empty
because nothing populates the bridge set. Inject three demo ships at
startup so the panel is non-empty at launch and we can verify it
visually.

- [ ] **Step 1: Add the demo-ship injection**

In `engine/host_loop.py`, near where `registry.register(target_list_view)` was added, also add:

```python
        # ── Demo ships for Phase 1 of the target list ─────────────────
        # Engine auto-population (bridge-set add/remove hooks) is a
        # Phase 2 follow-up. Until then, seed the target list with
        # three named ships across affiliations so the panel is
        # populated at launch and we can verify the rendering pipe.
        # Remove this block once the engine drives the list directly.
        import App as _App
        _App._reset_target_menu_singleton()
        _target_menu = _App.STTargetMenu_CreateW("Targets")
        from engine.core.game import Mission, Episode, Game, _set_current_game
        from engine.appc.ships import ShipClass as _ShipClass
        _demo_mission = Mission()
        _demo_episode = Episode(); _demo_episode.SetCurrentMission(_demo_mission)
        _demo_game = Game(); _demo_game.SetCurrentEpisode(_demo_episode)
        _set_current_game(_demo_game)
        _demo_mission.GetFriendlyGroup().AddName("USS Dauntless")
        _demo_mission.GetEnemyGroup().AddName("IKS Kor")
        _demo_mission.GetNeutralGroup().AddName("Trader")
        _demo_bridge = _App.g_kSetManager.GetSet("bridge")
        for _name in ("USS Dauntless", "IKS Kor", "Trader"):
            _s = _ShipClass(); _s.SetName(_name)
            _demo_bridge.AddObjectToSet(_s, _name)
            _target_menu.RebuildShipMenu(_s)
        _target_menu.ResetAffiliationColors()
        # Player ship — referenced by TargetListView.dispatch_event.
        _demo_player = _ShipClass(); _demo_player.SetName("Player")
        _demo_game.SetPlayer(_demo_player)
```

This block is bracketed by comments calling out its temporary nature so
the future cleanup is obvious.

- [ ] **Step 2: Build and launch**

Build:
```bash
cmake --build build -j
```

Run:
```bash
./build/dauntless
```

**Expected behaviour:**
- 3D scene renders normally.
- Upper-left corner shows the target list panel with three rows:
  - "USS Dauntless" with a blue (friendly) caret.
  - "IKS Kor" with a red (enemy) caret.
  - "Trader" with a pale-yellow (neutral) caret.
- Clicking a row tints it gold (chosen state).
- ESC opens the pause menu — still works (legacy fallback path).

**Troubleshooting:**
- Panel not visible: check the browser devtools (F12 via the existing
  `toggle_devtools` keybind). Verify `#target-list-panel` exists in DOM
  and doesn't have the `target-list--hidden` class.
- Panel empty: confirm `setTargetList` is being called — add a
  `console.log(state)` at the top of the JS render fn and watch the
  devtools console.
- Click does nothing: verify the dauntless-event channel — the JS
  emits `console.info('dauntless-event:target/...')`; the C++
  `OnConsoleMessage` parses it; Python's `registry.dispatch` should
  route it. Set a Python breakpoint in `TargetListView.dispatch_event`
  to confirm.

- [ ] **Step 3: Verify clicking changes the chosen state**

Click "IKS Kor". On the next tick the JS receives a state with
`selected: "IKS Kor"`. The "IKS Kor" row should now have the
`target-list__row--chosen` class — gold left border, gold caret.

Click "Trader". Selection updates.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
host_loop: seed target list with demo ships for Phase 1 visibility

Removed once engine auto-population (bridge-set hooks) lands.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Update docs/ui_designs/SDK_UI_API.md events table

**Files:**
- Modify: `docs/ui_designs/SDK_UI_API.md` (§3 events table)

The current table lists a fictional `ET_TARGET_SELECTED = 5`. The SDK
actually uses `ET_SET_TARGET` (player-directed) and
`ET_TARGET_WAS_CHANGED` (broadcast), fired by `pPlayer.SetTarget(name)`.

- [ ] **Step 1: Find the table**

Run: `grep -n "ET_TARGET_SELECTED\|## 3\." docs/ui_designs/SDK_UI_API.md`

- [ ] **Step 2: Look up the actual integer values**

Run: `grep -n "^ET_SET_TARGET\b\|^ET_TARGET_WAS_CHANGED\b" sdk/Build/scripts/App.py`

Expected output (paths from your earlier exploration):
```
sdk/Build/scripts/App.py:12922:ET_TARGET_WAS_CHANGED = Appc.ET_TARGET_WAS_CHANGED
sdk/Build/scripts/App.py:13059:ET_SET_TARGET = Appc.ET_SET_TARGET
```

The integer values are inside `Appc`. For the doc, the exact numeric
value matters less than naming the constants correctly — use
"(C++ enum)" as the value column entry rather than guessing a number.

- [ ] **Step 3: Edit the file**

In `docs/ui_designs/SDK_UI_API.md`, replace this row in §3:

```markdown
| `ET_TARGET_SELECTED` | 5 | Target list selection change |
```

with:

```markdown
| `ET_SET_TARGET` | (C++ enum) | Player chose a target — destination event sent to the player ship. Target-list row clicks call `pPlayer.SetTarget(name)` which fires this. |
| `ET_TARGET_WAS_CHANGED` | (C++ enum) | Broadcast — fires after `ET_SET_TARGET` so UI panels (TacticalMenuHandlers.TargetChanged et al.) can react. |
```

Immediately after the table, add this note:

```markdown
> The SDK does NOT define `ET_TARGET_SELECTED`. Target-list row clicks
> route through `pPlayer.SetTarget(ship_name)` which fires the two
> events above. Earlier drafts of this document listed
> `ET_TARGET_SELECTED = 5`; this has been corrected.
```

- [ ] **Step 4: Commit**

```bash
git add docs/ui_designs/SDK_UI_API.md
git commit -m "$(cat <<'EOF'
ui_designs: correct target-list event names

Removed fictional ET_TARGET_SELECTED = 5. Real SDK events are
ET_SET_TARGET (player-directed) and ET_TARGET_WAS_CHANGED (broadcast),
both fired by pPlayer.SetTarget(name).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes (for the executor)

After Task 14 you have a visible target list. After Task 15 the docs match the implementation. Final sanity checks:

```bash
uv run pytest -q                  # all tests pass
cmake --build build -j            # native builds clean
./build/dauntless                 # target list panel visible, 3 demo rows
```

A useful smoke test after every task: `uv run pytest tests/unit/test_target_menu_shim.py tests/unit/test_panel.py tests/unit/test_panel_registry.py tests/unit/test_target_list_view.py tests/integration/test_target_list_sdk_integration.py -v` — the cumulative suite for this plan.

## Deferred to follow-up plans

These remain explicitly out of scope; surface them when this plan is done so the next round of brainstorming can pick them up:

1. **Engine auto-population.** Set-manager hook that calls `RebuildShipMenu(ship)` when a ship enters the bridge set, drops the row when it leaves. Affiliation-property-change hook that calls `ResetAffiliationColors()`. These replace the demo-ship block in Task 14.
2. **Sensor visibility integration.** Sensor-subsystem update path that toggles `STSubsystemMenu.SetVisible/SetNotVisible` per row based on sensor range.
3. **Subsystem rows.** Each ship's targetable subsystems shown as expandable children of its `STSubsystemMenu`. Requires reading hardpoint data to know which subsystems exist.
4. **Keyboard cycling.** `T`/`Y` bindings → `App.ET_INPUT_TARGET_NEXT` / `_PREV` → `TacticalInterfaceHandlers.TargetNext`. The shim already supports it; only the host loop's input-event wiring is missing.
5. **Persistent target save/load.** Engine fires `ET_RESTORE_PERSISTENT_TARGET` then `pPlayer.SetTarget(saved_name)` on game load; existing `g_iAutoTargetChange` counter in TacticalMenuHandlers handles the rest.
6. **Subsystem identification.** Engine drives `STSubsystemMenu.ShowUnknownName` / `ShowRealName` based on sensor identification state.
7. **Pause menu refactor.** Migrate `PauseMenuModel` to a `Panel` subclass so the legacy-fallback path in `PanelRegistry` can go away. Low priority; the fallback is fine.
8. **Reticule in 3D scene.** Parked entirely (user decision; separate project).
