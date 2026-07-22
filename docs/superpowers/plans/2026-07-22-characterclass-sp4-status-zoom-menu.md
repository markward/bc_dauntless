# CharacterClass SP4 — StatusMap + PositionZoomTable + MenuState Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `CharacterClass` three faithful owned sub-objects — a keyed 0..5 `StatusMap` (rendered as a CEF crew tooltip box driven by the real SDK `*UpdateToolTip` handlers), a `PositionZoomTable` (wired to the bridge camera so an officer's station zoom applies on menu open), and a `MenuState` — completing the SP1-SP4 reimplementation.

**Architecture:** Own + consolidate (same as SP2/SP3). Each sub-object is a small pure-Python class in its own file; `CharacterClass` constructs and delegates to them. Visibility lives in the host loop / CEF, reached through seams (never importing the host loop at module load). The absent native surfaces — the tooltip box + its `UpdateToolTip` dispatch, and the per-officer zoom factor — are reconstructed in Python; the zoom-to-officer camera machinery already exists and only needs a per-officer factor.

**Tech Stack:** Python 3 (`engine/appc`, `engine/ui`), pytest, CEF UI (HTML/JS/CSS in `native/assets/ui-cef/`), the `Panel`/`PanelRegistry` render pipeline.

## Global Constraints

- **Tier-0 source of truth:** `docs/engine/characterclass-reference.md` §4.4 (position-zoom), §4.6 (status), §4.12 (context menu). SDK (`sdk/Build/scripts/`) is ground truth for call shapes.
- **Tests patch `host_io._h`; never call `_dauntless_host` directly.** Pure sub-objects need no host at all.
- **Twin SDK stub lists:** if runtime needs a whole SDK module importable, fix BOTH `tools/mission_harness.py` AND `tests/conftest.py`. Never unstub a whole module to reach one function.
- **Gate:** `scripts/check_tests.sh` (pytest + ctest), NOT `run_tests.sh`. One baselined emitters flake in `tests/known_failures.txt` is pre-existing/unrelated.
- **Check the stub heatmap** (`docs/stub_heatmap.md`) before asserting any `SetStatus`/zoom-read no-op.
- **Shared checkout:** explicit-pathspec `git add` only. NEVER `git add -A`/`.`, `git checkout --`, `git restore`, `git stash`, `git reset --hard`, `git clean`.
- **Visual language:** the tooltip box reuses the shared `.bc-panel` header/body chrome (`css/global.css` + `css/crew_menus.css` tokens). No new palette.
- **CharacterClass stays renderer-free.** It reaches the camera/UI only through `None`-guarded seams, exactly like `bridge_character_anim` / `crew_menu_panel`.
- End every commit message with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## File Structure

**Create:**
- `engine/appc/character_status_map.py` — `StatusMap` (pure keyed 0..5 store).
- `engine/appc/character_position_zoom.py` — `PositionZoomTable` (pure per-name table) + `POSITION_ZOOM_SENTINEL`.
- `engine/appc/character_menu_state.py` — `MenuState` (menu id + ready-flag).
- `engine/ui/character_tooltip_panel.py` — `CharacterTooltipPanel(Panel)`.
- `native/assets/ui-cef/js/character_tooltip.js` — `setCharacterTooltip(payload)`.
- `native/assets/ui-cef/css/character_tooltip.css` — layout only (placement + stacked rows).
- Tests: `tests/appc/test_character_status_map.py`, `tests/appc/test_character_position_zoom.py`, `tests/appc/test_character_menu_state.py`, `tests/ui/test_character_tooltip_panel.py`, `tests/appc/test_character_tooltip_dispatch.py`, `tests/appc/test_position_zoom_camera.py`.

**Modify:**
- `engine/appc/characters.py` — construct + delegate to the three sub-objects; tooltip-owner statics; `DropCharacterToolTips`; `GetCharacterFromMenu`; camera-zoom seam on MenuUp/MenuDown.
- `engine/ui/crew_menu_hotkeys.py` — add `station_name_for(officer)` helper.
- `engine/host_loop.py` — register `CharacterTooltipPanel`; add the tooltip owner-selection + `UpdateToolTip` dispatcher tick; make `_BridgeCamera.set_zoom_target` accept a per-officer zoom factor; feed `GetPositionZoom` in the zoom-focus path.
- `native/assets/ui-cef/index.html` — add the css `<link>`, js `<script>`, and `#character-tooltip-host` div.

---

## Task 1: StatusMap — keyed 0..5 status store

**Files:**
- Create: `engine/appc/character_status_map.py`
- Test: `tests/appc/test_character_status_map.py`
- Modify: `engine/appc/characters.py` (construct + delegate; remove SP1 single-slot `_status`)

**Interfaces:**
- Produces: `StatusMap(owner)` with `set_status(value, key=0)`, `get_status(key) -> value|0`, `clear_status(key)`, `rows() -> list[(int, value)]` (ascending key), `is_dirty() -> bool`, `clear_dirty()`.
- `CharacterClass.SetStatus(value, key=0)`, `GetStatus(key)`, `ClearStatus(key=None)` delegate to `self._status_map`.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/test_character_status_map.py
from engine.appc.character_status_map import StatusMap


def test_keys_0_to_5_store_and_read():
    sm = StatusMap(owner=None)
    sm.set_status("Waiting")            # default key 0
    sm.set_status("Red Alert", 1)
    assert sm.get_status(0) == "Waiting"
    assert sm.get_status(1) == "Red Alert"


def test_key_above_5_is_rejected():
    sm = StatusMap(owner=None)
    sm.set_status("nope", 6)
    assert sm.get_status(6) == 0          # BC: key>5 returns, nothing stored


def test_miss_returns_zero_sentinel():
    sm = StatusMap(owner=None)
    assert sm.get_status(3) == 0          # BC GetStatus miss -> 0


def test_clear_removes_one_row():
    sm = StatusMap(owner=None)
    sm.set_status("Destination : X", 3)
    sm.clear_status(3)
    assert sm.get_status(3) == 0


def test_rows_ascending_key_order():
    sm = StatusMap(owner=None)
    sm.set_status("loc", 2)
    sm.set_status("speed", 1)
    sm.set_status("general", 0)
    assert sm.rows() == [(0, "general"), (1, "speed"), (2, "loc")]


