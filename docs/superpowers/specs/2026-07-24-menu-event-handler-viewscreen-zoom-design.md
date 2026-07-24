# MenuEventHandler port — bridge-camera zoom onto the viewscreen & speaking officers

**Date:** 2026-07-24
**Status:** Design approved, pre-implementation
**Depends on:** SP4 PositionZoom work (`engine/appc/character_position_zoom.py`, on `main`)

## 1. Problem

When a mission raises the viewscreen on a hailed character (e.g. E1M1's Admiral
Liu briefing), BC swings the bridge captain's camera to face the viewscreen and
zooms in ~2× so the viewscreen fills the window. Dauntless renders the hail feed
(Liu appears on the screen) but the **bridge camera never zooms** — the viewscreen
stays a small panel dead ahead.

### Root cause / RE mechanism (TIER-0, from the RE project)

The zoom is driven by `CharacterClass::MenuEventHandler @ 0x0066D450` — a handler
we currently stub. It fires when a bridge character is **engaged** (its talk-menu
is raised), which is how you "talk to" a bridge officer AND how a hailed character
on the viewscreen is presented. Steps (engage path):

1. Gate checks (menu-state present; veto predicate clear; `m_bMenuEnabled`; menu
   action flag; menu-state ready-bit; character not busy `IsStateSet(8)==0`).
2. Fetch the `"maincamera"` `ZoomCameraObjectClass` from the `"bridge"` set.
3. Compute look-at from the character's position-offset vec3 + `GetPositionLookAtName(loc)`.
4. Turn the character to face the captain (turn/gesture CharacterActions).
5. Read `GetPositionZoom(loc)`; if it returns the default sentinel, substitute a
   **hardcoded fallback**; store the result into the camera's `MinZoom`.
6. `UpdateViewFrustum` / `ToggleZoom(now)` to start the transition.

Exit path (disengage): un-toggle the zoom, `BridgeHandlers.DropOutOfManualFireMode`,
turn the character back.

The zoom itself is a **frustum / FOV narrowing, not a camera dolly** — the camera
does not translate toward the viewscreen; its FOV tightens (telephoto). In
`ZoomCameraObjectClass`:

- `UpdateViewFrustum`: scale = `bIsZoomed ? MinZoom : MaxZoom(=1.0)`; writes the
  frustum edges into the backing NiCamera. Smaller scale ⇒ narrower FOV ⇒ zoomed in.
- `ToggleZoom(t)`: flips `bIsZoomed`, marks dirty, rewinds the transition start so a
  mid-transition reverse resumes smoothly rather than snapping.
- `Update(t)` per-frame: `frac = clamp((t − start) / ZoomTime)`, interpolates scale
  between `MaxZoom` and `MinZoom`, rewrites the frustum, optional random shake.

**Viewscreen tie-in:** there is no special viewscreen code path — the person on the
viewscreen is just another character position. Hailed/remote characters `SetLocation`
a remote-set location (E1M1 Liu = `SetLocation("StarbaseSeated")`) with **no
`AddPositionZoom` entry**, so `GetPositionZoom` misses → the hardcoded fallback is
used. That fallback IS the ~2× viewscreen zoom; it is uniform across hails because
none author a bridge position-zoom. Bridge officers DO author per-station zooms
(`Kiska.AddPositionZoom("DBHelm", 0.45, "Helm")`), so they zoom by their own amount.

### Current Dauntless state

- The FOV-narrow zoom EXISTS: `_BridgeCamera.set_zoom_target(world, dt, snap,
  zoom_factor)` (`host_loop.py`) eases forward + narrows FOV, using an officer's
  `GetPositionZoom` (SP4).
- Its focus resolver (`host_loop.py` ~7074-7084) only selects (a) an
  `AT_WATCH_ME`/`AT_LOOK_AT_ME` target or (b) an officer whose **crew menu is open**.
  A **hailed character speaking during a cutscene selects nothing → no zoom.**
- `ZoomCameraObjectClass.LookForward` / `ToggleZoom` / `IsZoomed` / `Update` are
  `_LoudStub` no-ops (`engine/appc/bridge_set.py` ~141-146). The SDK calls fire but
  do nothing.

