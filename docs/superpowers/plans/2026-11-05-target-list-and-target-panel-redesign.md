# Target List and Target Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The target list becomes a ship picker that never expands (filter tabs, sort, distance, stacked bars); subsystem picking moves into the target panel (family icon buttons, name bar, member blocks, a lock marker on the ship); Lucide glyphs replace BC's damage icons in both ship panels, placed on the drawn ship.

**Architecture:** Python decides content, the page draws it. `TargetListView` filters and sorts its rows and owns filter/sort state; `ShipDisplayPanel` (target role) builds a family tree from the ship's subsystems and owns which family is open. Locking still goes through the existing `target/<ship>/<subsystem>` event. Click shortcuts (double-click, family of one) are page logic in a new `subsystem_picker.js`, written as pure functions so node can test them.

**Tech Stack:** Python 3 (engine/ui panels), CEF/Chromium 144 HTML/CSS/JS, pytest, node (for JS tests, `tests/ui/*_js.py` pattern), Lucide static SVGs 1.69.0 (ISC).

**Spec:** `docs/superpowers/specs/2026-11-05-target-list-and-target-panel-redesign-design.md`. Visual reference for every size, colour and spacing: the mockup `.superpowers/brainstorm/28763-1793886627/content/target-panel-v54-family-shortcuts.html` in the **main checkout** (`/Users/mward/Documents/Projects/bc_dauntless/`, gitignored). Its `<style>` block is the source for CSS values; copy them, don't reinvent them.

## Global Constraints

- **Never run the gate or a whole pytest suite.** Run only the test files named in each task (CLAUDE.md "Test gate"). An empty file list runs the whole suite: always name files.
- **Shared checkout:** no `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`. Stage with explicit paths. Commit with `git commit -F <msgfile>` (a commit-message hook trips on some inline messages).
- Work in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/target-panel-redesign`, branch `feat/target-panel-redesign`.
- Never spell `game` or `sdk` as a path segment; never capture a path at import (`tests/unit/test_path_indirection.py`).
- No `title=` tooltips (they show nothing in CEF off-screen rendering). Icon-only controls without a name bar use the page-drawn `[data-tip]` pattern from `native/assets/ui-cef/css/configuration_panel.css`.
- Lucide icons pinned to `lucide-static@1.69.0`, ISC licence; add a Lucide section to `THIRD_PARTY_NOTICES.md` under "Included in BC Dauntless".
- Distance is converted only at the display boundary: `target_menu.surface_gu_to(ship, player) * engine.units.GU_TO_KM`. No `*_m` names.
- Read subsystem state only through public getters (`GetCondition`, `IsDamaged`, `IsDisabled`, `IsDestroyed`, `IsTargetable`, `GetPosition2D`). Never cache a condition: after `ws/motion-phase6-a1` merges, state is native-authoritative.
- Colours (from the spec §5): damaged `rgb(184,255,0)`, disabled `rgb(153,153,153)`, destroyed `rgb(255,64,0)`, lock gold `rgb(255,210,90)`, healthy glyph `rgba(235,225,255,0.75)`, button/block grey `rgba(40,40,40,0.6)`, open/locked tint `rgba(216,43,43,0.35)`.
- Position frame: `SDK_FRAME_PX = 128` on **both** axes (spec §4.2; §9 q7 is open, keep it a single named constant).
- Before Task 1: build the native module in the worktree (fire control is native-only, tests need it): `cmake -B build -S . && cmake --build build -j`. Never reconfigure `CMAKE_BUILD_TYPE`.

## Review Focus

1. **Retargeting while a family is open:** the new target's panel shows no open family (the old name must not leak onto a ship that happens to have a family of the same name). Test in Task 5.
2. **The target cloaks while a subsystem is locked:** families go empty, the marker disappears, the panel does not raise. Test in Task 5.
3. **Subsystem names with quotes or apostrophes** (mod ships): buttons, blocks and emitted events stay intact. Test in Task 6.
4. **Every row filtered out** (or the selected target's side hidden): the list body is empty, tabs and sort stay drawn and clickable, nothing raises. Test in Task 3 and Task 4.
5. **A subsystem with no position** (`Position2D` (0, 0), common on mod ships): no marker is drawn for it, its button and block still lock. Test in Task 6.

---

### Task 1: Subsystem icon set

**Files:**
- Create: `engine/ui/subsystem_icons.py`
- Create: `native/assets/ui-cef/icons/subsystems/{radar,chevrons-up,margin-horizontal,warp-pod,test-tubes,laser,loader,wand-sparkles,eye-off,shield-plus,zap,boxes-linked,hull}.svg`
- Modify: `THIRD_PARTY_NOTICES.md` (new `### Lucide` section)
- Test: `tests/unit/test_subsystem_icons.py`, `tests/host/test_subsystem_icons_real_ships.py`

