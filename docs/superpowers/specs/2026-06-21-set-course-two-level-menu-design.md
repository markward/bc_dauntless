# Two-Level Set Course Menu — Design

**Date:** 2026-06-21
**Status:** Approved (design), pending implementation plan
**Branch:** `feat/set-course-two-level-menu`

## Summary

Replace the merged "Setting course…" placeholder body of `SettingCoursePanel`
with a real **two-level star-system menu**: a two-column master-detail popup
listing **every** galaxy system on the left; selecting a system reveals **its
warp points** on the right; selecting a warp point records a UI-only "set
course". Systems and warp targets that the running game currently has in its
live SDK Set Course menu are styled **bold**.

The galaxy systems come from the galaxy-map JSON (`sector_model.json`, today
owned by the procedural-starbox module). The full set of warp points for every
system — which the original SDK only ever registers a per-mission subset of — is
produced by a new **offline baker** that runs the SDK registration over all
systems and folds the result into the galaxy data. The **bold** overlay is read
from the live SDK menu at runtime.

## Acceptance criteria

- **AC1** — All star systems are listed; a system can be selected to reveal the
  warp points within it.
- **AC2** — The user can select one of those warp points to "set course"
  (UI-only; no navigation).
- **AC3** — Systems and warp targets currently present in the live SDK-driven
  Set Course menu are styled **bold**.

## Out of scope (explicit)

- The warp action / actually navigating between systems.
- Persisting the "set course" selection across game launches.

## Validated findings (grounding probes, 2026-06-21)

These were verified empirically before writing this spec; the design depends on
them.

1. **The live SDK Set Course menu does not populate warp points today.**
   Root cause: our `STMenu.GetSubmenuW` (`engine/appc/characters.py:160`)
   auto-vivifies a submenu on lookup, so the SDK's `if pSystemMenu:` guard at
   `sdk/Build/scripts/Systems/Utils.py:67` treats every system as "already
   exists" and **skips the warp-point population loop** (Utils.py:78-100). Real
   Appc `GetSubmenuW` returns existing-or-NULL. This is the most likely reason a
   prior attempt was "not functional at all".
2. **Making `GetSubmenuW` strict (existing-or-`None`) fixes it and is low risk.**
   With the strict change, registering a system builds the full
   `system → warp-point` subtree, and **104/105 menu tests still pass**. The one
   failure is `tests/unit/test_characters.py::test_menu_get_submenu_w_auto_vivifies`,
   a unit test that explicitly pins the old auto-vivify behaviour (not a
   functional regression).
3. **All systems register headlessly.** Running every system's `CreateMenus()`
   with the strict fix: **35 system dirs, 32 have `CreateMenus()`, all 32
   succeed (0 failures), 95 warp points total** (e.g. Albirea 3, Alioth 8,
   Ascella 5). This makes the offline baker feasible.
4. **Warp-point labels need `SetClass_MakeDisplayName`.** Today
   `App.SetClass_MakeDisplayName` is an unimplemented stub, so warp-point labels
   come through as `<App._NamedStub 'SetClass_MakeDisplayName()'>`. It must be
   implemented for readable labels (needed by both the baker and the live
   overlay).
5. **The galaxy identity helpers already exist on `main`.**
   `engine/appc/sky_projection.py` already defines `load_sector_model`,
   `_MODEL_PATH`, `_MEMBER_TO_PARENT`, `system_id_for_set`, `vantage_for_set`
   (lines 13-43). Extraction into a dedicated module is a pure move.
6. **The panel already receives the live menu.** On `main`, a Set Course click
   routes through `CrewMenuPanel.on_set_course(widget)` →
   `SettingCoursePanel.open(course_menu=widget)`, so the panel already holds the
   live Set Course `SortedRegionMenu`. Its `_children` are the active per-system
   menus; with fix (1) their `_children` are the active warp points.

## Architecture

Three data sources, five components, built in phases.

- **All systems** ← galaxy JSON `sector_model.json` (34 systems, `{id,position}`).
- **All warp points for every system** ← new baked catalog (folded into
  `sector_model.json` as a `warp_points` list per system).
- **Bold/active overlay** ← the live SDK Set Course menu at runtime (the
  `course_menu` the panel already holds).

System identity is reconciled across all three via `system_id_for_set`
(lowercase, trailing-digit strip, member→parent map) so a live menu label
`"Vesuvi"`, a catalog key, and a galaxy id `"vesuvi"` all line up.

### Component A — Engine fix (makes the SDK menu populate)