def test_dirty_flag_lifecycle():
    sm = StatusMap(owner=None)
    sm.clear_dirty()
    assert sm.is_dirty() is False
    sm.set_status("x", 0)
    assert sm.is_dirty() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_character_status_map.py -v`
Expected: FAIL with `ModuleNotFoundError: engine.appc.character_status_map`

- [ ] **Step 3: Write the minimal implementation**

```python
# engine/appc/character_status_map.py
"""StatusMap -- CharacterClass's owned keyed status store (tier-0 reference sec 4.6).

BC's status system is a hash keyed 0..5 (struct +0xd8), each key holding one
tooltip-row display string; SetStatus(value, key) with key>5 is a no-op, GetStatus
misses return 0, ClearStatus removes one key's row. Replaces SP1's single
_status["text"] collapse. The status/tooltip UI (m_pStatusUI, +0xd4) is a separate
render concern wired by the CEF CharacterTooltipPanel; this class is pure data.
"""
from __future__ import annotations


class StatusMap:
    MAX_KEY = 5

    def __init__(self, owner):
        self._owner = owner
        self._rows: dict[int, object] = {}
        self._dirty = True

    def set_status(self, value, key=0) -> None:
        k = int(key)
        if k < 0 or k > self.MAX_KEY:      # BC 0x00669D10: key>5 -> return
            return
        self._rows[k] = value
        self._dirty = True

    def get_status(self, key):
        return self._rows.get(int(key), 0)  # BC 0x00669CC0: miss -> 0

    def clear_status(self, key=None) -> None:
        if key is None:
            return
        k = int(key)
        if k in self._rows:                 # BC 0x00669F70: unlink + refresh
            del self._rows[k]
            self._dirty = True

    def rows(self) -> list:
        return [(k, self._rows[k]) for k in sorted(self._rows)]

    def is_dirty(self) -> bool:
        return self._dirty

    def clear_dirty(self) -> None:
        self._dirty = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/appc/test_character_status_map.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Wire `CharacterClass` delegation**

In `engine/appc/characters.py`:

Add the import near the other `engine.appc` imports at top of file:
```python
from engine.appc.character_status_map import StatusMap
```

In `CharacterClass.__init__`, replace the line
```python
        self._status: dict = {}           # tooltip display strings (SP4 -> StatusMap)
```
with
```python
        self._status_map = StatusMap(self)   # SP4: keyed 0..5 status (tier-0 4.6)
```

Replace the SP1 `SetStatus`/`ClearStatus`/`GetStatusText` block (the three methods under the "Tooltip status strings" comment) with:
```python
    # ── Status system: keyed 0..5 StatusMap (tier-0 reference sec 4.6) ───────
    # SetStatus(displayString, key=0); key>5 is a no-op; GetStatus miss -> 0;
    # ClearStatus(key) drops one row. The rows render in the CEF crew tooltip
    # box (CharacterTooltipPanel) via the current-tooltip-owner (Task 4/5).
    def SetStatus(self, value, key=0, *args) -> None:
        self._status_map.set_status(value, key)

    def GetStatus(self, key=0):
        return self._status_map.get_status(key)

    def ClearStatus(self, key=None, *args) -> None:
        self._status_map.clear_status(key)
```

- [ ] **Step 6: Run the full appc suite for regressions**

Run: `uv run pytest tests/appc/ -q`
Expected: PASS (no new failures; any SP1 test asserting `GetStatusText`/`_status["text"]` must be updated to the keyed API in this same commit — grep `tests/` for `GetStatusText` / `_status\[` and fix).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/character_status_map.py tests/appc/test_character_status_map.py engine/appc/characters.py
git commit -m "feat(sp4): keyed 0..5 StatusMap replaces single-slot status

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: PositionZoomTable — per-name zoom/look-at table

**Files:**
- Create: `engine/appc/character_position_zoom.py`
- Test: `tests/appc/test_character_position_zoom.py`
- Modify: `engine/appc/characters.py` (construct + delegate)

**Interfaces:**
- Produces: `POSITION_ZOOM_SENTINEL: float`; `PositionZoomTable()` with `add_position_zoom(name, value, zoom_name="")`, `get_position_zoom(name) -> float` (sentinel on miss), `get_position_look_at_name(name) -> str|None`.
- `CharacterClass.AddPositionZoom/GetPositionZoom/GetPositionLookAtName` delegate to `self._position_zoom`.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/test_character_position_zoom.py
from engine.appc.character_position_zoom import (
    PositionZoomTable, POSITION_ZOOM_SENTINEL,
)


def test_add_and_get_value():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    assert t.get_position_zoom("DBHelm") == 0.45


def test_look_at_name_resolves_and_defaults_none():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    t.add_position_zoom("EBEngineer", 0.5)          # no zoom_name
    assert t.get_position_look_at_name("DBHelm") == "Helm"
    assert t.get_position_look_at_name("EBEngineer") is None


def test_append_only_if_absent():
    t = PositionZoomTable()
    t.add_position_zoom("DBHelm", 0.45, "Helm")
    t.add_position_zoom("DBHelm", 0.99, "Other")     # BC dedupe: ignored
    assert t.get_position_zoom("DBHelm") == 0.45
    assert t.get_position_look_at_name("DBHelm") == "Helm"