**Interfaces:**
- Produces: `icon_key_for(sub) -> str` and `svg_for_key(key: str) -> Optional[str]` in `engine.ui.subsystem_icons`; constant `ICON_KEYS: frozenset[str]` (the 13 keys above); `FALLBACK_KEY = "boxes-linked"`.

- [ ] **Step 1: Fetch the SVGs.** For each Lucide name, `curl -sL https://unpkg.com/lucide-static@1.69.0/icons/<name>.svg`, keep the `<!-- @license ... -->` line. File names = keys, except: `warp-pod.svg` is `usb-c-port` with its children wrapped in `<g transform="rotate(90 12 12)">…</g>`; `hull.svg` is a copy of the existing curated `native/assets/ui-cef/icons/damage/0.svg` (BC's hull glyph; the hull keeps it, spec §6 lists no Lucide hull icon). The mockup folder already holds most of these (`lucide-*.svg`); fetch rather than copy so the licence line is present.

- [ ] **Step 2: Write the failing unit test** `tests/unit/test_subsystem_icons.py`:

```python
from engine.ui import subsystem_icons as si
from engine.appc import subsystems as ss
from engine.appc import weapon_subsystems as ws

def test_class_keys():
    assert si.icon_key_for(ss.SensorSubsystem("S")) == "radar"
    assert si.icon_key_for(ss.ImpulseEngineSubsystem("I")) == "chevrons-up"
    assert si.icon_key_for(ss.WarpEngineSubsystem("W")) == "margin-horizontal"
    assert si.icon_key_for(ss.ShieldSubsystem("G")) == "shield-plus"
    assert si.icon_key_for(ss.PowerSubsystem("P")) == "zap"
    assert si.icon_key_for(ss.CloakingSubsystem("C")) == "eye-off"
    assert si.icon_key_for(ss.HullSubsystem("H")) == "hull"

def test_unknown_and_none_fall_back():
    assert si.icon_key_for(None) == "boxes-linked"
    assert si.icon_key_for(ss.ShipSubsystem("x")) == "boxes-linked"

def test_engine_pods_follow_their_parent():
    impulse = ss.ImpulseEngineSubsystem("Impulse Engines")
    warp = ss.WarpEngineSubsystem("Warp Engines")
    impulse_pod = ss.ShipSubsystem("Port Impulse")   # pods are plain ShipSubsystems
    warp_pod = ss.ShipSubsystem("Port Warp")         # (ships.py "Pass 5")
    impulse.AddChildSubsystem(impulse_pod)
    warp.AddChildSubsystem(warp_pod)
    assert si.icon_key_for(impulse_pod) == "chevrons-up"
    assert si.icon_key_for(warp_pod) == "warp-pod"

def test_every_key_has_a_file():
    for key in si.ICON_KEYS:
        assert si.svg_for_key(key).lstrip().startswith(("<!--", "<svg"))
    assert si.svg_for_key("nope") is None
```

Weapon classes (`TorpedoSystem`/`TorpedoTube` → `test-tubes`, `PulseWeaponSystem`/`PulseWeapon` → `loader`, `TractorBeamSystem`/`TractorBeam` → `wand-sparkles`, `PhaserSystem`/`PhaserBank` → `laser`) are asserted on real ships in Step 4 (their constructors need a ship).

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_subsystem_icons.py -v`. Expected: FAIL, `ModuleNotFoundError: engine.ui.subsystem_icons`.

- [ ] **Step 4: Write the failing host test** `tests/host/test_subsystem_icons_real_ships.py`, using the `loadspacehelper.CreateShip` fixture pattern from `tests/host/test_ship_display_damage_descriptors.py`. Walk the ship's subsystems and their children by name and assert: Akira `Phasers` and `Dorsal Phaser 1` → `laser`; `Torpedoes` and `Forward Torp 1` → `test-tubes`; `Tractors` and `Forward Tractor` → `wand-sparkles`; `Port Impulse` → `chevrons-up`; `Port Warp` → `warp-pod`; `Warp Core` → `zap`. Warbird: `Cloaking Device` → `eye-off`; `Disruptor Cannons` and `Port Cannon 1` → `loader`; `Disruptor Beam` and `Disruptor` → `laser`.

- [ ] **Step 5: Implement** `icon_key_for(sub) -> str`: first `isinstance` match over an ordered table (HullSubsystem, SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem, ShieldSubsystem, PowerSubsystem, CloakingSubsystem, TorpedoSystem, TorpedoTube, PulseWeaponSystem, PulseWeapon, TractorBeamSystem, TractorBeam, PhaserSystem, PhaserBank); on no match, `sub.GetParentSubsystem()` is an `ImpulseEngineSubsystem` → `chevrons-up`, a `WarpEngineSubsystem` → `warp-pod`; else `FALLBACK_KEY`. `svg_for_key` reads `native/assets/ui-cef/icons/subsystems/<key>.svg` relative to the project root (`os.path.dirname(__file__)` like `damage_icons._CURATED_DIR`), caches in a module dict, returns None for an unknown key. Add the `THIRD_PARTY_NOTICES.md` Lucide section (name, version 1.69.0, ISC licence text, URL https://lucide.dev).

- [ ] **Step 6: Run** `uv run pytest tests/unit/test_subsystem_icons.py tests/host/test_subsystem_icons_real_ships.py -v`. Expected: PASS.

- [ ] **Step 7: Commit** the module, SVGs, notice and both tests.

---

### Task 2: Damage icons: Lucide glyphs and placement on the drawn ship (both panels)

**Files:**
- Modify: `engine/ui/ship_display_panel.py` (`_damage_icon_descriptors`, `_snapshot`'s `damage_frozen`)
- Modify: `native/assets/ui-cef/index.html` (both `ship-display` sections: wrap the overlay in a frame)
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.js` (`rebuildDamageOverlay`)
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.css`
- Test: `tests/unit/test_ship_display_panel.py`, `tests/host/test_ship_display_damage_descriptors.py`, new `tests/ui/test_ship_display_overlay_js.py`

**Interfaces:**
- Consumes: Task 1 `icon_key_for`, `svg_for_key`.
- Produces: damage descriptor shape `{"icon_key": str, "icon_svg": str|None, "x_px": float, "y_px": float, "state": str}` (replaces `icon_num`); markup `<div class="ship-display__icon-frame">` inside `.ship-display__silhouette-stack`, holding `.ship-display__damage-overlay` (Task 6 adds the lock layer to the same frame); JS constant `SDK_FRAME_PX = 128`.

- [ ] **Step 1: Update the failing tests.** In `test_ship_display_panel.py::test_render_payload_damage_icons_descriptor_shape` assert the keys are exactly `{"icon_key", "icon_svg", "x_px", "y_px", "state"}`. In the host file rename `test_galaxy_sensor_array_emits_row_with_sensor_icon_num` to `..._with_radar_icon_key` and assert `row["icon_key"] == "radar"`.

- [ ] **Step 2: Write the failing node test** `tests/ui/test_ship_display_overlay_js.py` (pattern: `tests/ui/test_qb_victory_view_js.py`, skip without node). Fake DOM, call `setShipDisplay("target", {... damage_icons: [{icon_key:"warp-pod", icon_svg:"<svg/>", x_px:4, y_px:90, state:"damaged"}]})` and assert the created icon has `style.left == "3.13%"` and `style.top == "70.31%"` (4/128, 90/128).

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_ship_display_panel.py tests/host/test_ship_display_damage_descriptors.py tests/ui/test_ship_display_overlay_js.py -v`. Expected: the three changed tests FAIL.

- [ ] **Step 4: Implement.** Descriptor: `icon_key = subsystem_icons.icon_key_for(sub)`, `icon_svg = subsystem_icons.svg_for_key(icon_key)`; `damage_frozen` uses `icon_key` in place of `icon_num`. Markup: in both sections, `.ship-display__silhouette-stack` gets a child `<div class="ship-display__icon-frame">` holding the existing overlay div. CSS: `.ship-display__icon-frame { position:absolute; top:0; bottom:0; left:50%; height:100%; aspect-ratio:1/1; transform:translateX(-50%); pointer-events:none; z-index:5 }` (the drawn square of the `object-fit: contain` silhouette); the overlay keeps `inset:0` inside it. JS: replace `SDK_PANE_WIDTH_PX`/`SDK_PANE_HEIGHT_PX` with `SDK_FRAME_PX = 128` on both axes.

- [ ] **Step 5: Run** the Step 3 command. Expected: PASS. Also run `uv run pytest tests/unit/test_damage_icons.py tests/integration/test_ship_display_weapons_damage.py tests/integration/test_ship_display_sdk_integration.py -v`; fix any assertion on `icon_num` in those files the same way.

- [ ] **Step 6: Commit.**

---

### Task 3: Target list in Python: no expansion; distance, filter, sort

**Files:**
- Modify: `engine/ui/target_list_view.py`
- Delete: `tests/unit/test_target_list_view_nested.py`
- Modify: `tests/unit/test_target_list_view.py`
- Test: `tests/unit/test_target_list_view.py`, `tests/unit/test_target_list_sort_filter.py` (new)

**Interfaces:**
- Produces: payload `setTargetList({"visible", "selected", "selected_subsystem", "filters": {"FRIENDLY": bool, "NEUTRAL": bool, "ENEMY": bool}, "sort": "name"|"distance"|"health", "rows": [{"name", "label", "affiliation", "hull", "shields", "has_shields", "dist_km", "marker"}]})`, rows already filtered and in display order; events (prefix `target/`): `__filter__/<FRIENDLY|NEUTRAL|ENEMY>` toggles that side, `__sort__/<name|distance|health>` sets the sort; module function `sort_key(row: dict, sort: str) -> tuple`; constants `SORTS = ("name", "distance", "health")`, `FILTERABLE = ("FRIENDLY", "NEUTRAL", "ENEMY")`.
- Unchanged: `<ship>` and `<ship>/<subsystem>` events, `reconcile_subsystem_lock`, `TARGET_LIST_POLL_S`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_target_list_sort_filter.py` (reuse `_listed`, `_setup_game_with_player` style from `test_target_list_view.py`; give contacts real `surface_gu` values and place ships so `surface_gu_to` reads them):

```python
def test_default_sort_is_name_and_all_filters_on(): ...
    # payload["sort"] == "name"; payload["filters"] == {"FRIENDLY": True, "NEUTRAL": True, "ENEMY": True}
    # rows ordered by label, case-insensitive: ["galor 2", "Keldon 1", "USS Venture"]
def test_sort_distance_closest_first_ties_by_name(): ...
def test_sort_health_hull_then_shields_then_name_shieldless_counts_zero(): ...
    # hull 23 < 64 < 100; two rows at hull 100: shields 30 before 95; asteroid (has_shields False, shields 100) sorts as 0
def test_filter_hides_a_side_and_unknown_always_shows(): ...
    # dispatch_event("__filter__/ENEMY") -> no ENEMY rows, filters["ENEMY"] False, UNKNOWN row still listed
def test_every_side_hidden_leaves_empty_rows_not_an_error(): ...   # Review Focus 4
def test_dist_km_is_surface_distance_in_km_rounded_2dp(): ...
    # dist_km == round(surface_gu * GU_TO_KM, 2)
def test_filter_and_sort_events_do_not_retarget(): ...
    # player.GetTarget() unchanged after both events
def test_unknown_sort_or_filter_is_refused(): ...
    # dispatch_event("__sort__/bogus") is False and sort unchanged
def test_rows_carry_no_subsystem_tree(): ...
    # no "subsystems", "expanded", "has_subsystems" keys
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_target_list_sort_filter.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** Drop `_expanded_ships`, `_expanded_subsystems`, `_TOGGLE_ACTION`, `dispatch_event_subsystem_toggle`, the subsystem tree build (`_sub_entry`, `_keep`) and any `_query_*` helper left without a caller (keep `_resolve_subsystem_by_name`, `_next_living_sibling`, `reconcile_subsystem_lock`). Add `self._hidden: set[str]` and `self._sort = "name"`. Row tuple: `(name, caption, aff, hull, shields, has_shields, dist_km, marker)` with `dist_km = round(target_menu.surface_gu_to(ship, player) * GU_TO_KM, 2)`. Filter (drop rows whose affiliation is in `_hidden`; `UNKNOWN` and any other value always kept), then `sorted(rows, key=lambda r: sort_key(r, self._sort))` where `sort_key` returns `(label.casefold(),)`, `(dist_km, label.casefold())` or `(hull, shields if has_shields else 0, label.casefold())`. Filter/sort state goes in the snapshot so a change re-emits. In `dispatch_event`, handle `__filter__/` and `__sort__/` before any `SetTarget`; return True and `self.mark_due()` on a valid one.

- [ ] **Step 4: Update `tests/unit/test_target_list_view.py`.** Delete the tests that pin expansion or the subsystem tree in the list: `test_view_payload_includes_subsystems_and_health`, `test_view_payload_rows_collapsed_by_default`, `test_dispatch_event_toggle_expands_row`, `test_dispatch_event_toggle_does_not_change_player_target`, `test_view_payload_subsystems_carry_condition_pct`, `test_query_subsystem_condition_prefers_combined_over_individual`, `test_nested_children_and_expanded_reach_payload`, `test_query_subsystem_condition_defaults_to_100_when_resolution_misses`, `test_destroyed_child_subsystem_removed_but_parent_kept`, `test_parent_delisted_when_all_children_destroyed`, `test_destroyed_leaf_subsystem_removed_from_list`, `test_collapsed_rows_ship_no_subsystem_tree_but_keep_the_caret_flag`, `test_a_ship_with_no_subsystems_reports_no_caret`. (Their panel-side equivalents are added in Task 5.) Keep and fix the rest for the new row shape. Delete `tests/unit/test_target_list_view_nested.py`.

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_target_list_sort_filter.py tests/unit/test_target_list_view.py tests/unit/test_target_list_display_name.py tests/unit/test_target_markers.py tests/unit/test_weapon_system_cast_and_target_list.py -v`. Expected: PASS.

- [ ] **Step 6: Commit.**

---

### Task 4: Target list page: tabs, sort strip, distance, stacked bars, no chevron

**Files:**
- Modify: `native/assets/ui-cef/index.html` (`#target-list-panel`)
- Modify: `native/assets/ui-cef/js/target_list.js`
- Modify: `native/assets/ui-cef/css/target_list.css`
- Modify: `tests/ui/test_target_list_caret.py` (delete: the caret is gone)
- Test: `tests/ui/test_target_list_js.py` (new, node), `tests/ui/test_cef_js_syntax.py`

**Interfaces:**
- Consumes: Task 3 payload and events.
- Produces: markup `#target-list-tabs` (three `button.target-list__tab.target-list__tab--<AFF>` with `data-aff`, `data-tip`) between header and body; `#target-list-sort` (three `button.target-list__sort-opt` with `data-sort`, `role="radio"`, `data-tip`) after the body; JS `setTargetList(state)` (same entry point).

- [ ] **Step 1: Write the failing node test** `tests/ui/test_target_list_js.py`: feed `setTargetList` a payload and assert the rendered row HTML has no `target-list__caret`, no `target-list__sub`, contains `<span class="target-list__dist">29.62 km</span>` before `target-list__bars`, a row with `has_shields:false` has one bar; tab elements get `target-list__tab--on` exactly for `filters[aff] === true`; the sort option for `state.sort` gets `target-list__sort-opt--on` and `aria-checked="true"`; clicking a tab emits `target/__filter__/ENEMY`, clicking a sort option emits `target/__sort__/distance`, clicking the active sort emits nothing; with `rows: []` the tabs and sort still render and respond (Review Focus 4).

- [ ] **Step 2: Run** `uv run pytest tests/ui/test_target_list_js.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** Static markup with the inline Lucide SVGs `shield` / `satellite-dish` / `locate-fixed` (tabs, in that order: Friendlies, Neutrals, Enemies) and `id-card` / `radar` / `heart-pulse` (sort: name, distance, health), each with `data-tip` ("Friendlies", "Sort by distance (closest first)", ...). JS: row = name, `target-list__dist` (`dist_km.toFixed(2) + " km"`), bars; no caret/sub/leaf code; reflect `filters` and `sort` onto the static buttons; one delegated click handler per strip emitting the Task 3 events. CSS: copy from the mockup's style block the rules `.target-list__tabs`, `.target-list__tab*`, `.target-list__sort*`, `.target-list__dist`, and the stacked bars (`.target-list__bars { width:32px; flex-direction:column-reverse; gap:0 }`, bar `height:4px`, `:only-child` `height:8px`); delete the caret/sub/leaf rules. Add `[data-tip]` rules (copy the pattern from `configuration_panel.css`) scoped to `#target-list-panel`. Delete `tests/ui/test_target_list_caret.py`.

- [ ] **Step 4: Run** `uv run pytest tests/ui/test_target_list_js.py tests/ui/test_cef_js_syntax.py -v`. Expected: PASS.

- [ ] **Step 5: Commit.**

---

### Task 5: Target panel in Python: the family tree and the open family

**Files:**
- Create: `engine/ui/subsystem_tree.py`
- Modify: `engine/ui/ship_display_panel.py`
- Modify: `tests/unit/test_cloak_subsystem_suppression.py` (list-payload assertions move to the panel payload)
- Rewrite: `tests/integration/test_target_list_subsystems.py` → panel payload
- Test: `tests/unit/test_subsystem_tree.py`, `tests/host/test_subsystem_tree_real_ships.py`, `tests/unit/test_ship_display_panel.py`

**Interfaces:**
- Consumes: Task 1 `icon_key_for`; `engine.appc.target_menu._is_targetable`, `_has_targetable_descendant`; `App.STTargetMenu_GetTargetMenu().contact_for(ship).subsystems_targetable`.
- Produces in `engine.ui.subsystem_tree`:
  - `subsystem_state(sub) -> str` ∈ `"healthy"|"damaged"|"disabled"|"destroyed"` (move `ship_display_panel._row_state` here; `_row_state` becomes an alias or its callers switch).
  - `@dataclass(frozen=True) Member(name: str, state: str, icon_key: str, x_px: float, y_px: float)`
  - `@dataclass(frozen=True) Family(name: str, state: str, icon_key: str, lockable: bool, x_px: float, y_px: float, members: tuple[Member, ...])`
  - `build_families(ship) -> tuple[Family, ...]`
- Produces on `ShipDisplayPanel` (target role): events (prefix `ship-target/`) `open/<family>` (toggle), `show/<family>` (open, no toggle); payload keys `"families": [{"name","state","icon_key","icon_svg","lockable","x_px","y_px","members":[{"name","state","icon_key","icon_svg","x_px","y_px"}]}]`, `"open_family": str|None`, `"locked": str|None`. Player role: `families` `[]`, the other two `None`.

- [ ] **Step 1: Write the failing unit tests** `tests/unit/test_subsystem_tree.py` with hand-built subsystems on a `ShipClass`:

```python
def test_hull_is_never_a_family(): ...
def test_group_header_kept_only_with_a_targetable_member(): ...
    # non-targetable parent with targetable child -> Family(lockable=False, members=(child,))
    # non-targetable parent with only non-targetable children -> absent
def test_destroyed_members_drop_and_an_emptied_family_drops(): ...
def test_destroyed_single_subsystem_drops(): ...
def test_family_state_is_its_own_condition_not_its_members(): ...
    # family healthy, one member disabled -> Family.state == "healthy" (spec §4.3, Mark)
def test_state_ladder(): ...
    # condition 0 -> destroyed; <= disabled_pct*max -> disabled; < max -> damaged; max -> healthy
def test_position_and_order_follow_the_ship(): ...
    # x_px/y_px from GetPosition2D; family order = subsystem iteration order; member order = child index order
```

- [ ] **Step 2: Write the failing host test** `tests/host/test_subsystem_tree_real_ships.py`: Akira → family names (as a set) `{"Sensor Array","Impulse Engines","Warp Engines","Torpedoes","Phasers","Tractors","Shield Generator","Warp Core"}`, `Phasers` has 8 members, `Torpedoes` 6, `Port Warp` at `(4.0, 90.0)`; Warbird → 10 families including `Cloaking Device` (icon `eye-off`, no members), `Disruptor Beam` (`lockable False`, one member `Disruptor`), `Disruptor Cannons` (4 members, icon `loader`).

- [ ] **Step 3: Write the failing panel tests** in `tests/unit/test_ship_display_panel.py`:

```python
def test_target_payload_carries_families_open_family_and_locked(): ...
def test_player_payload_has_no_families(): ...
def test_open_event_toggles_and_show_event_only_opens(): ...
def test_retarget_clears_the_open_family(): ...            # Review Focus 1
def test_cloaked_target_has_no_families_and_no_lock(): ...  # Review Focus 2
    # contact.subsystems_targetable False -> families [], locked None, no raise
def test_family_change_reemits(): ...
    # a member's state change makes render_payload return a new string
```

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_subsystem_tree.py tests/host/test_subsystem_tree_real_ships.py tests/unit/test_ship_display_panel.py -v`. Expected: FAIL.

- [ ] **Step 5: Implement.** `build_families` walks `ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)` in order, skips `HullSubsystem`, keeps a subsystem when `_is_targetable(sub) or _has_targetable_descendant(sub)`; members are its direct children that are targetable and not destroyed; a subsystem with children but no surviving member is dropped; a childless one is dropped when destroyed. `ShipDisplayPanel`: `self._open_family: Optional[str] = None`, `self._open_ship_id = 0`; in `_snapshot` (target role) compute `families` (empty when the contact's `subsystems_targetable` is False), clear `_open_family` when `ship_id != self._open_ship_id` or the open name is not among the families, and add `(families, open_family, locked)` to the tuple; `locked = player.GetTargetSubsystem().GetName()` when the player's target is this ship, else None. Build `icon_svg` only in `render_payload` (via `svg_for_key`), never in the snapshot. Dispatch: `open/<f>` toggles, `show/<f>` sets; both `invalidate`.

- [ ] **Step 6: Move the list's subsystem tests to the panel.** In `tests/unit/test_cloak_subsystem_suppression.py`, the tests asserting the list's `subsystems` (`test_cloaked_contact_inside_bubble_lists_ship_with_no_subsystems`, `test_uncloaked_contact_at_same_distance_still_carries_subsystems`, `test_cached_subsystem_rows_survive_cloak_then_decloak_without_rebuild`) assert the target panel's `families` instead; the lock and click-recheck tests stay as they are. Rewrite `tests/integration/test_target_list_subsystems.py` to assert the same real-SDK ship's subsystems through the panel payload.

- [ ] **Step 7: Run** the Step 4 command plus `uv run pytest tests/unit/test_cloak_subsystem_suppression.py tests/integration/test_target_list_subsystems.py tests/host/test_ship_display_damage_descriptors.py -v`. Expected: PASS.

- [ ] **Step 8: Commit.**

---

### Task 6: Target panel page: speed on icon, family buttons, name bar, member blocks, lock marker, clicks

**Files:**
- Create: `native/assets/ui-cef/panels/ship_display/subsystem_picker.js`
- Modify: `native/assets/ui-cef/index.html` (target section only; add the script tag after `ship_display.js`)
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.js` (call the picker for the target role; speed binding)
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.css`
- Test: `tests/ui/test_subsystem_picker_js.py` (new, node)

**Interfaces:**
- Consumes: Task 5 payload keys and events; Task 3 `target/<ship>` and `target/<ship>/<subsystem>` events; Task 2 `.ship-display__icon-frame`.
- Produces (globals in `subsystem_picker.js`, pure unless noted):
  - `pickerFamilyColumns(n: number) -> 6|8` — 7 or 8 → 8, else 6.
  - `pickerMemberColumns(n: number) -> 1|2|3` — `Math.min(Math.max(n,1),3)`.
  - `pickerCaption(state, hoverName) -> string` — hover, else `open_family`, else `locked`, else `""`.
  - `pickerClick(state, kind, name, nowMs, last) -> {events: string[], last}` — `kind` ∈ `"family"|"member"`; `last` = `{name, t}`; `state` = the payload plus `ship`.
  - `renderSubsystemPicker(root, state)` (DOM) — writes `[data-bind="subsystems"]` and `[data-bind="lock-layer"]`, wires delegated click and hover handlers once per root.
  - Constant `PICKER_DOUBLE_CLICK_MS = 350`.

The click rules `pickerClick` must implement (spec §4.3, §4.5), with `members` = the family's listed members:

| Situation | Events |
|---|---|
| second click on the same family within 350 ms, family has members | `ship-target/show/<f>`, `target/<ship>/<first member>` |
| second click within 350 ms on a family with no members | `target/<ship>/<f>` |
| single click, family `lockable` with members | locked == f ? `target/<ship>` : `ship-target/show/<f>`, `target/<ship>/<f>` |
| single click, exactly 1 member | locked == member ? `target/<ship>` : `ship-target/show/<f>`, `target/<ship>/<member>` |
| single click, 2+ members | `ship-target/open/<f>` |
| single click, no members | locked == f ? `target/<ship>` : `target/<ship>/<f>` |
| member block click | locked == m ? `target/<ship>` : `target/<ship>/<m>` |

A double-click consumes `last` (resets it) so a third quick click is a single click again.

- [ ] **Step 1: Write the failing node test** `tests/ui/test_subsystem_picker_js.py` (load `subsystem_picker.js` with a minimal fake DOM; pure functions called directly):

```text
pickerFamilyColumns: 6->6, 7->8, 8->8, 9->6, 10->6, 3->6
pickerMemberColumns: 1->1, 2->2, 3->3, 8->3, 0->1
pickerCaption: hover wins; then open_family; then locked; else ""
pickerClick: one assertion per row of the table above, with ship "Warbird 1"
  - double-click on "Disruptor Cannons" (members Port Cannon 2, Star Cannon 1, Star Cannon 2) ->
    ["ship-target/show/Disruptor Cannons", "target/Warbird 1/Port Cannon 2"]
  - single click on "Disruptor Beam" (1 member) -> show + "target/Warbird 1/Disruptor"; with locked "Disruptor" -> ["target/Warbird 1"]
  - clicks 400 ms apart are two single clicks