**A1. `STMenu.GetSubmenuW` → strict.** Change `engine/appc/characters.py:160`
to return `self._submenus.get(str(label))` (existing-or-`None`), matching real
Appc. Update `tests/unit/test_characters.py::test_menu_get_submenu_w_auto_vivifies`
to assert strict semantics (lookup of an absent submenu returns `None`; the
explicit `AddChild`/create path still works). Audit `Bridge/*MenuHandlers.py`
and `MissionLib.py` callers for any genuine reliance on auto-vivify; the covered
menu paths (helm/crew/science/XO/engineer creation, m1basic init, globals
reset) already pass strict, so no functional caller is expected to break, but
the audit is part of the task.

**A2. Implement `App.SetClass_MakeDisplayName(setName)`** to return a
human-readable label. Behaviour: look up the set name in the Systems
localization (`data/TGL/Systems.TGL`) if available; otherwise a deterministic
formatted fallback (insert a space before a trailing run of digits, e.g.
`"Vesuvi4" → "Vesuvi 4"`). Must be a real string, never a stub, so labels render
and so the baker and live overlay produce identical labels for the same set.

### Component B — Galaxy helper extraction

New module `engine/appc/sector_model.py` that **owns the galaxy data**:

- Move `_MODEL_PATH`, `_MEMBER_TO_PARENT`, `load_sector_model`,
  `system_id_for_set`, `vantage_for_set` out of `sky_projection.py` into it.
- `sky_projection.py` imports those names from `sector_model` and keeps only the
  projection math. Update the one other caller (`engine/host_loop.py` ~1943,
  `sp.load_sector_model()`).
- Add `display_label(system_id) -> str`: title-cased display name with a small
  override map for the awkward cases (`xientrades → "Xi Entrades"`,
  `omegadraconis → "Omega Draconis"`, `tauceti → "Tau Ceti"`, `deepspace →
  "Deep Space"`); `multi*` scaffolding ids are excluded from the user-facing
  list by the panel (helper exposes a predicate or the panel filters).
- Add a loader for the warp-point catalog (Component C): `warp_points_for(system_id)
  -> list[{"id","label"}]`, reading the `warp_points` folded into the model
  (empty list when absent).

Pure move + additive helpers; existing `sky_projection` tests must stay green.

### Component C — Warp-point catalog (offline baker)

New tool `tools/bake_set_course_catalog.py`:

- Builds an isolated game/Helm/Set-Course menu (as in the grounding probe:
  `HelmMenuHandlers.CreateMenus()` under a minimal `Game/Episode/Mission`), with
  the strict `GetSubmenuW` (A1) in effect.
- Enumerates every `sdk/Build/scripts/Systems/<Name>/<Name>.py` that defines
  `CreateMenus()` (32 today), calls each, tolerating per-system failures
  (log + skip; today 0 fail).
- Walks the resulting Set Course tree → for each system node:
  `galaxy_id = system_id_for_set(system_label)`, warp points =
  `[{"id": <stable id>, "label": <MakeDisplayName label>} for child in node]`.
  The stable `id` is the warp-point display label slugged (labels are unique
  within a system); the live overlay matches on the same `(system_id, label)`.
- **Folds** the result into `engine/appc/sector_model.json`: each matching
  system gains a `"warp_points": [...]`. Systems whose `system_id_for_set` does
  not match any galaxy id are **logged** (so an override can be added) and their
  warp points are still emitted under the normalized id.
- Coexistence with `tools/bake_sector_model.py`: both bakers must **preserve**
  each other's data — `bake_sector_model.py` is updated to carry forward any
  existing `warp_points` when it rewrites systems from `poc/map.json`, and this
  baker only adds/refreshes `warp_points`. Re-running either in any order yields
  a consistent file.

The committed `sector_model.json` (with `warp_points`) is the runtime artifact;
the baker is not run at game start.

### Component D — Two-level panel (`SettingCoursePanel`)

Replace the placeholder body. Each `render_payload`:

- **Systems (left):** all galaxy systems from `sector_model` (excluding
  `multi*`), sorted by `display_label`. A system is `active` (bold) if its
  galaxy id matches a system in the live `course_menu` tree (normalize each live
  system label via `system_id_for_set`).
- **Selected system → warp points (right):** the warp points for
  `selected_system` from the catalog (`warp_points_for`). Each warp point is
  `active` (bold) if a live warp-point child under the matching live system node
  has the same label. A system with no catalog warp points shows an empty right
  column.
