# Sector Cartography — Findings & Approach

Captures the investigation into inferring and rendering a 3D map of BC's
"Maelstrom" sector, the data-model findings it surfaced, and the architectural
implications for a future procedural-starfield / dynamic-warp overhaul.

The working proof-of-concept lives in [`poc/`](../poc/) (throwaway spike;
`poc/README.md` has run instructions). This doc is the durable record.

---

## 1. The core question

> Can we infer a 3D map of the sector and where each system sits in space?

**Yes — but it is *inference*, not *extraction*.** BC stores **no galactic
coordinates**. There is no star-map data structure, no `{system: x,y,z}` table.
The "Maelstrom" sector is fiction invented for the campaign. So any 3D map is
*constructed* from relational signals, and artistic liberty is legitimate
because the true positions were never authored.

What BC *does* store, richly: per-system **local** 3D coordinates (suns,
planets, moons, player start, stations — all in game units within one set).

---

## 2. BC's spatial data model (the key insight)

A clean three-way separation runs through everything:

| Layer | Defined in | Persistent? | Role |
|---|---|---|---|
| **System** | `Systems/<Name>/` | yes | the reusable **stage**: sky, sun, planets, lights, nav points |
| **Mission** | `Maelstrom/Episode*/` | per-run | the **content**: ships, stations, objectives placed onto a stage |
| **Backdrop** | system `LoadBackdrops()` | yes | **scenery**: starsphere + nebula spheres |

Consequences:

- **Systems are the atomic navigable unit**, grouped into named "systems" only
  by an authored menu (see §3). Regions within a system are free-floating sets,
  each with its own origin, sun, and sky — even the *suns differ* between two
  regions of the same named system (they're independently authored scenes).
- **Celestial bodies are scenery + plot anchors, never physics objects.** Across
  all 26 campaign missions there is essentially **zero** direct orbit/land/fly-
  into interaction with planets, moons, or stars (see §7). "Orbit" in the
  scripts means ships orbiting *stations/ships*; the one "sun" mission (E8M2) is
  a Cardassian **Solarformer** *device*; "planet" references are largely debris
  (`"Planet Fragment N"`). This is the fact that makes an ambitious render/scale
  overhaul low-risk.
- **The sky is geometry, not metadata.** `StarSphere_Create()` /
  `BackdropSphere_Create()` produce camera-anchored sphere objects added to the
  set; the engine renders them like any object. A station placed into a set
  inherits that set's sky for free.

---

## 3. The inference signal stack

Positions are produced by a force-directed 3D layout fusing four real signals
against fixed real-star anchors:

1. **Menu grouping** — `CreateSystemMenu(...)` arg lists in `Systems/<Sys>/<Sys>.py`
   are the **authoritative** system→region membership (an *authored declaration*,
   strictly stronger than name-matching). Provides topology, not metric.
2. **Nebula co-visibility** — `BackdropSphere` textures shared across systems.
   Each carries a **bearing** (forward vector) and **apparent size** (span), so a
   shared nebula is a triangulation constraint. Systems sharing ≥2–3 backdrops
   are over-determined (the Artrus/Cebalrai/OmegaDraconis keystone shares 3).
3. **Mission co-occurrence** — systems loaded together in one mission imply
   proximity. Edge weight uses **inverse mission-frequency (idf)** so the
   universal Starbase 12 hub (in all 26 missions) is suppressed.
4. **Real-star anchors** — systems named after catalogued stars, **pinned at
   their true RA/dec/distance**; the fiction hangs off that skeleton.

The crude PoC layout uses (1)+(2)+(3) as springs with (4) hard-pinned; a
rigorous bundle-adjustment using the bearing data is the natural upgrade.

---

## 4. Real stars & the Local Bubble

Several systems are named after **real catalogued stars**:

| System | Real star | Distance |
|---|---|---|
| Alioth | ε Ursae Majoris | ~83 ly |
| Cebalrai | β Ophiuchi | ~82 ly |
| Ascella | ζ Sagittarii | ~88 ly |
| Omega Draconis | ω Draconis | ~76 ly |
| Tau Ceti (= DryDock + Starbase 12) | τ Ceti | ~12 ly |
| Albirea | Albireo (β Cygni) | ~430 ly (outlier) |
| Artrus* | Arcturus (α Boötis) | ~37 ly (*speculative) |

They form a ~150 ly bubble in the **Orion Arm / Local Bubble** — not a charted
"sector", just a pocket of the solar neighbourhood. Two findings:

- **Real geometry ≠ game adjacency.** Cebalrai and Omega Draconis share nebulae
  in-game (so "neighbours"), but are ~84 ly apart in different sky directions.
  Pinning to real coordinates *stretches* the keystone cluster ~2.5×. The
  inferred layout is therefore **more faithful to the campaign's intent** than
  real coordinates would be; the real anchors are best treated as a skeleton +
  Easter eggs.
- The map is badged **"Orion Arm · Stellar Cartography"** for flavour.

---

## 5. Entity taxonomy (what the map renders)

- **Systems** — bracket-reticle markers + labels. Real-star anchors render
  green with a catalogue subtitle; **bases** (menu-less region loaders:
  Starbase 12, DeepSpace, DryDock) render cyan with a station ring;
  **starbases** render a gold **Starfleet delta** (Tau Ceti).
- **Nebulae** — two distinct kinds, *not* the same thing:
  - `MetaNebula` (Vesuvi, Belaruz, MP) — **local gameplay** volumes with real
    colour, `visibilityGu`, `sensorDensity`, and `damage` (Vesuvi = 150 hull/s).
    Rendered small (intra-system features).
  - `BackdropSphere` `treknebula*` — **distant scenery** shared across systems,
    merged when co-observed, named (The Draconis Veil, Auric Remnant, Vermilion
    Shroud). Tinted from the **real TGA mean colour**.
  - A backdrop can be folded into a local nebula it *is* seen from afar (the
    `treknebula2/3` backdrop == the Belaruz nebula).
- **Star clouds** — `galaxy*` textures, reinterpreted as **regions of denser
  stars** (future starsphere density driver). Small non-selectable 3-star icons.
- **Mission routes** — faint connectors from co-occurrence (hub spokes excluded).
- **Nav points** — per region, each carrying `distFromStarGu`/`distFromStarKm`.

**Appearance metadata** is attached to every nebula/galaxy for a future
procedural-starfield pass: SDK spec for MetaNebulae; TGA-derived `meanColor`,
`palette`, `coverage` (density proxy), `luminance` for backdrops.

### Synthetic parent systems
`SYNTHETIC_SYSTEMS` folds menu-less locations under one star — DryDock +
Starbase 12 become child regions of **Tau Ceti** (DryDock's planet is literally
"Tau Ceti Prime"; both share the blue-white sun). Extensible config.

### Stations: static vs mission-spawned
- A *few* stations are **static** (in `_S.py`): e.g. Vesuvi 5/6 FedOutposts —
  persistent fixtures.
- *Most* — including **Starbase 12 itself** and all Cardassian
  outposts/stations — are **mission-spawned** via `CreateShip` and don't exist
  until a mission places them.
- Non-Federation presence exists: **Cardassian** CardStation/CardOutpost/
  CardStarbase, plus a neutral BiranuStation.
- **Stations get destroyed / change state** across the campaign (Haven colony in
  E1M2, BiranuStation in E2M6), and BC carries **persistent cross-mission
  state** (`Maelstrom.Maelstrom` globals like `bGeronimoAlive`). So a faithful
  map could reinterpret the campaign as an *evolving sector with memory* — a
  canonical post-war snapshot or a timeline. (Deferred.)

---

## 6. Rendering decision: web/CEF, not native GL

The map should **not** be a native GL pass like the Ship Property Viewer.

- The Ship Property Viewer is native GL because it renders the **real ship NIF**
  through the engine's shaders. The star map renders **stylized procedural
  primitives** (dots, labels, patches, lines) — *no game geometry, no asset
  pipeline*. The justification for native GL is absent.
- CEF + three.js wins on iteration speed (edit + refresh vs C++/cmake rebuild),
  text/font rendering, and fits the existing `PanelRegistry` / `ui-cef` infra
  (CEF cost already accepted). The PoC already validates the look/interaction.
- **Keep the Ship-Property-Viewer *interaction model*** (frozen modal from the
  pause menu, orbit camera, click-to-pick, `frame_dt=0`) — just host it in CEF.
- **One thing to validate**: WebGL under CEF off-screen rendering would be the
  first such panel here; spike it for clean compositing + framerate.

---

## 7. Feasibility: procedural starfield + realistic scale + warp

Mission-interaction audit (26 missions): celestial bodies are **backdrop +
plot anchors**, with **near-zero physics interaction**. This is the green light.

- **Procedural / dynamic starsphere — low risk.** No mission depends on backdrop
  pixels. Preserve only the **MetaNebula hazard volumes** and the rough
  **positions of plot-anchor bodies**.
- **Realistic scales + dynamic warp — feasible via a two-tier model** (which BC
  half-implements already):
  - **Sector/warp layer** = realistic-scale navigation between systems —
    *this is the star map*. Warp = load destination system's scene (Set Course
    already does this; the warp graph is the co-occurrence edges).
  - **Local combat scene** = the existing compressed per-system play space,
    **kept as-is**. Missions run here unchanged.
