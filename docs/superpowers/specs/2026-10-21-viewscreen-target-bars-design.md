# Viewscreen target bars — design

**Date:** 2026-10-21 · **Branch:** `feat/viewscreen-target-bars` (worktree `.claude/worktrees/viewscreen-target-bars`) · **Status:** built, live-verified by Mark 2026-10-21 (rev 3: name top-left, distance/speed top-right), merged to main
**Follows:** `2026-10-20-target-zoom-fit-design.md` (the viewscreen now frames the whole target; its §4 deferred this overlay)

## 1. Intent

When the bridge viewscreen shows a target, the player can't tell what it is:
there is no reticle and no readout on the screen. Add a header band and a
footer band to the viewscreen picture carrying the same facts as the exterior
reticle: the target's name on top, its distance and speed below, and the band
colour telling friend from foe.

BC reused its corner-box reticle on the viewscreen. Mark: "with the benefit of
hindsight this was not necessary because the target always filled the
viewscreen anyway (so why the box?)" — so no box, just the two bands.

## 2. What Mark decided

| Question | Decision |
|---|---|
| Look | **Option C** of the mockups: solid bands edge to edge across the top and bottom of the picture, rounded only at the corners that face the picture (top band: bottom corners; bottom band: top corners). |
| Where drawn | **Inside the viewscreen render-to-texture** (the 640×360 RTT), so the bands are part of the screen: they tilt, foreshorten and move with the viewscreen as the bridge camera looks around or zooms. Not a flat HUD overlay. |
| How text is drawn | **A generated bitmap font** (an atlas image of Antonio glyphs plus their metrics), drawn by a small GL pass. Not a second CEF page, not FreeType at runtime (the native-UI/FreeType thread is a shelved dead end). |
| Top band text | The target's **name**. |
| Bottom band text | `"<range> km / <speed> kph"` — the reticle's line, same numbers. |
| Band colour | The **target list's affiliation colours**: friendly blue `rgb(80,112,230)`, enemy red `rgb(216,43,43)`, neutral pale yellow `rgb(255,255,175)`, unknown grey `rgb(128,128,128)` (`native/assets/ui-cef/css/target_list.css:15-18`). No affiliation text. |

Mark confirmed these readings of my guesses ("nothing" wrong):

- The top band shows the **ship's** name even when a subsystem is locked (the
  reticle switches to the subsystem; the viewscreen frames the whole ship).
- An **unidentified** contact shows its placeholder (`"Unknown 2"`), never its
  real name, on the grey band — as the target list does.
- When a mission points the viewscreen at something other than the player's
  target (`MissionLib.ViewscreenWatchObject`), the bands describe **what is on
  screen**.
- **No bands** during a hail (comm feed) or on the plain forward view.
- Text is **white on blue, red and grey, black on the pale yellow** band.

## 2a. Revision after the first live look (2026-10-21) — SUPERSEDES the bands

Mark's live look (screenshot, E1M2-style hail of USS Zhukov): the bands work as
designed, but the design doesn't — from the captain's chair the **bottom of the
viewscreen is hidden behind the helm/ops consoles**, so the footer showed only a
clipped sliver ("2.45 km / 1414 kpl"). New layout, Mark's words then his
correction ("left aligned to the corner"):

| Element | Decision |
|---|---|
| Position | A two-line block **anchored to the TOP-LEFT** of the viewscreen picture, inset so the screen's curved bezel can't clip it. Left-aligned. |
| Background | **None.** No bands. |
| Line 1 | A small **filled circle in the affiliation colour** (the same four colours), then the **target name**. |
| Line 2 | **Smaller** text under the name: `DST: <range> km  SPD: <speed> kph` — the reticle's numbers, relabelled. |
| Text colour | **All white.** |