def test_miss_returns_sentinel():
    t = PositionZoomTable()
    assert t.get_position_zoom("nope") == POSITION_ZOOM_SENTINEL
    assert t.get_position_look_at_name("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_character_position_zoom.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the minimal implementation**

```python
# engine/appc/character_position_zoom.py
"""PositionZoomTable -- CharacterClass's owned per-station zoom table
(tier-0 reference sec 4.4, struct +0xa8/+0xac, 0x18-byte records).

Each record is (station-name, zoom value, look-at/zoom-target name). BC appends
only if the name is not already present, and GetPositionZoom does a linear search
returning the value or a default sentinel. The bridge camera native-reads this
(no SDK Python caller) to zoom to an officer's station on focus; SP4 wires that
via the MenuUp zoom hook (Task 8).
"""
from __future__ import annotations

# BC returns *0x00888EB4 (a float const) on a GetPositionZoom miss. Its exact
# value was not recoverable from the tier-0/constants sources; 1.0 == "no focus
# zoom" (captain FOV factor) is the documented, behaviourally-safe fallback: a
# miss means "this station has no authored zoom", which the camera treats as no
# zoom. See spec sec 4.1.
POSITION_ZOOM_SENTINEL = 1.0


class PositionZoomTable:
    def __init__(self):
        self._records: list = []   # list[tuple[str, float, str|None]]

    def add_position_zoom(self, name, value, zoom_name="") -> None:
        n = str(name)
        for rn, _v, _la in self._records:
            if rn == n:                        # BC 0x0066C530: append if absent
                return
        self._records.append((n, float(value), str(zoom_name) if zoom_name else None))

    def get_position_zoom(self, name) -> float:
        n = str(name)
        for rn, val, _la in self._records:     # BC 0x0066C690: linear search
            if rn == n:
                return val
        return POSITION_ZOOM_SENTINEL

    def get_position_look_at_name(self, name):
        n = str(name)
        for rn, _val, la in self._records:     # BC 0x0066C720
            if rn == n:
                return la
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/appc/test_character_position_zoom.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Wire `CharacterClass` delegation**

In `engine/appc/characters.py`:

Add import at top:
```python
from engine.appc.character_position_zoom import PositionZoomTable
```

In `__init__`, replace
```python
        self._position_zoom = None    # SP4: PositionZoomTable
```
with
```python
        self._position_zoom = PositionZoomTable()   # SP4: per-station zoom (tier-0 4.4)
```

Add explicit delegators (place near `SetLocation`/`GetLocation`, before the `__getattr__` data-bag so they no longer fall through). The data-bag docstring at the `__getattr__` comment lists `AddPositionZoom/GetPositionZoom` — remove those two names from that comment:
```python
    # ── Position-zoom table (tier-0 reference sec 4.4) ──────────────────────
    def AddPositionZoom(self, name, value, zoom_name="") -> None:
        self._position_zoom.add_position_zoom(name, value, zoom_name)

    def GetPositionZoom(self, name):
        return self._position_zoom.get_position_zoom(name)

    def GetPositionLookAtName(self, name):
        return self._position_zoom.get_position_look_at_name(name)
```

- [ ] **Step 6: Run appc suite**

Run: `uv run pytest tests/appc/ -q`
Expected: PASS (no new failures).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/character_position_zoom.py tests/appc/test_character_position_zoom.py engine/appc/characters.py
git commit -m "feat(sp4): faithful PositionZoomTable replaces data-bag single-slot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: MenuState + GetCharacterFromMenu (consolidation)

**Files:**
- Create: `engine/appc/character_menu_state.py`
- Test: `tests/appc/test_character_menu_state.py`
- Modify: `engine/appc/characters.py` (construct; populate from `SetMenu`; add `GetCharacterFromMenu` static)

**Interfaces:**
- Produces: `MenuState()` with `set_menu(menu)`, `menu_id() -> int` (0 when none), `has_menu() -> bool`, `is_ready() -> bool`.
- `CharacterClass._menu_state` populated in `SetMenu`. New static `CharacterClass_GetCharacterFromMenu(menu_id)`.

**Design note (byte-identical MenuUp):** this task does NOT change `MenuUp`/`MenuDown` control flow — a characterization test proves behaviour is unchanged. `MenuState` tracks id + ready so `GetCharacterFromMenu` (§4.12) can resolve the owning character; `is_ready()` mirrors the existing `menu and menu.IsEnabled()` predicate for future consolidation without rewiring the gate now (avoids a regression risk in shipped menu handling).

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/test_character_menu_state.py
from engine.appc.character_menu_state import MenuState
from engine.appc.characters import (
    CharacterClass, STTopLevelMenu_CreateW, CharacterClass_GetCharacterFromMenu,
)


def test_empty_menu_state():
    ms = MenuState()
    assert ms.has_menu() is False
    assert ms.menu_id() == 0
    assert ms.is_ready() is False


def test_set_menu_tracks_id_and_ready():
    ms = MenuState()
    menu = STTopLevelMenu_CreateW("Helm")
    ms.set_menu(menu)
    assert ms.has_menu() is True
    assert ms.menu_id() == id(menu)
    assert ms.is_ready() is True


def test_set_menu_stamps_menu_state_on_character():
    ch = CharacterClass()
    menu = STTopLevelMenu_CreateW("Helm")
    ch.SetMenu(menu)
    assert ch._menu_state.menu_id() == id(menu)


def test_get_character_from_menu_resolves_owner(monkeypatch):
    ch = CharacterClass()
    ch.SetCharacterName("Helm")
    menu = STTopLevelMenu_CreateW("Helm")
    ch.SetMenu(menu)
    # Resolve against a one-character candidate list.
    found = CharacterClass_GetCharacterFromMenu(id(menu), candidates=[ch])
    assert found is ch
    assert CharacterClass_GetCharacterFromMenu(999999, candidates=[ch]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_character_menu_state.py -v`
Expected: FAIL (`ModuleNotFoundError` / `ImportError: CharacterClass_GetCharacterFromMenu`)

- [ ] **Step 3: Write `MenuState`**

```python
# engine/appc/character_menu_state.py
"""MenuState -- CharacterClass's owned menu-state sub-object (tier-0 reference
sec 4.12, struct +0x14c; menu id at +0x14c, ready-flag byte at +0x28 bit 0x1).

Formalizes SP1's informal _menu handle. Holds the top-level menu handle (the id
source) plus a ready flag. GetCharacterFromMenu (a bridge-set search by menu id)
uses menu_id(). Consolidation only -- MenuUp/MenuDown behaviour is unchanged.
"""
from __future__ import annotations


class MenuState:
    def __init__(self):
        self._menu = None       # STTopLevelMenu handle (id source)
        self._ready = False     # +0x28 bit 0x1

    def set_menu(self, menu) -> None:
        self._menu = menu
        # Ready mirrors the existing MenuUp gate: a real, enabled menu.
        try:
            self._ready = bool(menu) and bool(menu.IsEnabled())
        except Exception:
            self._ready = bool(menu)

    def menu_id(self) -> int:
        return id(self._menu) if self._menu is not None else 0

    def has_menu(self) -> bool:
        return self._menu is not None

    def is_ready(self) -> bool:
        return self._ready
```

- [ ] **Step 4: Wire `CharacterClass` + the static**

In `engine/appc/characters.py`:

Add import:
```python
from engine.appc.character_menu_state import MenuState
```

In `__init__`, replace
```python
        self._menu_state = None       # SP4: MenuState (formalizes _menu)
```
with
```python
        self._menu_state = MenuState()   # SP4: menu id + ready (tier-0 4.12)
```

In `SetMenu`, after `self._menu = menu`, add:
```python
        self._menu_state.set_menu(menu)
```

Add the module-level static (near `CharacterClass_GetObject`):
```python
def CharacterClass_GetCharacterFromMenu(menu_id, candidates=None):
    """Return the bridge character whose menu id matches menu_id, or None
    (tier-0 reference sec 4.12: search the "bridge" set, first member whose
    +0x14c == menuId). `candidates` overrides the search set (tests); default
    is the live "bridge" set's CharacterClass members."""
    if candidates is None:
        try:
            import App
            bridge = App.g_kSetManager.GetSet("bridge")
            candidates = [c for c in _iter_bridge_characters(bridge)]
        except Exception:
            candidates = []
    for ch in candidates:
        ms = getattr(ch, "_menu_state", None)
        if ms is not None and ms.menu_id() == int(menu_id) and int(menu_id) != 0:
            return ch
    return None


def _iter_bridge_characters(bridge):
    if bridge is None:
        return []
    try:
        import App
        return [c for c in bridge.GetClassObjectList(App.CT_CHARACTER)
                if isinstance(c, CharacterClass)]
    except Exception:
        return []
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/appc/test_character_menu_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Characterization test — MenuUp behaviour unchanged**

Add to `tests/appc/test_character_menu_state.py`:
```python
def test_menu_up_behaviour_unchanged_no_menu():
    ch = CharacterClass()                 # no menu set
    assert ch.MenuUp() == 0               # nothing to raise (same as pre-SP4)


def test_menu_up_behaviour_unchanged_disabled_menu():
    ch = CharacterClass()
    menu = STTopLevelMenu_CreateW("Helm")
    menu.SetDisabled()
    ch.SetMenu(menu)
    assert ch.MenuUp() == 0               # disabled menu: not raised
```

Run: `uv run pytest tests/appc/test_character_menu_state.py -v`
Expected: PASS (6 passed)

- [ ] **Step 7: Commit**

```bash
git add engine/appc/character_menu_state.py tests/appc/test_character_menu_state.py engine/appc/characters.py
git commit -m "feat(sp4): owned MenuState + GetCharacterFromMenu (consolidation)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Current-tooltip-owner statics + DropCharacterToolTips

**Files:**
- Modify: `engine/appc/characters.py` (owner statics; `DropCharacterToolTips`; wire `_should_drop_tooltips`/`_drop_character_tooltips`)
- Test: `tests/appc/test_character_tooltip_dispatch.py` (owner-tracking half)

**Interfaces:**
- Produces: `CharacterClass_GetCurrentToolTipOwner() -> CharacterClass|None`, `CharacterClass_SetCurrentToolTipOwner(ch)`, `DropCharacterToolTips()`. `CharacterClass._should_drop_tooltips()` returns True when this character IS the current owner.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/test_character_tooltip_dispatch.py
from engine.appc.characters import (
    CharacterClass,
    CharacterClass_GetCurrentToolTipOwner,
    CharacterClass_SetCurrentToolTipOwner,
    DropCharacterToolTips,
)


def test_owner_set_get_roundtrip():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    assert CharacterClass_GetCurrentToolTipOwner() is ch
    CharacterClass_SetCurrentToolTipOwner(None)
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_drop_clears_owner():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    DropCharacterToolTips()
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_should_drop_tooltips_only_for_owner():
    a, b = CharacterClass(), CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(a)
    assert a._should_drop_tooltips() is True
    assert b._should_drop_tooltips() is False
    CharacterClass_SetCurrentToolTipOwner(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_character_tooltip_dispatch.py -v`
Expected: FAIL (`ImportError` for the owner statics)

- [ ] **Step 3: Implement the owner statics**

In `engine/appc/characters.py`, add near the other module-level statics:
```python
# ── Current-tooltip-owner (BC statics CharacterClass_Get/SetCurrentToolTipOwner)
# One character's status box is visible at a time; the host loop's owner-
# selection tick (Task 8) sets this to the focused officer. DropMenusTurnBack /
# DropCharacterToolTips clear it.
_current_tooltip_owner = None


def CharacterClass_GetCurrentToolTipOwner():
    return _current_tooltip_owner


def CharacterClass_SetCurrentToolTipOwner(character):
    global _current_tooltip_owner
    _current_tooltip_owner = character


def DropCharacterToolTips():
    """Hide the current tooltip owner's box and clear the owner slot (mirrors
    BridgeHandlers.DropCharacterToolTips). The CEF panel reads the owner each
    frame, so clearing the slot hides the box next render."""
    CharacterClass_SetCurrentToolTipOwner(None)
```

Replace the SP2 placeholder `_should_drop_tooltips` in `CharacterClass`:
```python
    def _should_drop_tooltips(self) -> bool:
        return False        # SP4 wires the real current-tooltip-owner check
```
with:
```python
    def _should_drop_tooltips(self) -> bool:
        return CharacterClass_GetCurrentToolTipOwner() is self
```

Leave `_drop_character_tooltips` as-is (the CEF panel handles the visual drop via the owner slot; no per-character call needed). Add a one-line note there:
```python
    def _drop_character_tooltips(self) -> None:
        DropCharacterToolTips()     # owner-slot clear; CEF panel hides next frame
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/appc/test_character_tooltip_dispatch.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Reset the owner slot on mission swap (leak guard)**

In `tests/conftest.py`'s autouse `_reset_leakable_engine_globals`, add a reset (find the block that resets `engine.appc` module globals and append):
```python
    try:
        import engine.appc.characters as _chars
        _chars.CharacterClass_SetCurrentToolTipOwner(None)
    except Exception:
        pass
```

Run: `uv run pytest tests/appc/ -q`
Expected: PASS (no new failures).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/characters.py tests/appc/test_character_tooltip_dispatch.py tests/conftest.py
git commit -m "feat(sp4): current-tooltip-owner statics + DropCharacterToolTips

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: CharacterTooltipPanel + CEF assets

**Files:**
- Create: `engine/ui/character_tooltip_panel.py`
- Create: `native/assets/ui-cef/js/character_tooltip.js`
- Create: `native/assets/ui-cef/css/character_tooltip.css`
- Modify: `native/assets/ui-cef/index.html`
- Test: `tests/ui/test_character_tooltip_panel.py`

**Interfaces:**
- Consumes: `CharacterClass_GetCurrentToolTipOwner` (Task 4); `StatusMap.rows()` (Task 1).
- Produces: `CharacterTooltipPanel(Panel)` with `name == "character-tooltip"`, `render_payload()` emitting `setCharacterTooltip(<json>);`, `snapshot() -> dict`. JS `setCharacterTooltip(payload)` mounts a `.bc-panel` into `#character-tooltip-host`.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_character_tooltip_panel.py
import json
from engine.appc.characters import (
    CharacterClass, CharacterClass_SetCurrentToolTipOwner,
)
from engine.ui.character_tooltip_panel import CharacterTooltipPanel


def _owner_with_rows():
    ch = CharacterClass()
    ch.SetCharacterName("Helm")
    ch.SetStatus("Waiting", 0)
    ch.SetStatus("5 : 120 kph", 1)
    CharacterClass_SetCurrentToolTipOwner(ch)
    return ch


def test_snapshot_hidden_when_no_owner():
    CharacterClass_SetCurrentToolTipOwner(None)
    p = CharacterTooltipPanel()
    assert p.snapshot()["visible"] is False


def test_snapshot_shows_owner_rows_in_key_order():
    _owner_with_rows()
    p = CharacterTooltipPanel()
    snap = p.snapshot()
    assert snap["visible"] is True
    assert snap["title"] == "Helm"
    assert snap["rows"] == ["Waiting", "5 : 120 kph"]
    CharacterClass_SetCurrentToolTipOwner(None)


def test_render_payload_diff_gated():
    _owner_with_rows()
    p = CharacterTooltipPanel()
    first = p.render_payload()
    assert first is not None and first.startswith("setCharacterTooltip(")
    assert p.render_payload() is None          # unchanged -> no re-emit
    CharacterClass_SetCurrentToolTipOwner(None)


def test_name_is_routing_prefix():
    assert CharacterTooltipPanel().name == "character-tooltip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_character_tooltip_panel.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement the panel**

```python
# engine/ui/character_tooltip_panel.py
"""CharacterTooltipPanel -- the CEF crew tooltip box (BC's native status box,
built by Bridge.BridgeMenus.CreateCharacterTooltipBox). Renders the current
tooltip owner's StatusMap rows 0..5 as a top-centre .bc-panel. Visibility follows
CharacterClass_GetCurrentToolTipOwner: the host-loop owner-selection tick (Task 8)
sets the owner to the focused officer; this panel just reflects it.

Title comes from CharacterStatus.tgl keyed by GetCharacterName (headless/miss ->
the raw name). Rows come from StatusMap.rows() in ascending key order.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.appc.characters import CharacterClass_GetCurrentToolTipOwner


class CharacterTooltipPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str:
        return "character-tooltip"

    def _title_for(self, owner) -> str:
        raw = owner.GetCharacterName()
        try:
            import App
            db = App.g_kLocalizationManager.Load("data/TGL/CharacterStatus.tgl")
            try:
                s = str(db.GetString(raw))
                return s or raw
            finally:
                App.g_kLocalizationManager.Unload(db)
        except Exception:
            return raw

    def snapshot(self) -> dict:
        owner = CharacterClass_GetCurrentToolTipOwner()
        if owner is None:
            return {"visible": False, "title": "", "rows": []}
        rows = [str(v) for _k, v in owner._status_map.rows()]
        if not rows:
            return {"visible": False, "title": "", "rows": []}
        return {"visible": True, "title": self._title_for(owner), "rows": rows}

    def render_payload(self) -> Optional[str]:
        payload = json.dumps(self.snapshot())
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setCharacterTooltip(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        return False        # display-only; no interaction

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ui/test_character_tooltip_panel.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Add the JS renderer** (mirrors `js/crew_menus.js`'s `.bc-panel` build)

```javascript
// native/assets/ui-cef/js/character_tooltip.js
// Invoked by the host as setCharacterTooltip(payload). Renders the focused
// officer's status rows as a top-centre .bc-panel (shared crew chrome). Only the
// current-tooltip-owner's box shows; {visible:false} clears it.
function setCharacterTooltip(payload) {
  const host = document.getElementById("character-tooltip-host");
  if (!host) return;
  host.innerHTML = "";
  if (!payload || !payload.visible) return;

  const panel = document.createElement("section");
  panel.className = "bc-panel character-tooltip";

  const header = document.createElement("header");
  header.className = "bc-panel__header";
  const title = document.createElement("span");
  title.className = "bc-panel__title";
  title.textContent = payload.title || "";
  header.appendChild(title);
  panel.appendChild(header);

  const body = document.createElement("div");
  body.className = "bc-panel__body";
  for (const line of payload.rows || []) {
    const row = document.createElement("div");
    row.className = "character-tooltip__row";
    row.textContent = line;
    body.appendChild(row);
  }
  panel.appendChild(body);
  host.appendChild(panel);
}
```

- [ ] **Step 6: Add the CSS** (layout only; chrome inherited from `.bc-panel`)

```css
/* native/assets/ui-cef/css/character_tooltip.css
   Crew tooltip box -- the focused officer's status rows. Chrome (header/body
   salmon .bc-panel) is inherited from global.css/crew_menus.css; this file
   only positions the box (top-centre of the bridge view) and stacks rows. */
#character-tooltip-host {
  position: absolute;
  top: 5%;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  pointer-events: none;   /* tooltip never eats clicks */
}
#character-tooltip-host .character-tooltip { min-width: 220px; max-width: 40%; }
#character-tooltip-host .character-tooltip__row {
  padding: 2px 10px;
  white-space: nowrap;
}
```

- [ ] **Step 7: Wire into `index.html`**

In `native/assets/ui-cef/index.html`:
- After the `css/engineering_power.css` link (line ~19) add:
```html
    <link rel="stylesheet" href="css/character_tooltip.css">
