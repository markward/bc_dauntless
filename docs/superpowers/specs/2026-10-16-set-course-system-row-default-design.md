# Set Course system row — label plots the system default, caret opens regions

Status: merged to local main (90676d3a). Live-verified by Mark 2026-10-16.

## Problem

In E1M1 the Helm Set Course menu offers "Vesuvi". In Dauntless a click on it
only expanded the row into Vesuvi Dust Cloud / Geki Colony / Haven Colony, with
nothing to say which one the mission wants. In BC a click on most of that row
plots the system's outermost region (Haven); only a thin strip at its left
edge opens the list.

## What BC does (SDK evidence)

- `Systems/Utils.py:24,76` — `CreateSystemMenu(sSystemName, sSystemRegion,
  *lSystems)`: the second argument is the "Region file that you go to if you
  select the menu". The system `SortedRegionMenu` carries it AND has one child
  per region. In every stock multi-region system it is the highest-numbered
  region (Vesuvi6, Alioth8, Itari8 …).
- `Utils.py:89-95` — single-player focuses the last child; multiplayer makes
  the system `SetNotOpenable`, so the row can only act on its default.
- Missions move the default with `SetRegionName` on the system node:
  `Episode4.py:187`, `E4M5.py:1438`, `E4M6.py:2046,2095`, each paired with
  `LinkMenuToPlacement(<system>, None, …)` — a placement on the system row,
  which only makes sense if selecting that row is itself a destination.
- E1M1 puts the E1M2 mission name on the system node (`E1M1.py:3067`) and its
  tutorial arrow on "Vesuvi" itself (`E1M1.py:3603`), never on a region.

A mission can only add or remove WHOLE systems (no campaign script builds a
region row itself). It steers a player to a non-default region only by
dialogue + objective text, a region-level `SetPlacementName` (E6M3 Savoy 1,
E6M4 Tezle 1), or by plotting the course itself (`SetDestination` on the warp
button, 8 missions). About 20 campaign missions test for the player in a
non-default region (E3M5 Belaruz 2, E6M3 Savoy 1, E8M1 Cebalrai 1 …), so the
region list must stay reachable from the drop-down.

## Design

- `SortedRegionMenu.SetRegionName` / `GetRegionName` implemented (were silent
  stubs, heatmap rank 170). They share the field `GetRegionModule` reads.
- `crew_menu_panel._is_course_system`: a `SortedRegionMenu` with a region,
  children, and openable. Its snapshot node is a `"menu"` with
  `sets_course: true` and `chosen` when its default is the plotted course.
  `click:<id>` on it calls `on_course_set(default)`; `expand:<id>` opens it.
- `crew_menus.js`: a `sets_course` row is split — the caret
  (`.crew-menu__caret--split`, full-height, own hover, hairline) fires
  `expand:`; the rest of the row fires `click:`. Other submenus still expand
  from anywhere on the row.
- Star map: `_outermost_module` (double-click a star) reads the live menu's
  system default before the offline bake, so `SetRegionName` applies there
  too; an arrow on a system with regions marks its default region row.

## Known gaps

- `ClearInfo` is still a no-op. Whether BC's `ClearInfo` resets a
  `SetRegionName` override when a later mission re-runs `CreateMenus` is not
  known; for now an override persists.
- The Helm tooltip's "Destination :" line (`BridgeHandlers.FindCourseButton`)
  still never resolves: `SortedRegionMenu_GetRoot` is a stub and `IsTypeOf`
  returns 0. Unchanged by this work.
- E1M1's own route to the Vesuvi offer (after docking at Starbase 12) is not
  driven headlessly; E3M2 (Vesuvi offered from the start) and E4M6's
  `OpenCebalrai` cover the same code end to end.

Tests: `tests/unit/test_crew_menu_set_course_override.py`,
`tests/unit/test_st_widgets_region.py`, `tests/ui/test_crew_menu_system_row_js.py`,
`tests/ui/test_star_map_panel.py`, `tests/integration/test_set_course_dropdown_missions.py`.