My calls, accepted ("otherwise good"):
- Line 2 starts under the name (aligned with the name's left edge, not the circle).
- Line 2 ≈ 70% of line 1's size, drawn from the **same** atlas scaled down — no second atlas.
- A **soft dark shadow** under all text (like the HUD reticle's CSS text-shadow) so white stays readable over explosions and pale planets. A shadow, not a background.
- Everything else unchanged: placeholder name + grey dot for unidentified contacts; nothing on hail/forward/no target; drawn into the RTT; the 0.85 channel cap (the dot and the white text).

Where §2 and §4 below describe bands, band colours, rounded corners and the
"km / kph" footer, this section wins; the data path (§4.1), font (§4.2) and
lifecycle are unchanged.

### Revision 3 — the detail line moves to the top right

Mark, after the second live look: "can you move the speed and distance line to
the top right? keep the font size the same" — then, correcting a
baseline-aligned proposal: "not the same baseline. put them the same distance
from the top of the screen".

Rule: the `DST/SPD` line (still 0.7 scale) is **right-aligned** to the picture's
right inset (24 px @640) and **top-aligned** with the name — its CAP TOP is at
the same y as the name's (inset 18 px below the top), so the two baselines
differ. The dot and name are unchanged; the name is ellipsised to stop
`kVsReadoutNameDetailGapPx` (16 px @640) short of the detail line. At 640x360
for "DST: 2.45 km  SPD: 1414 kph": name baseline 318, detail baseline 325,
detail x 416.

## 3. Existing pieces (verified 2026-10-21 on main `d98aa88cd`)

- **The target feed.** `engine/host_loop.py:_viewscreen_scene_feed(player,
  forward_fov, dt)` resolves the watched object (`mode.GetAttrIDObject
  ("Target")`, player target or mission watch) and returns the camera; the
  native side renders it when `g_scene_source.active`
  (`native/src/host/host_bindings.cc:~2030`). Precedence comm > scene >
  forward is decided by `_select_viewscreen_source`.
- **The draw slot.** The RTT block in `host_bindings.cc` (~2013-2057) renders
  the scene into `g_viewscreen_hdr` (`kViewscreenRttW/H` = 640×360), then
  `ViewscreenStaticPass` alpha-blends the hail "snow" over the bound target —
  the exact pattern a bars pass follows (`native/src/renderer/
  viewscreen_static_pass.{h,cc}`). The bridge pass then samples
  `g_viewscreen_hdr->color_texture()` onto the viewscreen mesh.
- **The reticle's numbers.** `engine/ui/reticle_text.py:build_reticle_text`
  computes the name (Unknown placeholder via `sensor_contacts.shows_identity`
  / `unknown_labels.placeholder`), the surface distance
  (`target_menu.surface_gu_to`) and speed (`implements(target,
  "GetVelocity")`), formatted `"%.2f km / %.0f kph"`.
- **Affiliation.** The target list colours each row by
  `target_menu.resolve_affiliation(ship, mission)` (`FRIENDLY / ENEMY /
  NEUTRAL / UNKNOWN` from the mission's groups), reported as `UNKNOWN` while
  the contact is unidentified (`STSubsystemMenu.GetAffiliation`).
- **The font.** `native/assets/ui-cef/fonts/Antonio-Regular.ttf` (OFL, licence
  in `native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`). Pillow 12 is in the
  dev environment (used by `tools/sprites/prep.py`).
- **Project assets.** Native code resolves project-owned assets through
  `set_project_asset_root` (e.g. `native/assets/textures/scuff_normal.tga`),
  never through the BC `game/` root.

## 4. The design

### 4.1 Data (Python, per frame)

A pure builder — *Claude's call:* `engine/ui/viewscreen_bars.py:
build_viewscreen_bars(player, target) -> dict` — returns
`{visible, top_text, bottom_text, band_rgb, text_rgb}`:

- `visible` False when there is no live target on the feed.
- `top_text`: the Unknown placeholder for an unidentified `ShipClass`, else
  `target.GetDisplayName()` (never the subsystem name).
- `bottom_text`: the reticle's exact format and numbers. Share the distance /
  speed / placeholder logic with `reticle_text.py` (extract a helper both use)
  rather than copying it — the reticle and the viewscreen must never disagree.
  The extraction is a pure refactor: the reticle's existing tests are its
  guard and must pass unchanged.
- `band_rgb` from the affiliation string via the four colours in §2;
  `text_rgb` white, black for NEUTRAL.
- The target is the one the scene feed resolved (watched object), not
  `player.GetTarget()`. The feed function hands it on (or exposes it); a
  second resolution in another place would let them drift. That object is
  always the ship/object, never a subsystem: our subsystem lock lives
  separately on the ship (`GetTargetSubsystem`), and the feed reads
  `player.GetTarget()` / the mode's `Target` attr. Distance is to the
  **object's** surface (`surface_gu_to(target, player)`), never a subsystem.
- **Non-ship objects** (planets, stations, rocks, waypoints a mission
  watches): name = `GetDisplayName()`; distance via `surface_gu_to`, which
  already handles planets; speed 0 when the object has no `GetVelocity`
  (`implements`, as the reticle does). Affiliation exactly as the target list
  colours its row: `UNKNOWN` while a `ShipClass` contact is unidentified
  (`STSubsystemMenu.GetAffiliation`), else
  `engine/appc/target_menu.resolve_affiliation(target, mission)` with the
  current mission (it reads only `GetName()` and the mission's groups, so it
  is safe on non-ships). Its `UNKNOWN` → grey.
- **Lifecycle** (*Claude's call*): the bars are set every frame the scene
  feed returns a camera and cleared every frame it does not (hail, forward,
  off, dead target, mission swap, bridge hidden — all of which already route
  through that one branch). The native pass is only called on the scene-
  source path, so a stale state can never draw on a hail; no extra clear
  path is needed.

The host loop pushes the dict to native each frame the scene feed is active,
and clears it when the feed is not (hail, forward, off) — following the
pull-model: read SDK state, never write it.

### 4.2 Bitmap font (generated asset)

- *Claude's call:* `tools/fonts/gen_bitmap_font.py` renders Antonio with Pillow
  at one size into an atlas PNG + a JSON of per-glyph metrics (advance,
  bearing, atlas rect, line height/ascent), committed under
  `native/assets/fonts/` (e.g. `viewscreen_antonio.png` / `.json`).
- Glyph set: printable ASCII 32-126 (names are ASCII in stock BC; a missing
  glyph draws as nothing and advances by a space — never crashes).
- GENERATED: never hand-edited; a drift test regenerates and compares (the
  repo's pattern: `tests/tools/test_rock_catalogue_drift.py`,
  sprites `prep.py`). Generation must be deterministic.
- Size the source glyphs for the RTT, not the window: the bands live in a
  640×360 texture, so a cap height of roughly 60-70% of the band height is the
  target (*Claude's call*, tune live). The glyph pixel size is **one named
  constant in the generator**; live tuning means changing it and
  regenerating (the drift test follows the committed output). Single-channel
  coverage, sampled linearly with mipmaps, is the first try (*Claude's
  call*); a distance field is the fallback only if Mark sees shimmer on the
  bridge.

### 4.3 Bars pass (C++)

- *Claude's call:* `native/src/renderer/viewscreen_bars_pass.{h,cc}`, a sibling
  of `ViewscreenStaticPass`, with its own small shader pair. Draws, over the
  bound viewscreen target:
  1. two band quads, solid colour, rounded inner corners (an SDF rounded-rect
     in the fragment shader is fine);
  2. the two strings, centred horizontally in their bands, as atlas quads.
- Called in the RTT block **only on the scene-source path**, after the scene
  and after the static overlay, so the text is never hidden by snow.
  Saves/restores GL state like the static pass.
- Data arrives through a binding (*Claude's call:*
  `set_viewscreen_bars(visible, top, bottom, band_rgb, text_rgb)` /
  `clear_viewscreen_bars()`), mirrored in `engine/renderer.py` with the
  headless no-op pattern used there.
- Band height and corner radius are named constants (*Claude's call:* band
  ≈ 10% of the RTT height, as in mockup C; radius ≈ 18 px at 640 wide).
- **Colour must read the same as the target list.** Verified path: the
  bridge pass draws the viewscreen mesh **unlit** — `col = base.rgb ×
  u_viewscreen_brightness` (`shaders/bridge.frag:~614`, the `u_unlit`
  branch; brightness is the ViewOn/ViewOff ramp, 1.0 when settled) — into the
  main HDR target, which then goes through the ordinary post chain with its
  ≈0.9 bloom threshold. So the RTT value IS what reaches the post chain: write
  the band colour straight into the RTT, but scale it so **no channel exceeds
  a named cap below the bloom threshold** (*Claude's call:* 0.85 — pale yellow
  `(1,1,0.69)` would otherwise bloom). The bands fade with ViewOn/ViewOff and
  flash with warp like the rest of the picture — correct, they are part of it.
  The judge is Mark's live look against the target list; the cap is the one
  tuning knob.

### 4.4 Text fit

A name too wide for the band is cut at the band with an ellipsis
(*Claude's call*; the 640-px band fits ~40 Antonio characters, longer than any
stock name).

## 5. Non-goals

- No corner box, crosshair or fore/aft bars on the viewscreen.
- No affiliation text, hull/shield bars or subsystem readout.
- No change to the exterior reticle's look or behaviour (it only gains a
  shared helper).
- No bands on hail or forward views.
- No CEF, no FreeType, no runtime font rasterising.

## 6. Anti-goals

- The viewscreen and the reticle showing different distance/speed or name for
  the same target.
- A real name leaking for an unidentified contact.
- Bands blooming, glowing or colour-shifting away from the target list's.
- Bands appearing during a hail or with no target.
- Any visible change to the main view or the exterior HUD.

## 7. Verification

- **Focused tests only** (never a whole suite or the gate — CLAUDE.md):
  - the Python builder: each affiliation → colour, Unknown placeholder, ship
    name with a subsystem locked, mission-watched target, hidden with no
    target; bottom text identical to the reticle's for the same target;
  - the font tool: deterministic output, drift test;
  - the native pass: a `FrameTest`-style GL test renders into a viewscreen-
    sized target and reads back pixels — band colour at a band pixel, scene
    untouched mid-picture, text pixels present in the band, nothing drawn
    when cleared.
- **Live check by Mark:** E1M2 start — target a debris rock (neutral yellow?
  whatever the mission's groups say), Starbase 12, Haven; QuickBattle with
  friends and enemies (blue/red); an unidentified contact (grey "Unknown N");
  a hail (no bands); look around the bridge and zoom on an officer (bands stay
  on the screen surface).

## 8. Left to the builder

Exact file names, glyph size and atlas layout, shader details, how the scene
feed hands the resolved target to the builder, test file layout.