```
- Add the host div near `#crew-menu-host` (line ~409):
```html
            <div id="character-tooltip-host"></div>
```
- With the other `<script src="js/...">` tags (line ~572+) add:
```html
    <script src="js/character_tooltip.js"></script>
```

- [ ] **Step 8: Commit**

```bash
git add engine/ui/character_tooltip_panel.py tests/ui/test_character_tooltip_panel.py \
        native/assets/ui-cef/js/character_tooltip.js native/assets/ui-cef/css/character_tooltip.css \
        native/assets/ui-cef/index.html
git commit -m "feat(sp4): CEF crew tooltip box panel (.bc-panel chrome)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: station_name_for helper (officer → UpdateToolTip prefix)

**Files:**
- Modify: `engine/ui/crew_menu_hotkeys.py` (add `station_name_for`)
- Test: `tests/ui/test_crew_menu_station_name.py`

**Interfaces:**
- Produces: `crew_menu_hotkeys.station_name_for(officer) -> str|None` — the bridge set-object name (`"Helm"`, `"Tactical"`, `"XO"`, `"Science"`, `"Engineer"`), which is exactly the `<prefix>UpdateToolTip` prefix. Resolves by identity against the live "bridge" set.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_crew_menu_station_name.py
from engine.ui import crew_menu_hotkeys


class _FakeBridge:
    def __init__(self, mapping):
        self._m = mapping
    def GetObject(self, name):
        return self._m.get(name)


def test_station_name_for_matches_by_identity(monkeypatch):
    helm = object()
    tac = object()
    bridge = _FakeBridge({"Helm": helm, "Tactical": tac, "XO": None,
                          "Science": None, "Engineer": None})

    class _SM:
        def GetSet(self, n): return bridge if n == "bridge" else None

    import App
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    monkeypatch.setattr(App, "CharacterClass_GetObject",
                        lambda pset, name: pset.GetObject(name), raising=False)

    assert crew_menu_hotkeys.station_name_for(helm) == "Helm"
    assert crew_menu_hotkeys.station_name_for(tac) == "Tactical"
    assert crew_menu_hotkeys.station_name_for(object()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_crew_menu_station_name.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'station_name_for'`)