## 2. Scope

**Full MenuEventHandler port** (chosen over a viewscreen-only patch). Reconstruct
`CharacterClass::MenuEventHandler` faithfully as the single dispatcher that both the
officer talk-menu and the viewscreen hail feed into. The already-working officer
crew-menu zoom becomes one producer into this handler; the refactor must keep the
live-verified officer framing byte-identical.

**Architecture decision:** the zoom **state and FOV easing live on
`ZoomCameraObjectClass`** (most faithful to the RE). `_BridgeCamera` reads that
object each frame. The ad-hoc `set_zoom_target` / `_active_zoom_officer` resolver
is retired.

## 3. Design

### 3.1 Components (one job each)

**A. `ZoomCameraObjectClass` — real zoom state machine** (`engine/appc/bridge_set.py`).
Replaces the `_LoudStub` no-op surface. State:

- `_min_zoom` (target FOV factor for the current engagement), `_max_zoom = 1.0`,
  `_zoom_time`, `_is_zoomed` (bool), `_transition_start` (game-time), `_look_at`
  (world point, or `None` = base-forward), `_shake` (magnitude, default 0).

Methods, faithful to the RE:

- `ToggleZoom(t)` — flip `_is_zoomed`; rewind `_transition_start` so a mid-transition
  reverse resumes from the current fraction (not a snap).
- `IsZoomed()` — return `_is_zoomed`.
- `Update(t)` — return the eased scale: `frac = clamp((t − _transition_start) /
  effective_zoom_time)`; `lerp(_max_zoom, _min_zoom, frac)` when zooming in, reverse
  when out. **`effective_zoom_time = _zoom_time if _zoom_time > 0 else
  _BRIDGE_ZOOM_TIME`** — the fallback is load-bearing: the bridge config does not
  reliably `SetZoomTime`, and a 0 would snap the *officer* zoom to instant and break
  the regression bar. The current officer easing duration (`_BRIDGE_ZOOM_TIME`) is
  therefore preserved by construction.
- `UpdateViewFrustum()` — SDK-surface method (called by the RE flow / any SDK caller);
  in Dauntless the frustum is realized by `_BridgeCamera.compute()` reading `Update(t)`
  each frame, so this method only marks the camera dirty. It exists so SDK calls stop
  being silent no-ops, not because it owns the projection.
- `LookForward()` — becomes real: sets `_look_at = None` and toggles zoom. (The one
  SDK entry `MissionLib.ViewscreenOn` / `MissionLib.LookForward` already call — it
  stops being silent.)

`SetMinZoom` / `SetMaxZoom` / `SetZoomTime` already store; keep. `_zoom_time` is left
at its SDK-set value (often 0); the `Update` fallback above supplies the real duration.

**B. `CharacterClass.MenuEventHandler(engaged, look_at, zoom_factor, now)` —
dispatcher** (`engine/appc/characters.py`). Fetches the `"bridge"` set's
`"maincamera"` `ZoomCameraObjectClass` and drives it:

- Engage: substitute the hardcoded fallback when `zoom_factor` is
  `POSITION_ZOOM_SENTINEL`, else use it → write to camera `MinZoom`; set `_look_at`;
  `ToggleZoom(now)` in (only if not already zoomed for this engagement).
- Disengage: `ToggleZoom(now)` out + `BridgeHandlers.DropOutOfManualFireMode()`.

Single zoom slot on the camera ⇒ last-engaged wins naturally (a hail replacing an
open menu, or vice-versa, just rewrites `MinZoom`/`_look_at` and re-toggles).

**C. Two producers feed the dispatcher** (unchanged engagement signals):

- **Menu path** — the existing `MenuUp()`/`MenuDown()` → `dispatch_character_menu`
  seam (`characters.py`) also calls `MenuEventHandler` with the officer's head-centre
  world point + `GetPositionZoom(GetLocation())`.