- **Mission implications** — most untouched. The minority needing care: nebula
  hazards, plot-anchor bodies (Haven colony, defend-the-planet), the Solarformer
  climax, ~10 `ProximityCheck` missions — all "object at local position, event
  fires", so they survive a sector-scale overhaul.
- **Hard parts (honest):** intra-system *realistic* travel (BC never did it; no
  mission requires it — optional polish), **floating-origin precision** at large
  scale, and body **LOD**.
- **Suggested staging:** (1) procedural backdrop → (2) sector/warp layer
  (graduate the map into the live nav interface) → (3) realistic intra-system
  scale, gated behind floating-origin work.
- Procedural sky shipped on `feat/procedural-starfield` — Modern VFX toggle `procedural_sky_set_enabled`, default on.
- Map-driven starsphere **implemented (pending live A/B verification)** — the sky is the sector model projected from the current system's vantage (procedural toggle on); stock BC on toggle off. The procedural fields on `aggregate_for_renderer` (proc_kind/color/coverage/seed) are now used only on the unmapped-system fallback path.

The PoC's real value: it surfaced the **stage / content / scenery** separation
that makes this overhaul safe. Gameplay is *not* coupled to render scale here —
the usual blocker in space sims is largely absent.

---

## 8. Open follow-ups

- **Station / faction layer** — detect station `CreateShip` calls, attribute to
  host system via the set-variable → `GetSet()` mapping, classify faction
  (Federation / Cardassian / neutral), tag static vs mission-spawned.
- **Canonical-state reinterpretation** — post-war snapshot vs evolving timeline
  (§5), using destruction flags + persistent globals.
- **Rigorous triangulation** — bundle-adjust the bearing/span data instead of the
  crude force layout.
- **Graduate the PoC** into a CEF dev panel (§6) after the WebGL-in-CEF spike.