- [ ] **Step 3: Implement the helper**

In `engine/ui/crew_menu_hotkeys.py`, add after `resolve_character`:
```python
def station_name_for(officer):
    """The bridge set-object name for `officer` ("Helm"/"Tactical"/"XO"/
    "Science"/"Engineer"), or None. That name is exactly the SDK's
    <prefix>UpdateToolTip prefix (BridgeHandlers.HelmUpdateToolTip, ...), so the
    tooltip dispatcher (host loop) maps officer -> handler through this. Resolves
    by identity against the live "bridge" set."""
    if officer is None:
        return None
    try:
        import App
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            return None
        for _key, char_name in _KEY_TO_CHARACTER.items():
            if App.CharacterClass_GetObject(bridge, char_name) is officer:
                return char_name
    except Exception:
        return None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ui/test_crew_menu_station_name.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_hotkeys.py tests/ui/test_crew_menu_station_name.py
git commit -m "feat(sp4): station_name_for(officer) -> UpdateToolTip prefix

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: UpdateToolTip dispatcher + owner-selection tick

**Files:**
- Create: `engine/ui/tooltip_dispatch.py` (pure dispatcher; unit-testable)
- Modify: `engine/host_loop.py` (register `CharacterTooltipPanel`; call the tick each bridge frame)
- Test: `tests/appc/test_character_tooltip_dispatch.py` (dispatcher half — extend the Task-4 file)

**Interfaces:**
- Consumes: `bridge_officer_picking.pick` (aimed officer label), `crew_menu_hotkeys.resolve_character` / `station_name_for`, `CharacterClass_SetCurrentToolTipOwner`, `crew_menu_panel.open_menu_label`.
- Produces: `tooltip_dispatch.select_owner(aimed_officer, open_menu_officer) -> owner|None`; `tooltip_dispatch.run_update_tooltip(owner, now, state) -> None` (throttled call into `BridgeHandlers.<station>UpdateToolTip`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/appc/test_character_tooltip_dispatch.py
from engine.ui import tooltip_dispatch
from engine.appc.characters import CharacterClass_GetCurrentToolTipOwner


def test_select_owner_prefers_open_menu_then_hover():
    a, b = object(), object()
    assert tooltip_dispatch.select_owner(hover=a, open_menu=b) is b   # menu wins
    assert tooltip_dispatch.select_owner(hover=a, open_menu=None) is a
    assert tooltip_dispatch.select_owner(hover=None, open_menu=None) is None


def test_run_update_tooltip_calls_station_handler(monkeypatch):
    calls = []

    class _Handlers:
        def HelmUpdateToolTip(self, ch):
            calls.append(ch)

    monkeypatch.setattr(tooltip_dispatch, "_bridge_handlers",
                        lambda: _Handlers(), raising=False)
    monkeypatch.setattr(tooltip_dispatch, "_station_name_for",
                        lambda ch: "Helm", raising=False)

    owner = object()
    state = {"last": -999.0}
    tooltip_dispatch.run_update_tooltip(owner, now=10.0, state=state, period=0.25)
    assert calls == [owner]
    # Within the throttle window: no second call.
    tooltip_dispatch.run_update_tooltip(owner, now=10.1, state=state, period=0.25)
    assert calls == [owner]
    # After the window: called again.
    tooltip_dispatch.run_update_tooltip(owner, now=10.4, state=state, period=0.25)
    assert calls == [owner, owner]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_character_tooltip_dispatch.py -v`
