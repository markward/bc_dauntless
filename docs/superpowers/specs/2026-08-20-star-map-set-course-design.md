# Star Map — 3D Set Course Interface (design)

Graduates the throwaway stellar-cartography proof of concept (`poc/`) into a
live in-game interface: a 3D sector map, rendered in a windowed panel, that
replaces the two-column list in the Helm → Set Course modal.

Background and the data-model findings behind the map live in
[`docs/sector-cartography.md`](../../sector-cartography.md). This spec covers
only the in-game interface.

---

## 1. What this is

Helm → Set Course currently opens `SettingCoursePanel`: a 640×420 CEF modal
with systems on the left and that system's warp points on the right. Clicking a
warp point sets the course.

This replaces the left column with a **3D map of the sector**, rendered by a
native GL pass into the modal's rectangle. The right column stays. The
mechanism underneath is untouched.

**This is a presentation swap, not new navigation work.** The selection
contract already exists and works end to end:

```
dispatch_event("set-course:<id>") → _module_for(id) → on_course_set(module)
  → App.SortedRegionMenu_GetWarpButton().SetDestination(module)
  → announce_course_set()          # Kiska's "ready to warp" ack
  → player presses Helm "Warp" → on_warp_engage → the warp spine
```

The new panel satisfies exactly that contract: produce a destination
set-module, call `on_course_set`, close.

---

## 2. Rendering: native GL, not WebGL

`docs/sector-cartography.md` §6 recommended CEF + three.js and explicitly
argued against native GL. **That recommendation is superseded**, because a
constraint landed after it was written.

CEF here is deliberately software-rasterized —
[`cef_app.cc:16-17`](../../../native/src/ui_cef/cef_app.cc) forces
`--disable-gpu` and `--disable-gpu-compositing`, because CEF's GPU process
conflicts with the GLFW-managed GL context (shared IOSurface allocations on
macOS). [`cef_lifecycle.cc:181-188`](../../../native/src/ui_cef/cef_lifecycle.cc)
records the consequence: re-rastering the full page on the CPU cannot finish in
time and delivers partial frames — the HUD flicker bug. A continuously
animating WebGL canvas dirties its whole region every frame, which is that
pathology by construction.

(Not tested: whether a WebGL context can be created at all under those
switches. Modern Chromium often requires `--enable-unsafe-swiftshader` to keep
WebGL alive with the GPU off. The repaint cost stands either way.)

The alternative is already a shipped pattern here, not an invention:
[`target_reticle_pass.cc`](../../../native/src/renderer/target_reticle_pass.cc)
draws reticle geometry in GL while
[`reticle_text.py`](../../../engine/ui/reticle_text.py) projects world points to
screen and [`reticle_text.js`](../../../native/assets/ui-cef/js/reticle_text.js)
positions the text as CEF DOM. The star map uses the same split.

**The POC's three.js is visual reference only. None of it ships.**

---

## 3. Windowed, not full-screen

The map renders into the modal's rectangle, over the live 3D scene. The game
and the helm menu stay visible around it. The simulation is **not** frozen —
`frame_dt` is untouched, matching stock BC (crew menus never stopped time) and
today's Set Course behaviour.

`letterbox_pass.cc:60-77` is the working precedent for drawing into a sub-rect
of FBO 0: save viewport and scissor box, `glScissor` to the target rect, draw,
restore. The map pass runs at the same point in the frame — **after the post
chain resolves, before `ui_cef::composite()`** — so CEF chrome composites on
top of it. Because the CEF layer is already alpha-blended over the scene, the
panel leaves a **transparent hole** where the map belongs.

No render-to-texture is required.

**The pass takes its rect from the panel.** Aspect ratio, projection and
click-picking all derive from that rect, so modal dimensions are a CSS value
plus one constant — a live-tuning knob, not an architectural commitment.

Starting footprint: **880×560** in CEF logical pixels (the view is 1280×720,
[`host_loop.py:6294`](../../../engine/host_loop.py)), giving the map roughly
640×520 beside a ~220px warp-point list. If growing symmetrically would cover
the helm menu — whose position is decided by `sdk_panel_positions.py` — offset
the modal rather than shrink it.

The map viewport is filled **opaque** dark. "Game visible" means around the
modal, not through it; a live scene behind the stars destroys their legibility.

---

## 4. Components

Three layers.

### `native/src/renderer/starmap_pass.{h,cc}` + shaders

Draws all geometry: star dots, bracket reticles, the course line, nebula and
star-cloud billboards, the faint grid and drop-lines, and the selection
highlight. Takes a camera, a viewport rect, and a scene buffer. **Knows nothing
about Set Course** — it draws positioned markers.

