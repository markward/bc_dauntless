# Perf Tier 1 — no gameplay change, no visible change

**Date:** 2026-11-08. **Source:** the overnight perf hackathon,
`docs/superpowers/spikes/2026-11-08-overnight-perf-hackathon.md` on branch
`spike/perf-hackathon` (not on main; read it with `git show`). Read its
"Ranking for proper implementation" (Tier 1), sections 3, 5, 8 and 10 first.

## 1. Intent

The spike showed that eight ideas, none of which change gameplay or the
picture, together cut whole-process CPU at vsync by 27% in exterior combat
(1.68 → 1.23 cores) and 28% on the bridge, and 4K GPU by ~27–32% (Debug,
`engine.dev_missions.combat_stress`, 64 ships). This work lands each of them as
**proper engine code**: a real design per idea, tests, documented cadences.

The spike code is a reference only. Do not cherry-pick it, and never bring
`engine/spike_flags.py` over. No `DAUNTLESS_SPIKE_*` switch survives, and no
new env switch is added unless an existing dev toggle already fits.

**Anti-goals.** A visible HUD stutter or lag a player would notice; a contact
that stays on the list after it died, cloaked or left the player's set; any change to the
rendered image beyond what the format change makes invisible; any gameplay
behaviour change; any memory leak across mission swaps.

**Out of scope:** bloom/flare at 1/4 res, AO reuse, pause scene hold, nebula
resolution, render scale (Tier 2); AI cadences and the catch-up cap (Tier 3);
native render-CPU items (Tier 4); CEF zero-copy (`OnAcceleratedPaint`) — noted
as a follow-up only, because it needs CEF's GPU lockdown
(`native/src/ui_cef/cef_app.cc`) lifted.

## 2. The items

### 2.1 HUD: contacts on the sensor sweep, panels change-driven

**Contacts** (`engine/host_loop.py:_pump_contacts`, `engine/appc/perception.py`,
`engine/appc/target_menu.py`). Today `perceived_by(player)` + `set_contacts` +
`ResetAffiliationColors` run every frame.

