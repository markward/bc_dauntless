# Sector Map — Proof of Concept (throwaway)

A standalone spike to test the **Stellar Cartography** sector-map idea *outside* the
engine/build. Nothing here touches `native/`, `engine/`, or the build. Delete the
whole `poc/` folder when we graduate the concept into a real dev-mode CEF panel.

## What it does

1. **`extract_map.py`** mines real signals from `sdk/Build/scripts/`:
   - system → region grouping (`CreateSystemMenu` arg lists)
   - region nav points (`Waypoint_Create` + placed planets/moons/stations)
   - nebula co-visibility (`BackdropSphere` `treknebula*` textures + apparent span)
   - hazard nebulae (`MetaNebula_Create` + `SetupDamage`, real colour/radius)
   - star clouds (`BackdropSphere` `galaxy*` textures): areas of denser stars,
     their own 3D entity with a `size` value. Rendered as a small non-selectable
     3-star icon. Intended to later drive starsphere density variety.
   - **appearance metadata** (for the future procedural-starfield pass), on every
     nebula + galaxy:
     - `metanebula` source (Vesuvi etc.): the SDK spec — tint colour, internal/
       external textures, `visibilityGu`, `sensorDensity`, true `spheresGu` shape,
       plus a `damage` block (hull/shield per sec) for hazards.
     - `backdrop` source (treknebula*/galaxy*): derived from the actual TGA via
       Pillow — `meanColor`, dominant `palette` (5), `coverage` (density proxy),
       `luminance`, `resolution`, plus `apparentSpan` (angular size in-sky).
     TGA analysis needs the (gitignored) `game/` install; it degrades to `null`
     swatches without it, so the extractor still runs on a clean checkout.
   - **real-star anchors** (`REAL_STARS`): systems named after catalogued stars
     (Alioth, Cebalrai, Ascella, Omega Draconis, Albireo, Arcturus*, Tau Ceti)
     pinned at their true RA/dec/distance positions. *Arcturus≈Artrus is speculative.
   - **synthetic parent systems** (`SYNTHETIC_SYSTEMS`): fold menu-less locations
     under one star — e.g. DryDock + Starbase 12 become child regions of **Tau Ceti**
     (DryDock's planet is "Tau Ceti Prime"). Flagged `starbase` -> Starfleet delta.
   - **distance-from-star** (`distFromStarGu`/`distFromStarKm`) on every nav point
     and child region, measured from the region's sun waypoint (BC's in-scene
     backdrop distance, not an astronomical orbit).
   - **mission routes**: system co-occurrence across `Maelstrom/Episode*/`
     missions, idf-weighted so the universal Starbase 12 hub is suppressed.

   It then runs a **crude 3D force-directed layout** — nebula co-visibility and
   mission co-occurrence pull systems together, real-star systems are held fixed,
   and everything else settles around that skeleton — and writes `map.json`
   (+ `map.js`, a `window.SECTOR_MAP` global so the viewer works from `file://`).

   > This is the *first-cut* layout, NOT the rigorous bearing-triangulation /
   > bundle-adjust solve. That's a later upgrade behind the same `map.json` contract.

2. **`stellar_cartography.html`** renders `map.json` with three.js (CDN): flat-shaded
   scene, ground grid + drop-lines for depth, bracket-reticle system markers with
   labels, hatched nebula patches (diagonal warning bands on hazards). Orbit to
   rotate; click a system to focus and list its nav points.

## Run

```bash
uv run python poc/extract_map.py      # regenerate map.json / map.js
open poc/stellar_cartography.html      # or just double-click it in Finder
```

Needs internet on first view (three.js loads from CDN). Real-star anchors render
with green reticles + catalogue subtitle. Toggles: "show mission routes" (faint
co-occurrence connectors, on by default) and "show multiplayer maps" (the
`Multi*` / QuickBattle sets, hidden by default).

## Known rough edges (PoC, expected)

- Positions are inferred and stylised — not canonical BC geometry.
- Multiplayer region display names are ugly (`MRegion5`) and some MP nebulae duplicate.
- Click-to-zoom *into* a region's nav markers is not built yet (v2); v1 only lists them.