- **Viewscreen-hail path** — a new host-loop watcher on `_active_comm_feed(controller)`
  edges (`host_loop.py`): `None`→set ⇒ `MenuEventHandler(engaged=True, look_at=None,
  zoom_factor=<hailed char GetPositionZoom>)`; set→`None` ⇒ disengage.

**D. `_BridgeCamera.compute()` reads the camera object** (`host_loop.py`). Instead of
resolving crew-menu state itself, it reads the `ZoomCameraObjectClass`:
`_is_zoomed` + `Update(now)` → the eased fraction (was `_zoom_t`); `MinZoom` → the
FOV factor (was `_zoom_factor`); `_look_at` → the target world point, or base-forward
when `None`. The eased-forward + FOV-narrow + roll-free-up math (currently
~2692-2727) is unchanged.

### 3.2 Engagement lifecycle & resolution

| | Officer (menu path) | Viewscreen hail (comm path) |
|---|---|---|
| Engage signal | `MenuUp()` → `dispatch_character_menu(is_open=True)` | `_active_comm_feed` `None`→set |
| Engaged character | officer whose menu raised | hailed char (`ViewscreenOn`'s `pcName`) |
| look_at | officer **head-centre** world point (`r.get_instance_head_center`) | `None` = **base-forward** (BC `LookForward` semantics) + tunable pitch `_VIEWSCREEN_LOOK_PITCH` |
| zoom_factor | `GetPositionZoom(GetLocation())` — authored (0.45–0.8) | `GetPositionZoom(GetLocation())` — misses (remote loc) → sentinel → **fallback** |
| Disengage | `MenuDown()` → `dispatch_character_menu(is_open=False)` | `_active_comm_feed` → `None` (ViewscreenOff) |

**Hardcoded fallback zoom** — module constant `_VIEWSCREEN_ZOOM_FALLBACK` in
`character_position_zoom.py`, alongside `POSITION_ZOOM_SENTINEL`. Start **0.5**
(≈2× fill; within the authored-officer band), tuned live (calibrate-up-then-down).
Single knob for "how much the viewscreen fills the window."

**`_look_at = None` → base-forward.** For a hail, `_BridgeCamera` interprets a `None`
look-at as "ease toward the captain's *base* (un-yawed/un-pitched) forward" — i.e.
recentre on the viewscreen exactly like BC's `LookForward()`, rather than aiming at a
specific world point. **No native binding for v1**: the seated captain's forward
already points at the screen; a small tunable pitch handles vertical centring without
a rebuild. (Aiming at the real viewscreen node — a `get_viewscreen_world_center()`
binding using `viewscreen_model_handle_` — stays a later refinement if the forward
recentre reads off.)

**Precedence** (one line added to today's order): baked cutscene camera pose
(`set_anim_pose`) **>** MenuEventHandler zoom **>** free-look. E1M1's Liu briefing
has no baked path during the hail, so the zoom shows; a mission that bakes a camera
path wins over the zoom.

**Time source:** `Update(t)` / `ToggleZoom(t)` use the same `_player_dt`-consistent
clock the bridge camera already uses, so the zoom freezes under pause/DevTools (like
the letterbox), rather than sliding on wall-clock.

### 3.3 Deliberate divergences from BC (documented)

- **Turn-to-face:** officers already turn to the captain via `MenuUp` — kept. The
  **viewscreen** character is NOT turned (it is framed by the authored comm camera on
  its remote set); BC's "turn the speaker to face you" applies to bridge-space
  characters, not the RTT feed.
- **Camera shake:** `ZoomCameraObjectClass` carries `_shake` for surface-completeness
  but v1 leaves magnitude 0 (no visible shake); base-campaign missions don't set it on
  the maincamera.

### 3.4 Retirements

`set_zoom_target`, `_active_zoom_officer`, `_active_zoom_officer_world`,
`_officer_zoom_factor`, and the focus-resolver block (~7074-7084). Officer
head-centre + `GetPositionZoom` resolution moves into the menu producer feeding
`MenuEventHandler`. `watch_ctrl` (AT_WATCH_ME / AT_LOOK_AT_ME) stays as-is and keeps
outranking the zoom — it is a separate focus mechanism, not part of MenuEventHandler.

## 4. Testing

- **`ZoomCameraObjectClass` unit tests:** `ToggleZoom` flips + rewinds start;
  `Update(t)` eases Max→Min over the effective zoom time and clamps; mid-transition
  reverse resumes from the current fraction (not a snap); **`_zoom_time == 0` falls
  back to `_BRIDGE_ZOOM_TIME` (does NOT snap)** — the officer-feel regression guard;
  `MinZoom` fallback substitution when fed the sentinel.
- **`MenuEventHandler` unit tests:** engage writes MinZoom + toggles in; disengage
  toggles out; sentinel `zoom_factor` → `_VIEWSCREEN_ZOOM_FALLBACK`; authored factor
  passes through; last-engaged wins when a second engage arrives.
- **Producer wiring:** menu-up/down drives engage/disengage (extend existing
  crew-menu zoom tests); `_active_comm_feed` on/off edges drive engage/disengage (new).
- **Regression bar:** the existing live-verified officer crew-menu zoom tests stay
  green with identical framing (head-centre look-at, same easing constants). This is
  the guardrail that the refactor did not change officer feel.
- **Gate:** `scripts/check_tests.sh` (pytest + ctest) — `_BridgeCamera` reads a
  changed source.
- **Live-verify (Mark, main tree — green tests can't see on-screen framing):** E1M1
  Liu briefing zooms in ~2× to fill on the hail and returns on ViewscreenOff; a
  crew-menu open still frames its officer identically to before.

## 3.5 Planning refinements (concrete SDK values)

Discovered while mapping files; consistent with the approved architecture:

- **The zoom min/max/time are real, harvested at bridge load.** `GalaxyBridge.py`
  (and `SovereignBridge.py`) call `SetMinZoom(0.64)`, `SetMaxZoom(1.0)`,
  `SetZoomTime(0.375)` on the maincamera. `host_loop.py:5875-5877` harvests these into
  `_BRIDGE_ZOOM_MIN/_BRIDGE_ZOOM_MAX/_BRIDGE_ZOOM_TIME`. So **post-load the officer
  zoom already eases over 0.375 s** (not instant); the module defaults (1.0/1.0/0.0)
  are pre-load fallbacks only. `effective_zoom_time = _zoom_time if _zoom_time > 0 else
  _BRIDGE_ZOOM_TIME` (§3.1 A) is therefore pre-load safety; in practice the ease is
  0.375 s.
- **`ZoomCameraObjectClass` transient state does NOT clobber the harvested min.**
  `_min_zoom` keeps the `SetMinZoom(0.64)` default; the per-engagement target factor is
  a separate `_active_zoom_factor` (BC stores its per-engagement value into MinZoom, but
  we keep the 0.64 default distinct so the fallback survives). Transient state added:
  `_is_zoomed`, `_transition_start`, `_look_at`, `_active_zoom_factor`.
- **`_BridgeCamera` reads the maincamera via a new `_BRIDGE_ZOOM_CAM` module global**,
  harvested next to the others at `host_loop.py:5875` (the `_cam` handle is already in
  scope there). Established pattern; no per-frame set lookup.
- **Fallback split, regression-safe.** The **officer** sentinel fallback stays
  `_BRIDGE_ZOOM_MIN` (0.64) — byte-identical to today, and in practice never hit (all
  campaign stations author a zoom). The **viewscreen** sentinel fallback is a distinct
  `_VIEWSCREEN_ZOOM_FALLBACK` (default **0.5** ≈ 2×, the user-observed fill; stronger
  than a station's 0.64). BC uses one hardcoded fallback for both; we keep the officer
  default at its live-verified 0.64 and give the viewscreen the stronger value. Same
  sentinel-substitution shape; documented divergence.

## 5. Out of scope

- Exact viewscreen-node world-centre aiming (native binding) — forward-recentre for v1.
- Camera shake magnitude — field exists, stays 0.
- Turning the viewscreen character to face the captain.
- Any change to `watch_ctrl` (AT_WATCH_ME / AT_LOOK_AT_ME).
