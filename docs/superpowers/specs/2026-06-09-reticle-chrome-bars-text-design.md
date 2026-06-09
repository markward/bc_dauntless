# Target Reticle: Chrome Colour, Fore/Aft Bars & Text — Design

**Date:** 2026-06-09
**Status:** Approved design, pending implementation plan
**Builds on:** `2026-06-09-subsystem-target-reticle-and-camera-design.md` (iteration 1, merged)
**Area:** targeting HUD — renderer (GL reticle pass) + CEF text overlay

## Problem

Iteration 1 shipped the faithful BC reticle (full-ship corner box + subtarget
crosshair) as a native GL billboard pass. Three elements from BC's reticle are
still missing (see the reference screenshot in the iteration-2 request):

1. **Colour** — the reticle renders in the raw white texture colour; it should
   be tinted **orange** to match the UI chrome.
2. **Fore/aft alignment bars** — vertical bars down the left and right of the
   box, each a thin yellow line with a green arrow that shows the target's
   bearing along the player's fore–aft axis.
3. **Text** — the target/subsystem name above the box and a
   `"<range> km / <speed> kph"` line below it.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Render path | **Hybrid**: keep the GL pass for all graphics (box, crosshair, bars, arrows); add a CEF text overlay for the two labels. This project has no GL font system; all HUD text is CEF. |
| Bar metric | Arrow height = the target's **bearing along the player fore–aft axis**: `dot(player_forward, normalize(target − player))`. +1 fore → arrow top; 0 abeam → centre; −1 aft → bottom. Both bars share the value. |
| Bottom-line speed | **Target's absolute speed** = `|target.GetVelocity()| × GUPS_TO_KPH`. |
| Name source | Locked **subsystem** name when a subsystem is locked, else the target **ship** name. |
| Tint method | **`texture × tint` multiply**. All three textures are white/grey (verified), so white art → solid tint and the grey `TargetArrow` keeps its shading as green shading. |

## Assets (verified present)

| Asset | Size | Use |
|---|---|---|
| `game/data/target.tga` | 16×16 white | corner box (existing) |
| `game/data/subtarget.tga` | 8×8 white | crosshair (existing) |
| `game/data/Icons/tilevertline.tga` | 4×8 white | side-bar line → tinted yellow |
| `game/data/Icons/TargetArrow.tga` | 64×32 grey/white | fore/aft arrow → tinted green |

## Colour palette

From the config-panel chrome gradient (`configuration_panel.css:41`,
`rgb(216,94,86)→rgb(216,132,80)`):

| Element | Colour | RGB (0–1) |
|---|---|---|
| Corner box | orange `#d88450` | (0.847, 0.518, 0.314) |
| Crosshair | yellow | (1.0, 0.86, 0.0) |
| Side-bar lines | yellow | (1.0, 0.86, 0.0) |
| Arrows | green | (0.30, 0.85, 0.30) |
| Name text | orange `#d88450` | — |
| Distance text | pale | `#ffd` |

All are named constants (C++ `constexpr` / Python / CSS) tunable in review.

## Component 1 — GL tint + non-square billboards

**`target_reticle.frag`:** add `uniform vec4 u_tint;` →
`vec4 t = texture(u_tex, v_uv); if (t.a < 0.01) discard; frag = t * u_tint;`.

**`target_reticle.vert`:** generalise the scalar `u_size_world` to
`uniform vec2 u_half_extent;` so bars can be tall and thin:
`offset = (u_camera_right * a_corner.x * u_half_extent.x + u_camera_up * a_corner.y * u_half_extent.y)`.
Corners/crosshair pass equal x/y; bars pass a narrow x and tall y. The existing
vertical-flip negate and `u_uv_flip` mirroring are unchanged.

**`pipeline` / shader:** unchanged wiring; the accessor stays
`target_reticle_shader()`.

## Component 2 — Bars & arrows in `TargetReticlePass`

**Struct** (`target_reticle_pass.h`) gains:
```cpp
bool  has_bars      = false;
float bar_alignment = 0.0f;   // [-1,+1], +1 = fore, -1 = aft
```

**Textures:** `ensure_textures()` also loads `tilevertline.tga` (bar) and
`TargetArrow.tga` (arrow) via the existing `load_tga`.

**Draw (after the box, before/after the crosshair), only when `has_bars`:**
- Two **bars**: `tilevertline` billboards at the box's left and right edges
  (`ship_center ± cam_right · ship_radius`), `u_half_extent = (bar_w, ship_radius)`
  spanning the box height, tinted yellow. (`bar_w` = small constant world width
  derived from a px size, like the crosshair.)
- Two **arrows**: `TargetArrow` billboards, one per bar, tinted green, at the
  same x as each bar, vertical offset
  `v_frac = clamp(0.5 + 0.5 * bar_alignment, 0, 1)` mapped onto the bar span:
  `arrow_center = ship_center ± cam_right·ship_radius + cam_up · ship_radius · (2·v_frac − 1)`.
  Constant on-screen px size (reuse `world_for_px`).

Each draw sets `u_tint`; box/crosshair tints move from implicit-white to the
palette constants above.

## Component 3 — Fore/aft metric (Python)

`TargetReticlePayload` (`engine/ui/target_reticle.py`) gains
`bar_alignment: float = 0.0`. In `build_target_reticle`, when a target exists:
```python
fwd = player.GetWorldRotation().GetCol(1)          # ship forward (world)
d   = target_center - player_center                # TGPoint3
n   = d / |d|                                       # guard |d|>eps
bar_alignment = clamp(fwd.x*n.x + fwd.y*n.y + fwd.z*n.z, -1.0, 1.0)
```
`has_bars` is true whenever the reticle is visible. `player_center =
player.GetWorldLocation()`.