render (renderSubsystemPicker with Akira-shaped payload):
  - 8 buttons, grid style "--cols:8"; Warbird-shaped (10) -> "--cols:6"
  - disabled family button has data-state="disabled"; locked family button has class subsys-btn--locked
  - open family shows member blocks with "--member-cols:" + min(n,3); locked member block has class subsys-block--locked
  - name bar always present; empty text when nothing locked and no hover
  - lock marker drawn at left "42.19%" top "23.44%" for Dorsal Phaser 2 (54,30)/128; no marker when locked subsystem has x_px 0 and y_px 0 (Review Focus 5)
  - names containing ' and " render intact and emit intact event strings (Review Focus 3)
```

- [ ] **Step 2: Run** `uv run pytest tests/ui/test_subsystem_picker_js.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** Markup (target section): move the speed span into `.ship-display__silhouette-stack` as `<span class="ship-display__speed" data-bind="speed">`; delete `ship-display__target-extras` and its `range` span (and the range branch in `ship_display.js`; leave Python's `range_km` alone, the list uses the same function); add `<div class="ship-display__lock-layer" data-bind="lock-layer">` inside `.ship-display__icon-frame`; add `<div class="ship-display__subsystems" data-bind="subsystems"></div>` after the hull bar. `ship_display.js` calls `renderSubsystemPicker(root, state)` when `role === "target"`. CSS: copy from the mockup the rules for `.ship-display__speed`, `.subsys-grid`, `.subsys-btn*`, `.subsys-caption` (centred), `.subsys-blocks`, `.subsys-block*` (left-aligned names, `text-wrap: balance`, 3px state edge transparent when healthy, disabled grey fill with black text, locked tint plus the `::after` full-width 2px white underline with `left:-3px`), `.lock-marker*` (22px, gold corner brackets, no backing), `.ship-display__lock-layer`; z-order speed 7 > lock layer 6 > damage overlay 5 > shields 4. Event emission uses `dauntlessEvent` with the strings from `pickerClick`; build attribute values with the same escaping helpers as `target_list.js` (`escapeHtml`; copy them, `target_list.js` is not loaded first).

- [ ] **Step 4: Run** `uv run pytest tests/ui/test_subsystem_picker_js.py tests/ui/test_ship_display_overlay_js.py tests/ui/test_ship_display_shield_flicker.py -v`. Expected: PASS.

- [ ] **Step 5: Commit.**

---

### Task 7: Rebase, measure, live check

**Files:**
- Modify: `docs/reference/engine/perf-register.md` (one signal entry), `CLAUDE.md` (one Key reference row)

- [ ] **Step 1: Rebase** onto `main` once `ws/motion-phase6-a1` has merged. Expected conflict only in `engine/host_loop.py` `_pump_contacts` (profiler scopes); this branch does not change `_pump_contacts`, so take main's side. Rerun every test file named in Tasks 1-6 in one command. Expected: PASS.

- [ ] **Step 2: Ask Mark before launching the game** (memory: never launch without asking). With permission, capture with the frame profiler at 64 ships: `DAUNTLESS_MISSION=engine.dev_missions.combat_stress ./build/dauntless`, Developer Options → Diagnostics, target an enemy and open a family. Expected: `ui.target` no higher than before this branch (the list no longer builds subsystem trees), and the `ship-target` panel's share reported. Record it as a new signal in `perf-register.md` (measured tier, capture ID, build type).

- [ ] **Step 3: Live check with Mark:** filter tabs, sort, distance column, stacked bars; family buttons on an Akira and a Warbird; double-click, family of one, unlock by clicking the lock; marker positions on both ship panels; disabled fill; `text-wrap: balance` in CEF. Record the result in the spec's header and the memory file `project_target_panel_redesign.md`.

- [ ] **Step 4: Add a CLAUDE.md Key reference row** ("Target list + target panel") pointing at the spec, `subsystem_icons.py`, `subsystem_tree.py`, `subsystem_picker.js`, with the two traps: icon keys come from `subsystem_icons.icon_key_for` only; `SDK_FRAME_PX` is the one position-frame constant. Commit.