- **Selection state:** `selected_system` and `selected_warp` are panel-local and
  reset on each `open()` (not persisted — out of scope).

Events (routed by `PanelRegistry`, prefix stripped):

- `select-system:<system_id>` — set `selected_system`, clear `selected_warp`.
- `select-warp:<warp_id>` — set `selected_warp` (UI-only "set course"; AC2).
- `cancel` — close (existing).

Snapshot payload (snapshot-cached, mirroring the current panel):

```json
{
  "visible": true,
  "selected_system": "vesuvi",
  "systems": [{"id": "vesuvi", "label": "Vesuvi", "active": true}, ...],
  "warp_points": [{"id": "vesuvi-4", "label": "Vesuvi 4", "active": true,
                   "selected": false}, ...]
}
```

The panel keeps holding `course_menu` from `open()`; reading it each render
keeps the bold overlay live as the mission changes the menu.

### Component E — CEF assets

- `index.html`: the `#setting-course-panel` body becomes a two-column layout
  (systems list | warp-points list) inside the existing `cp-modal` chrome.
- `setting_course_panel.js`: `setSettingCoursePanel(state)` renders both lists;
  system rows fire `dauntlessEvent('setting-course/select-system:<id>')`, warp
  rows fire `setting-course/select-warp:<id>`. `active` → bold class; `selected`
  → highlight class. All labels HTML-escaped (the existing `escapeHtmlSC`); the
  data-attribute pattern already in the file is used for ids in onclicks.
- CSS: a two-column rule (reuse `cp-*` chrome; add `.sc-col` / `.sc-row--active`
  bold / `.sc-row--selected`). The centred-modal container rule already includes
  `#setting-course-panel`.

## Data flow

```
sector_model.json (systems + baked warp_points)
        │  load_sector_model / warp_points_for / display_label
        ▼
SettingCoursePanel.render_payload ──► setSettingCoursePanel(...) ──► CEF two columns
        ▲
        │  active overlay (bold): system_id_for_set on live labels
course_menu (live SDK Set Course tree, held from open())
```

## Testing

- **A1:** a test that registers a system (e.g. Vesuvi) against a real
  `HelmMenuHandlers.CreateMenus()` and asserts the live tree has
  `system → warp-point` children; the full menu suite stays green; the pinning
  test is rewritten for strict semantics.
- **A2:** `SetClass_MakeDisplayName` unit tests — localized hit and formatted
  fallback (`"Vesuvi4" → "Vesuvi 4"`), always a real `str`.
- **B:** `sector_model` unit tests (load, `system_id_for_set`, `display_label`
  overrides, `warp_points_for` present/absent); existing `sky_projection` tests
  still pass after the move.
- **C:** baker unit/integration test — runs the bake into a temp file, asserts
  ≥30 systems and ~95 warp points with real labels, asserts unmatched-id logging,
  and asserts `bake_sector_model` preserves `warp_points`.
- **D:** panel unit tests with a fabricated `course_menu` — full systems list +
  `active` flags; `select-system` populates warp points; warp `active` overlay;
  `select-warp` records UI-only selection; empty-warp system; reset on `open()`.
- **E:** JS render verified manually in-game (handoff); `node --check` on the JS.

## Phases (one spec, sequenced; review gate between)

1. **Phase 1 — Engine fix (A1 + A2).** Standalone, regression-tested. The live
   SDK menu now populates warp points with real labels.
2. **Phase 2 — Galaxy helper + catalog (B + C).** Data layer: extraction +
   baked `sector_model.json` with `warp_points`.
3. **Phase 3 — Panel + CEF (D + E).** The user-facing two-level menu.

Each phase ends with an independently testable deliverable; later phases consume
earlier ones.

## Risks / notes

- The strict `GetSubmenuW` is a change to a shared menu primitive. Mitigation:
  the audit in A1 + the existing menu suite (helm/crew/science/XO/engineer) as a
  regression gate; the one pinning unit test is the only expected change.
- System-id reconciliation may surface labels that don't normalize to a galaxy
  id (e.g. unusual system names). The baker logs these; fix by extending the
  override map / `_MEMBER_TO_PARENT`. Not expected to block (Vesuvi-class names
  normalize cleanly).
- Warp points only carry **labels** through the live menu (the region id passed
  to `SortedRegionMenu_CreateW` is not stored by our stub), so the active
  overlay matches by `(system_id, label)`. Both catalog and live use the same
  `MakeDisplayName`, so labels align by construction.