Expected: FAIL (`ModuleNotFoundError: engine.ui.tooltip_dispatch`)

- [ ] **Step 3: Implement the dispatcher**

```python
# engine/ui/tooltip_dispatch.py
"""Tooltip owner-selection + UpdateToolTip dispatch (reconstructs BC's native
tooltip loop). BC natively calls <station>UpdateToolTip(pChar) on a cadence while
a character's tooltip is up; those SDK handlers (BridgeHandlers.HelmUpdateToolTip
etc.) write status keys 1-3. Nothing calls them in Dauntless, so this module runs
the real handlers for the current tooltip owner on a throttle.

select_owner picks the focused officer (open crew menu wins over hover). The host
loop resolves hover via bridge_officer_picking and the open-menu officer via the
crew menu panel, sets the current tooltip owner, and calls run_update_tooltip.
"""
from __future__ import annotations


def select_owner(hover, open_menu):
    """Focused officer: an open crew menu outranks hover (BC shows the menu
    officer's box); else the hovered officer; else None."""
    if open_menu is not None:
        return open_menu
    return hover


def _bridge_handlers():
    import BridgeHandlers
    return BridgeHandlers


def _station_name_for(officer):
    from engine.ui import crew_menu_hotkeys
    return crew_menu_hotkeys.station_name_for(officer)


def run_update_tooltip(owner, now, state, period=0.25) -> None:
    """Throttled call into BridgeHandlers.<station>UpdateToolTip(owner). `state`
    is a mutable dict carrying {"last": <time>}; `period` is the min seconds
    between calls. No-op when the owner has no station handler (non-station
    characters show only their key-0 status)."""
    if owner is None:
        return
    if now - state.get("last", -1e9) < period:
        return
    station = _station_name_for(owner)
    if not station:
        return
    handlers = _bridge_handlers()
    fn = getattr(handlers, station + "UpdateToolTip", None)
    if fn is None:
        return
    state["last"] = now
    try:
        fn(owner)
    except Exception:
        pass        # a handler fault must never break the frame
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/appc/test_character_tooltip_dispatch.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Verify `BridgeHandlers` is importable at runtime (twin stub lists)**

Check `tools/mission_harness.py` and `tests/conftest.py` stub lists: `BridgeHandlers` must NOT be in the `_StubModules` set (it holds the real `*UpdateToolTip` bodies). If it is stubbed in either, the dispatcher's `import BridgeHandlers` yields a stub and the call no-ops — grep both files:

Run: `grep -n "BridgeHandlers" tools/mission_harness.py tests/conftest.py`
Expected: BridgeHandlers is imported/used, not in a `_StubModules`/stub set. If stubbed, remove it from BOTH lists (never unstub a whole unrelated module — verify BridgeHandlers imports cleanly headless first with `uv run python -c "import BridgeHandlers"` after `_setup_sdk`).

- [ ] **Step 6: Wire the tick into the host loop**

In `engine/host_loop.py`:

Register the panel where the dev/production panels are registered (near the `ship_display`/`weapons_display` registration, ~line 6060):
```python
        from engine.ui.character_tooltip_panel import CharacterTooltipPanel
        character_tooltip_panel = CharacterTooltipPanel()
        registry.register(character_tooltip_panel)