## Component 4 — CEF text overlay

**New module `engine/ui/reticle_text.py`** — pure Python:
```python
def build_reticle_text(player, camera, viewport):
    """Return {visible, name, line2, name_xy, line2_xy} or {visible: False}.
    camera: object exposing eye()/target/up()/fov_y_rad/near/far (a thin adapter
    over the gameplay camera params host_loop already computes). viewport: (w,h)."""
```
- `name` = `player.GetTargetSubsystem().GetName()` if a valid subsystem is
  locked (reuse `_valid_subsystem`), else `target.GetName()`.
- `line2 = "%.2f km / %.0f kph" % (dist_gu*GU_TO_KM, speed_gu*GUPS_TO_KPH)` where
  `dist_gu = |target_center − player_center|`,
  `speed_gu = |target.GetVelocity()|`.
- Positions: project the box top/bottom **world** points
  (`ship_center ± up · ship_radius`, `up` = camera up) to screen via the
  existing `project(world, cam, viewport)` (`ship_property_viewer.py:209`,
  returns top-left-origin px + a `visible` flag). `name_xy` sits above the top
  point; `line2_xy` below the bottom point. If either projects with
  `visible == False` (behind camera / off-clip), return `{visible: False}`.

**CEF side:** new `native/assets/ui-cef/js/reticle_text.js` exposing
`setReticleText(state)` that positions two absolutely-placed `<div>`s
(`#reticle-name`, `#reticle-dist`) at the given pixel coords (translate, centred),
or hides them when `!state.visible`. Markup in `index.html`, styling
(orange name, pale distance, no pointer events, text-shadow for legibility) in a
new `css/reticle_text.css`. Registered like the other overlays.

**Driving it:** imperative from `host_loop` (in lockstep with the GL reticle, not
via the pull-model `PanelRegistry`, because it needs the live camera + viewport):
`engine/renderer.py` gains `set_reticle_text(payload)` which calls
`_h.cef_execute_javascript("setReticleText(" + json.dumps(payload) + ");")`
(same exec path `PanelRegistry` uses), guarded to no-op headless.

## Component 5 — Host wiring & data flow

`host_bindings.cc::set_target_reticle` gains a `bar_alignment` arg (and
`has_bars`); `engine/renderer.py::set_target_reticle` passes
`payload.bar_alignment`. In `host_loop`'s per-frame block (next to the existing
`r.set_target_reticle(...)`):
```python
r.set_target_reticle(build_target_reticle(player))      # now carries bar_alignment
cam = _ReticleCamAdapter(eye, target, up, director.fov_y_rad, 1.0, 5000.0)
r.set_reticle_text(build_reticle_text(player, cam, viewport))
```
SPV-open branch also clears the text (`r.clear_reticle_text()` →
`setReticleText({visible:false})`). `viewport` = the CEF view size host_loop
already knows. The camera adapter wraps the same `(eye, target, up, fov, near,
far)` passed to `r.set_camera`, so GL graphics and CEF text share one camera and
align by construction (the iteration-1 "match by construction" discipline).

```
player + gameplay camera
   ├─ build_target_reticle ─→ r.set_target_reticle ─→ TargetReticlePass (box, crosshair, bars, arrows)
   └─ build_reticle_text   ─→ r.set_reticle_text   ─→ cef_execute_javascript("setReticleText(…)")
        (project() with the same camera ⇒ text aligns with the GL box)
```

## Edge cases

- No target → reticle hidden (existing) **and** `set_reticle_text({visible:false})`.
- No subsystem locked → name = ship name; bars/box still shown.
- Target behind camera / off-clip → `build_reticle_text` returns `visible:false`
  (text hidden); GL graphics already clip naturally.
- `|target − player|` ~ 0 → `bar_alignment` defaults to 0 (abeam), no divide.
- SPV open → both reticle halves cleared (existing for GL; added for text).

## Testing

**Pure-Python** (focused subsets only — full suite OOMs):
- `bar_alignment`: target dead ahead → ~+1; abeam → ~0; dead astern → ~−1
  (build a pitched/rolled player so `GetCol(1)` is exercised).
- `build_reticle_text`: name = subsystem when locked else ship; `line2`
  formatting (`"38.29 km / 2 kph"` from known GU inputs); `visible:false` when
  no target or projected behind camera.
- Projection alignment: a known camera + a world point yields the expected
  screen px via `project()` (guards the GL/CEF agreement at the Python level).

**Visual** via `./build/dauntless --developer`: orange box, yellow crosshair &
bars, green arrows tracking fore/aft (fly past a target and watch the arrows
sweep top→bottom), name + range/speed text anchored to the box.

## Scope

**In:** `u_tint` + `u_half_extent` shader changes; bars/arrows + 2 textures in
the pass; `bar_alignment` through struct/binding/payload; `reticle_text.py`;
`reticle_text.js` + css + index.html; `set_reticle_text`/`clear_reticle_text`
wrappers + host wiring; the camera adapter; tests above.

**Out:** moving the box/crosshair to CEF; a GL font renderer; reticle in
non-tracking edge views beyond what iteration 1 already covers; retiring the
subsystem-pin pass's latent v-flip.

## Open implementation details (resolve during planning/build)

- Exact bar width / arrow px sizes and the bar's vertical inset — tuned by feel
  in `--developer`.
- Whether the camera adapter is a tiny local class or a shared dataclass reused
  by future HUD projection needs.
- Confirm `index.html`/overlay registration point for the new JS/CSS matches the
  existing sensors/target-list registration.