- **Membership and verdicts** (which ships are rows; perceivable / targetable;
  affiliation colour) are re-derived on the player's sensor sweep cadence
  (`sensor_contacts`, `sweep_period_s`, BC 1.0 s game time) **and immediately
  when an event lands that changes them** (Mark: "we are fine to handle event
  driven stuff when it lands"): a ship destroyed / out of action, cloak or
  decloak, a ship entering or leaving the player's set, the player changing
  set (warp, hand-off), player swap, target change, mission regrouping
  (`ResetAffiliationColors` callers). The builder finds which of these are
  real posted events and which need a direct hook; an event that is NOT posted
  (see `docs/reference/engine/event-emitter-gaps.md`) must not be relied on.
  Also immediate (*my call*): an identification commit
  (`sensor_contacts._identify_one`, the single commit point), so a row's
  caption never trails the reticle's `shows_identity`, and a medium
  entry/exit that flips `subsystems_targetable`.
- **Range and cloak-bubble crossings are NOT immediate**: a ship crossing
  sensor range keeps or lacks its row until the next sweep (≤ 1 s). Accepted:
  it is the lag Mark accepted for everything not event-driven, and it matches
  BC's own 1 s sweep.
- **Distances** on every row are refreshed every frame from positions, without
  re-running detection.
- `can_detect` writes a per-(observer, target) hysteresis latch
  (`perception.py` docstring). Calling it less often from the UI is fine
  (the latch is idempotent set membership, and the per-tick firing chokepoint
  keeps feeding it), but the builder must confirm the UI and the lock guard
  (`clear_undetectable_player_lock`) cannot disagree in a way the player sees:
  a lock break must also rebuild the list.

**Panels** — radar (`sensors`), crew menu (`crew-menu`), player ship
(`ship-player`), weapons (`weapons`). Use the existing `PanelRegistry`
machinery (`poll_interval_s`, `mark_due`, visibility flip, event dispatch):

- Input, open/close and visibility flips draw on the next frame (already true).
- Known discrete state changes `mark_due` the panel at once (target change,
  alert level, power, a weapon firing/reloading — the builder settles the
  list per panel).
- Continuous data gets a cadence: radar 20 Hz; crew menu, ship and weapons
  10 Hz. Damage cannot be purely event-driven
  (`ET_SUBSYSTEM_*` are never posted, emitter-gap #15), which is why the
  cadence is a floor, not a fallback.
- Cadences live on each panel's `poll_interval_s` with a named constant and a
  docstring saying why, as `TargetListView` does.

**CEF upload** (`native/src/ui_cef/`):

- `on_paint` becomes the default `UploadMode`; `always` stays selectable via
  the existing `DAUNTLESS_CEF_UPLOAD` (an existing switch: keep it).
- **Dirty-rect upload.** `DauntlessCefClient::OnPaint` currently ignores
  `dirtyRects` and memcpys the whole bitmap; the composite uploads the whole
  surface. Instead: OnPaint copies only the dirty rects into the bitmap and
  accumulates them (union list) until the next upload; the composite uploads
  only those regions (`GL_UNPACK_ROW_LENGTH` sub-image uploads), then clears
  the list. Falls back to one full upload when the rects cover most of the
  surface (builder picks the threshold and the max rect count), and on any
  (re)allocation or size change. Rect merging and the fallback rule are a
  header-only, GL-free helper with its own C++ unit test, like
  `cef_upload_policy.h`.

### 2.2 R11G11B10F for the HDR scene and bloom targets

`HdrTarget` colour, `HdrMsaaTarget` colour (same format, so the resolve stays a
same-format blit) and the bloom mip chain move from `RGBA16F` to
`GL_R11F_G11F_B10F`. Keep `RGBA16F` wherever alpha is read (nebula buffer)
**or wherever a negative value must survive** (R11G11B10F is unsigned).

- **The dev nonfinite probe** reads the main HDR target itself
  (`host_bindings.cc`, `g_hdr_target->color_texture()`): `opaque.frag`'s
  `u_nan_debug` writes a cause code into alpha, and it needs −Inf/negatives.
  *My call:* while the probe is on, the main HDR target and its MSAA twin are
  (re)allocated as RGBA16F; off, R11G11B10F. The probe is dev-only, so the
  realloc on toggle costs nothing in production.
- **Other `HdrTarget` users** — `g_viewscreen_hdr` (viewscreen RTT) and
  `g_dof_target` — switch too unless the audit finds an alpha or negative
  read (DOF may keep circle-of-confusion in alpha; then it stays RGBA16F). Before switching, audit every writer and reader of these targets:
alpha reads, alpha-dependent blending into them, negative values, `glReadPixels`
/ blit format assumptions, screenshot / dev readback paths. The audit result goes
in the plan. Mark checks bright scenes and nebulae in game by running main
against the branch's worktree; no runtime format toggle is added (Mark,
2026-11-08).

### 2.3 Glow updates off the per-frame path

`subsystem_glow.SubsystemGlow.update` runs per ship per frame from
`_sync_instance_transforms`. Pushes are already change-only, except the impulse
(and warp) gain, which changes every frame while moving for two reasons: a
`sin(now)` pulse, and the throttle ease (`_eased_frac`, an exponential with
`IMPULSE_EASE_TAU`, stepped by each frame's dt). Design:

- Move both into the renderer, evaluated from the game clock it already uses
  for glow flicker. *My call:* the ease is pushed as (start value, target,
  start time) and evaluated in closed form, `target + (start − target)·
  exp(−(t − t0)/τ)`, with today's settle-to-0 snap. For a target held
  constant this equals today's per-frame integration up to float rounding
  (the product of `exp(−dtᵢ/τ)` is `exp(−Σdt/τ)`), so it is not a visible
  change. The pulse is pushed as (base, amplitude) on change. Then the push is
  truly change-only.
- AI ships run the state poll (`glow_state`, condition, commanded throttle) at
  20 Hz, staggered across ships; the player every frame. Consequence,
  accepted (Mark's brief: "on change or at 20 Hz"): an AI ship's damage
  flicker, disabled/destroyed blow-out and throttle ease start up to 50 ms
  late, because the edge time is the detection time. No new "when it
  changed" timestamp is added to the damage path.

### 2.4 Rock-field early-out (exact)

`engine/rocks/far_tier.field_strength_at` returns 0 before any position work
when there is no tile field pushed and the viewed system has no field sources.
Cache the per-system source lookup and invalidate it with whatever already
invalidates field sources (system change, mission swap, `reset_mission_state`).

### 2.5 GC freeze after load

At the end of every mission load: `gc.collect(); gc.freeze()`. Every teardown
calls `gc.unfreeze()` **before** tearing the old mission down, or every object
of the old mission stays alive for good. *My call* on "every": boot, the dev
picker's `swap_mission`, `engine/core/mission_change.change()` (campaign
mission/episode changes in the warp tunnel; direct `LoadEpisode` /
`LoadMission` route through it), and Quick Battle End/Restart. Best done as
one helper pair called from each path, with a test that each path calls it.
The collect inside the warp tunnel is accepted: the tunnel is already the
loading screen. Only the game's load paths freeze; `reset_mission_state` and
the test suite's per-test reset never do.

The builder must check, and the plan must record:
- `weakref.finalize` callbacks (they queue native-mirror frees; see
  `docs/reference/architecture/test-suite-memory.md`): a load-time object that
  becomes garbage mid-mission is not collected while frozen. Confirm nothing
  depends on that collection during a mission (e.g. native mirror slots, ship
  counts), and that a long mission's growth is bounded.
- That the per-test memory budget is unaffected (no freeze under pytest).

### 2.6 Motion blur skipped when the camera is still

Skip the motion-blur pass when the CPU-side reprojection of the centre and four
corners (exactly as `motion_blur.frag` computes it) moves less than 0.5 px.
Pure function with a unit test; the threshold is a named constant.

### 2.7 Hum allocator at ~10 Hz

`hum_allocator.update` (nearest-4 reconcile) runs at ~10 Hz instead of every
frame, plus immediately when a humming ship dies or leaves, so a dead ship
never keeps humming. Hum positions/gains (driven elsewhere) stay per frame.

### 2.8 Hoist hot local imports, plus a guard

Move function-local imports in hot per-frame / per-tick paths to module level
(the spike's cProfile list: `frames.frame_of`, `sensor_media.medium_unknown`,
`profile.locate`, `far_tier.*`, `attached_sources`, …), except where a local
import breaks a real cycle (leave those, with a comment). Add a test that fails
on a function-local `from X import` inside a listed set of hot modules
(parse, don't grep; an exemption is a comment marker on the line). The
radiation sample cache is **dropped** (−1 to −4%, not worth it).

## 3. Branches

All branch off `main`, merge into `int/2026-11-08-01` with no gate, and one
merge gate runs when Mark says to merge into main.

| Branch | Items | Main files |
|---|---|---|
| `perf/hud-cadences` | 2.1 contacts + panels | `host_loop.py`, `perception.py`, `target_menu.py`, `engine/ui/*_panel.py` |
| `perf/cef-dirty-rects` | 2.1 CEF upload | `native/src/ui_cef/` |
| `perf/hdr-r11g11b10f` | 2.2 | `native/src/renderer/{hdr_target,hdr_msaa_target,bloom_pass}.cc` |
| `perf/glow-off-frame` | 2.3 | `subsystem_glow.py`, glow shader + bindings |
| `perf/field-early-out` | 2.4 | `engine/rocks/far_tier.py` |
| `perf/gc-freeze` | 2.5 | `host_loop.py` load/swap |
| `perf/mblur-still-skip` | 2.6 | `host_bindings.cc`, motion blur |
| `perf/hum-10hz` | 2.7 | `host_loop.tick_audio`, `hum_allocator.py` |
| `perf/hoist-imports` | 2.8 | many; **last**, after the others merge into int |

## 4. Tests, docs, measurement

- Focused tests only, per CLAUDE.md "Test gate". No gates, no whole suites.
- Each cadence added goes in `docs/reference/engine/perf-cadences-and-latency.md`
  (contacts, the four panels, glow state poll, hum allocator); the CLAUDE.md
  perf-cadences row's count is updated to match.
- `perf-register.md`: P-10 closes when `on_paint` becomes default.
- **Measurement** waits for Mark's go-ahead to launch (headless too). Then each
  branch is measured against main with `~/Documents/dauntless-perf/hk-tools/`
  (`run4.sh W=<worktree>`, `batch4.sh`, `psum.py`, `score.py`, `cmp.py`):
  headless frames scored as `loop − cef.pump` (M-7), `HEADLESS=0` for vsync
  utilisation, `"fullscreen": false` in the worktree's `settings.json`, Debug
  against Debug. Results become new signals in `perf-register.md`.
- **Mark checks in game:** HUD responsiveness (2.1) and the HDR format on
  bright scenes and nebulae (2.2).

## 5. Left to the builder

Exact event list per contact/panel trigger; the per-panel `mark_due` hooks;
the dirty-rect fallback threshold; the 20 Hz glow stagger; where exactly load
and swap end; the hot-module list for 2.8.