```

Add module-level throttle state near the other host-loop state:
```python
_tooltip_dispatch_state = {"last": -1e9}
```

In the bridge-view frame block (the same `not pause.sim_frozen` region that calls `_resolve_bridge_focus_world` / `set_zoom_target`, ~line 6905), after resolving the open-menu focus, add owner-selection + dispatch:
```python
                        # SP4: tooltip owner = focused officer (open menu wins
                        # over hover), then run the real SDK UpdateToolTip
                        # handler on a throttle so its status rows populate.
                        from engine.appc.characters import (
                            CharacterClass_SetCurrentToolTipOwner)
                        from engine.ui import tooltip_dispatch, bridge_officer_picking
                        _hover = None
                        _aimed = bridge_officer_picking.pick(host_io._h, r, bridge_camera)
                        if _aimed is not None:
                            _hover = crew_menu_hotkeys.resolve_character(_aimed["label"])
                        _menu_off = None
                        _mlabel = crew_menu_panel.open_menu_label()
                        if _mlabel:
                            _menu_off = crew_menu_hotkeys.resolve_character(_mlabel)
                        _owner = tooltip_dispatch.select_owner(hover=_hover,
                                                               open_menu=_menu_off)
                        CharacterClass_SetCurrentToolTipOwner(_owner)
                        tooltip_dispatch.run_update_tooltip(
                            _owner, now=App.g_kUtopiaModule.GetGameTime(),
                            state=_tooltip_dispatch_state)
```

Ensure `DropCharacterToolTips` clears the owner when leaving the bridge / on mission swap: the owner slot is reset by `_reset_leakable_engine_globals` (Task 4) and set to None each frame no owner resolves, so no extra teardown is needed.

- [ ] **Step 7: Build + gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 (only the baselined emitters flake in `known_failures.txt`).

- [ ] **Step 8: Commit**

```bash
git add engine/ui/tooltip_dispatch.py tests/appc/test_character_tooltip_dispatch.py \
        engine/host_loop.py tools/mission_harness.py tests/conftest.py
git commit -m "feat(sp4): UpdateToolTip dispatcher + tooltip owner-selection tick

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Per-officer camera zoom from PositionZoom

**Files:**
- Modify: `engine/host_loop.py` (`_BridgeCamera.set_zoom_target` gains a `zoom_factor`; `_active_zoom_officer_world` also returns the officer; feed `GetPositionZoom(GetLocation())`)
- Test: `tests/appc/test_position_zoom_camera.py`

**Interfaces:**
- Consumes: `CharacterClass.GetPositionZoom(name)` / `GetLocation()` (Task 2); `_active_zoom_officer_world` (existing).
- Produces: `_BridgeCamera.set_zoom_target(world_xyz, dt, snap=False, zoom_factor=None)` — when `zoom_factor` is given and not the sentinel, it overrides `_BRIDGE_ZOOM_MIN` for the FOV narrow; a helper `_officer_zoom_factor(officer)` returns `officer.GetPositionZoom(officer.GetLocation())`.

- [ ] **Step 1: Write the failing test**

```python
# tests/appc/test_position_zoom_camera.py
from engine.appc.characters import CharacterClass


def test_officer_zoom_factor_from_location():
    from engine.host_loop import _officer_zoom_factor
    ch = CharacterClass()
    ch.SetLocation("DBHelm")
    ch.AddPositionZoom("DBHelm", 0.45, "Helm")
    assert _officer_zoom_factor(ch) == 0.45


def test_officer_zoom_factor_miss_is_sentinel():
    from engine.host_loop import _officer_zoom_factor
    from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL
    ch = CharacterClass()
    ch.SetLocation("DBHelm")                 # no AddPositionZoom
    assert _officer_zoom_factor(ch) == POSITION_ZOOM_SENTINEL


def test_set_zoom_target_uses_zoom_factor_for_fov():
    from engine.host_loop import _BridgeCamera
    cam = _BridgeCamera()
    cam.set_zoom_target((0.0, 5.0, 0.0), dt=999.0, snap=True, zoom_factor=0.45)
    _eye, _t, _up, fov = cam.compute_camera()
    # Fully zoomed (snap) FOV is base * zoom_factor, not base * _BRIDGE_ZOOM_MIN.
    from engine.host_loop import _BRIDGE_ZOOM_MAX
    assert abs(fov - cam.FOV_Y_RAD * 0.45) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appc/test_position_zoom_camera.py -v`
Expected: FAIL (`ImportError: _officer_zoom_factor` / `set_zoom_target() unexpected keyword`)

- [ ] **Step 3: Add `zoom_factor` to `set_zoom_target` + the FOV narrow**

In `engine/host_loop.py` `_BridgeCamera`:

Add an instance field in `__init__` near `self._zoom_t = 0.0`:
```python
        self._zoom_factor = _BRIDGE_ZOOM_MIN   # SP4: per-officer FOV factor (GetPositionZoom)
```

Change the `set_zoom_target` signature and store the factor:
```python
    def set_zoom_target(self, world_xyz, dt: float, snap: bool = False,
                        zoom_factor=None) -> None:
```
At the top of the body, after `self._zoom_active = world_xyz is not None`, add:
```python
        if world_xyz is not None and zoom_factor is not None:
            from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL
            # sentinel == "no authored zoom" -> keep the default min factor.
            self._zoom_factor = (_BRIDGE_ZOOM_MIN
                                 if zoom_factor == POSITION_ZOOM_SENTINEL
                                 else float(zoom_factor))
```

In `compute_camera`, change the FOV narrow line
```python
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_MIN, e)
```
to
```python
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, self._zoom_factor, e)
```

- [ ] **Step 4: Add `_officer_zoom_factor` + `_active_zoom_officer` helper**

Change `_active_zoom_officer_world` to also expose the officer. Add a sibling that returns `(world, officer)`:
```python
def _active_zoom_officer(crew_menu_panel, r):
    """(world-centre, officer) of the open-menu officer, or (None, None)."""
    if crew_menu_panel is None:
        return None, None
    label = crew_menu_panel.open_menu_label()
    if not label:
        return None, None
    off = crew_menu_hotkeys.resolve_character(label)
    if off is None:
        return None, None
    iid = getattr(off, "_render_instance", None)
    if iid is None:
        return None, None
    center = r.get_instance_head_center(iid)
    if not center:
        return None, None
    return (center[0], center[1], center[2]), off


def _officer_zoom_factor(officer):
    """officer.GetPositionZoom(officer.GetLocation()) -> per-station FOV factor,
    or the sentinel when the station has no authored zoom."""
    from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL
    if officer is None:
        return POSITION_ZOOM_SENTINEL
    try:
        loc = officer.GetLocation()
        return officer.GetPositionZoom(loc)
    except Exception:
        return POSITION_ZOOM_SENTINEL
```