Exposed through `host_bindings.cc` as `starmap_set_enabled`,
`starmap_set_camera`, `starmap_set_viewport`, `starmap_set_scene`, reached from
Python through the `host_io` façade like every other pass.

### `engine/ui/star_map.py`

The counterpart to `ship_property_viewer.py`, and the only home for the map's
spatial logic: orbit camera state, world→screen projection (importing SPV's
existing `project`, as `reticle_text.py` already does), click-picking against
projected star positions, anchor resolution, and scene assembly from
`sector_model`.

Pure Python, no GL, no CEF — directly unit-testable, the same property that
made SPV's picking testable.

### `engine/ui/star_map_panel.py`

A `Panel` subclass named `star-map`. Emits the CEF payload (projected label
positions, the selected system's warp points, chrome state) and handles
`select-system:` / `set-course:` / `cancel`. Takes the same `on_course_set`
callback `SettingCoursePanel` does.

### CEF — `js/star_map.js`, `css/star_map.css`, an `index.html` section

System labels as absolutely-positioned DOM tracking projected coordinates,
clipped to the map rect; the warp-point list; header and cancel chrome; and the
transparent hole the GL pass draws into. No canvas, no WebGL.

### Wiring — `engine/host_loop.py`

- [`:6864`](../../../engine/host_loop.py) `on_set_course=` repoints from
  `setting_course_panel.open` to the map panel.
- Cursor-free ([`:2872`](../../../engine/host_loop.py)) and click-swallow
  ([`:7313`](../../../engine/host_loop.py)) logic already keys off
  `setting_course_panel.is_open()` and generalizes to the new panel.
- A block in the render section drives the pass from panel state, beside the
  SPV block, following `r.set_hologram_only_mode(...)` / `r.set_subsystem_pins(...)`.

---

## 5. Camera — fixed anchor

**The camera orbits the player's current system and that anchor never moves.**
Orbit on drag, zoom on scroll, nothing else.

Clicking a star **selects** it — highlight plus warp points in the side list.
It does **not** re-centre the camera.

This is the SPV's model (CLAUDE.md: *"the camera orbits the subsystem centroid
(no re-centring)"*), and it is the stronger design for a nav map rather than
merely the simpler one: with a fixed anchor every on-screen position is read
relative to you, so "which way is that, and is it further than the other one"
is answerable by looking. Re-centring destroys that, because after one click
the centre means nothing. It also removes a class of bugs outright — no focus
animation, no interrupted transitions, no "where did the camera end up" after
rapid clicks. The POC re-centres on click; this deliberately does not.

**Anchor-moving is not built at this stage** — not deferred behind a flag,
absent. If distant clusters prove hard to inspect, the likely fix is zoom range,
and that should be decided from a live run.

**Fallback.** The anchor needs the current system resolved from the player's
set via `sector_model.system_id_for_set(pSet.GetName())`. (Not `vantage_for_set`
— it returns a *position* and discards the id, which the "you are here" reticle
needs.) `system_id_for_set` falls back to a stripped-digits base name, so it can
return an id absent from the model, and in Deep Space, a multiplayer set, or
anything unmapped there may be no matching system at all. When
unresolvable: anchor on the sector centroid and **omit the "you are here"
reticle entirely**. A misplaced "you are here" on a nav map is worse than none.

**No distance readouts.** Inter-system positions are force-layout *inference*,
not canonical BC data. The spatial arrangement may be impressionistic; a
number in kilometres would present fiction as measurement.

---

## 6. Visual language

### The reticle means "a live relationship to the player right now"

Default is a bare dot plus label — most of the 34 systems. The bracket reticle
is reserved for three states, visually distinct from each other:

| State | Treatment |
|---|---|
| **You are here** | Bracket + inner ring, bright key colour. The marker the eye should find instantly. |
| **Course set** | Bracket + a **line drawn from the current system to it**. |
| **Mission-relevant** | Bracket in a distinct accent. No ring, no line. |

Everything static loses its POC bracket — starbases and real-star anchors get
dot styling at most, and nothing by default until they are missed.

Lines are reserved for the plotted course. The POC's 42 mission-route
connectors are deferred (§9), which is what frees lines to mean one thing: a
single line showing your standing order and how far it is.

Mission-relevance is today's bold overlay, read from the live SDK Set Course
menu, promoted from font weight to a reticle.

### Nebulae and star clouds

Existing treatment at **~50% opacity**. Star clouds keep the POC's small
non-selectable icons, also reduced.

One implementation detail, not a design change: the POC billboards use
`depthWrite: false` and can wash over stars in front of them. Draw order must
guarantee **star markers are never occluded** — that serves the legibility
complaint rather than adding a feature.

No hazard/ambient split. Uniform opacity reduction.

### Depth cues

A 3D point cloud with no ground reference is hard to read, and reserving
borders for meaning does not fix it. Keep a **faint** grid, and draw drop-lines
**only for reticled systems** — the depth cue follows the same "earns its
place" rule as the reticle. If it still reads as clutter live, removing it is a
constant, not a rewrite.

### Labels

All 34 by default, small, with emphasis on hover and on reticled systems.
Whether 34 simultaneous labels is legible or soup is a live-tuning question;
the levers — size, distance fade, label-on-demand — are all CEF-side, costing a
page refresh rather than a rebuild.

---

## 7. Data

**Deliberately almost no change.**

Systems already carry `id`, `position`, `module`, `warp_points`; display names
come from `display_label` via TGL. Nebulae and star clouds already carry
`position`, `radius`/`size`, `color`.

The only missing field is a **`name` on nebulae**, for labels. That is one
addition to `tools/bake_sector_model.py`.

⚠️ **`sector_model.json` has three consumers, not one.** Besides the Set Course
catalog it feeds the map-driven starsphere — the sky *is* this model projected
from the current system's vantage. Two separate bakers write the file
(`bake_sector_model.py`, `bake_set_course_catalog.py`), each preserving the
other's keys. The addition must be **additive**, and the re-bake verified
against `tests/tools/test_bake_sector_model.py`,
`tests/integration/test_bake_set_course_catalog.py` **and**
`tests/engine/appc/test_sky_projection_realmodel.py`. A careless bake is a
starsphere regression, not just a map one.

Everything richer in `poc/map.json` — regions, nav points, links, appearance
metadata, real-star anchors — stays out.

---

## 8. Error handling

Degrade visibly, never silently.

| Case | Behaviour |
|---|---|
| Current system unresolvable | Centroid anchor; no "you are here" reticle. |
| Warp point with `module is None` | Rendered visibly non-selectable, not dead-on-click. |
| Live-menu reconciliation miss | `dev_mode.log_swallowed` instead of the bare `except: pass`, so a missing mission reticle is diagnosable. |
| Stale native binary | Every `r.<binding>` call `hasattr`-guarded — the pattern damage decals use — so a map without a rebuilt renderer no-ops instead of raising `AttributeError`. |
| Mission swap / set change while open | Close and invalidate; the pending destination may no longer exist. |

Frame ownership is **not** a case: the map occupies a rectangle and never
competes with the rest of the frame, so the tactical HUD, orders row and
reticle text are untouched.

---

## 9. Scope

**In:** the pass, the Python controller, the panel, the CEF layer, the one bake
field, the Set Course rewiring.

**Out, deliberately:**

- Anchor-moving / click-to-focus (§5).
- Mission-route link lines, real-star green reticles, region fly-in — the POC's
  richer scene. A follow-up once the base reads well.
- Distance readouts (§5).
- Persisting the selection across launches.
- Anything in the warp path below `on_course_set`. `on_warp_engage`
  deliberately bypasses `WarpPressed`, whose camera and cinematic work is
  deferred to Warp Stages 2–3; that is unchanged and unaffected.

**`SettingCoursePanel` is not deleted in this change.** It stays in the tree and
constructible for a commit or two. Not ceremony: if the map has a bad first live
run, "cannot set a course at all" makes warp unreachable and blocks playtesting
everything downstream. Retire it in a follow-up once the map is verified live.

---

## 10. Testing

Four layers, in the order they catch things:

1. **Unit — `star_map.py`.** Projection, hit-testing, anchor resolution and its
   centroid fallback, scene assembly. No GL, no CEF.
2. **Unit — `star_map_panel.py`.** The `render_payload` idempotency contract
   (returns `None` when unchanged), event routing, and that `set-course:` calls
   `on_course_set` with the right module while an unavailable one does not.
3. **Integration at the host layer.** Enter where the game does — Helm → Set
   Course opens the map, selection reaches `SetDestination`. Entering below the
   host poller is a mistake this project has made before.
4. **ctest `FrameTest`** for `starmap_pass` if the geometry warrants it.

Merge gate is `scripts/check_tests.sh` — both suites, diffed against
`tests/known_failures.txt`. Never eyeball "pre-existing".

**What the tests cannot see, stated plainly:** none of the above says whether
the map *reads* well. Label legibility at 34 systems, the 50% nebula opacity,
whether the faint grid helps or clutters, orbit feel, and the 880×560 footprint
are all live-run questions. Expect a tuning pass after first launch. The levers
are deliberately split so most are CEF-side refreshes rather than C++ rebuilds.