Keep `_active_zoom_officer_world` as a thin wrapper (used elsewhere):
```python
def _active_zoom_officer_world(crew_menu_panel, r):
    world, _off = _active_zoom_officer(crew_menu_panel, r)
    return world
```

- [ ] **Step 5: Feed the factor at the zoom call site**

In the bridge frame block, where `set_zoom_target` is called (~line 6920), resolve the officer's factor when the focus is the open-menu officer. Replace the existing focus resolve + `set_zoom_target` with:
```python
                        _focus = None
                        _zoom_factor = None
                        if watch_ctrl is not None:
                            _focus = watch_ctrl.resolve_target_world(r)
                        if _focus is None:
                            _focus, _zoom_off = _active_zoom_officer(crew_menu_panel, r)
                            _zoom_factor = _officer_zoom_factor(_zoom_off)
                        bridge_camera.set_zoom_target(
                            _focus, _player_dt,
                            snap=watch_ctrl.consume_snap(),
                            zoom_factor=_zoom_factor)
```
(Leave `_resolve_bridge_focus_world` in place for any other caller; this block now inlines the same precedence — watch target over open-menu officer — plus the factor.)

- [ ] **Step 6: Run test + gate**

Run: `uv run pytest tests/appc/test_position_zoom_camera.py -v`
Expected: PASS (3 passed)

Run: `scripts/check_tests.sh`
Expected: exit 0 (only the baselined emitters flake).

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/appc/test_position_zoom_camera.py
git commit -m "feat(sp4): bridge camera zooms to officer's authored PositionZoom

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Integration — real SDK UpdateToolTip populates the box

**Files:**
- Test: `tests/appc/test_character_tooltip_integration.py`

**Interfaces:** consumes everything above; no new production code (a green here validates the full chain; a RED means an earlier task's seam is wrong).

- [ ] **Step 1: Write the integration test**

```python
# tests/appc/test_character_tooltip_integration.py
"""End-to-end: the real BridgeHandlers.XOUpdateToolTip writes an alert into the
XO's StatusMap key 1, and the tooltip panel renders it. Runs the actual SDK
handler (not a reimplementation), proving the dispatcher chain + StatusMap +
panel agree."""
import pytest


def test_xo_update_tooltip_writes_alert_key1(sdk_env):
    import App
    import BridgeHandlers
    from engine.appc.characters import (
        CharacterClass, CharacterClass_SetCurrentToolTipOwner,
    )
    from engine.ui.character_tooltip_panel import CharacterTooltipPanel

    xo = CharacterClass()
    xo.SetCharacterName("XO")

    # A player at red alert so XOUpdateToolTip picks the "Red Alert" branch.
    player = _make_red_alert_player(App)
    # BridgeHandlers.XOUpdateToolTip resolves the XO via the bridge set + player
    # via MissionLib.GetPlayer; register both.
    _register_bridge_xo(App, xo, player)

    BridgeHandlers.XOUpdateToolTip(xo)
    assert "Alert" in str(xo.GetStatus(1))

    CharacterClass_SetCurrentToolTipOwner(xo)
    snap = CharacterTooltipPanel().snapshot()
    assert snap["visible"] is True
    assert any("Alert" in row for row in snap["rows"])
    CharacterClass_SetCurrentToolTipOwner(None)
```

**Implementation note for the engineer:** `sdk_env`, `_make_red_alert_player`, and
`_register_bridge_xo` are test scaffolding. Use the existing bridge-handler test
fixtures — grep `tests/` for a test that already calls a `BridgeHandlers.*` function
against a real player (e.g. tests touching `HelmUpdateToolTip`/`GetAlertLevel`) and
reuse its player construction + bridge-set registration. If none exists, build the
player via the same path `tests/appc/` uses to make a `ShipClass` with
`SetAlertLevel(App.ShipClass.RED_ALERT)` and register the XO with
`bridge.AddObjectToSet`/the set API the other character tests use. Keep the
localization DB load headless-safe (the SDK loads `Bridge Menus.TGL`; the harness
localization stub returns the key).

- [ ] **Step 2: Run it (expect RED first, then make it green by fixing scaffolding, not production code)**

Run: `uv run pytest tests/appc/test_character_tooltip_integration.py -v`
Expected: initially FAIL on scaffolding; once the fixtures are correct, PASS. If it fails inside `XOUpdateToolTip` on a stubbed `BridgeHandlers`/localization call, that's a Task-7 Step-5 stub-list miss — fix the stub lists, not the test.

- [ ] **Step 3: Full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 (only the baselined emitters flake).

- [ ] **Step 4: Commit**

```bash
git add tests/appc/test_character_tooltip_integration.py
git commit -m "test(sp4): real XOUpdateToolTip populates StatusMap + tooltip box

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Update the SP4 memory + heatmap note

**Files:**
- Modify: memory `project_characterclass_reimplementation.md` (SP4 status)

- [ ] **Step 1:** After the branch is merged/live-verified (Mark's pass), update the SP4 bullet: mark StatusMap/PositionZoomTable/MenuState done, note the tooltip box + camera zoom are player-visible and live-verified, and record that `BridgeHandlers` is the tooltip-handler source. Do NOT claim done before Mark's live pass (per `feedback_green_tests_cannot_see_asset_paths`). This step runs at the very end, after Task 9's gate and Mark's live verification.

- [ ] **Step 2:** Note in the memory that the exact `POSITION_ZOOM_SENTINEL` float remains a documented approximation (`1.0`), a follow-up if a future RE lookup recovers `*0x00888EB4`.

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §3.1 StatusMap data model → Task 1. §3.2 tooltip owner → Task 4. §3.3 CEF box → Task 5. §3.4 UpdateToolTip dispatcher → Tasks 6-7. §3.5 key semantics → tests in Tasks 1/9.
- §4.1 PositionZoomTable → Task 2. §4.2 camera zoom on focus → Task 8. Key composition (`GetLocation()`) → Task 8 `_officer_zoom_factor`.
- §5 MenuState + GetCharacterFromMenu → Task 3.
- §6 testing (unit/integration/gate/heatmap/stub-lists) → per-task + Task 9. §7 delivery → branch already created.

**Placeholder scan:** the only deferred content is the integration-test scaffolding in Task 9 (explicitly delegated to existing fixtures with a concrete grep target) and the `POSITION_ZOOM_SENTINEL` value (documented fallback). No `TODO`/`TBD` in production steps.

**Type consistency:** `set_status(value, key=0)` / `get_status(key)` / `rows()` consistent across Tasks 1/5/9. `get_position_zoom` / `POSITION_ZOOM_SENTINEL` consistent across Tasks 2/8. `station_name_for` (Task 6) feeds `_station_name_for` in the dispatcher (Task 7). `set_zoom_target(..., zoom_factor=None)` consistent across Task 8 production + test.
