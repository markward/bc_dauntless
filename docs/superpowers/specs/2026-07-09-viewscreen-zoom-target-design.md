# ViewscreenZoomTarget camera mode — design

**Status:** REVISED after live-verification (2026-07-10). See "Revision 2" below —
the activation model and the FOV law in the original design were **wrong**, and
the sections below them describe the superseded v1. Revision 2 governs.
**Date:** 2026-07-09
**Follow-up to:** `docs/superpowers/specs/2026-07-07-cutscene-camera-direction-design.md`
(the "Out of scope" item), plan `docs/superpowers/plans/2026-07-08-cutscene-camera-direction.md`.

---

## Revision 2 — faithful auto-focus (supersedes Decision 3 + the FOV law)

Live-verification (VZT rendered correctly, but the viewscreen showed blurry white
blobs) surfaced two design errors.

### Error 1 — activation was modelled as a flag; BC uses a first-valid-wins chain

The v1 design claimed BC engages the viewscreen zoom via a deliberate trigger
(mission call or a toggle key), and modelled it with a sticky `_vs_active` flag
set through an `AddModeHierarchy` seam. **That is wrong.** `Camera.py`
`MakePlayerCamera` installs the chain *at camera creation*:

```
pCamera.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")
pCamera.AddModeHierarchy("ViewscreenZoomTarget", "ViewscreenForward")
```

and deliberately makes `InvalidViewscreen` an always-invalid mode ("It needs some
special named modes which are always invalid"). The hierarchy is a
**first-valid-wins fallback chain**; `Camera.PlayerTargetChanged` (registered on
`ET_TARGET_WAS_CHANGED`) keeps `ViewscreenZoomTarget`'s `Target` synced to the
player's current target; and `ViewscreenZoomTarget` is *valid* exactly when it
holds a live `Target`.

Therefore, in BC: **a target is selected → the viewscreen focuses it. No target →
the chain falls through to `ViewscreenForward`.** Automatic. There is no flag and
nothing to disengage — which also dissolves the v1 "sticky VZT can never return
to forward" gap.

`MissionLib.ViewscreenWatchObject(obj)` simply writes a *different* object into
that same `Target` field; a subsequent player target change overwrites it
(last-writer-wins), exactly as `PlayerTargetChanged` does in BC.

**Our engine never dispatches `ET_TARGET_WAS_CHANGED`** (it appears only in a
docstring). So we reproduce the sync in the pull-model resolver by remembering
the player's target frame-to-frame on the camera:

```
cur  = player.GetTarget()
if cur is not cam._vs_last_player_target:      # stands in for PlayerTargetChanged
    mode.SetAttrIDObject("Target", cur)         # player target overwrites any watch
    cam._vs_last_player_target = cur
tgt = mode.GetAttrIDObject("Target")            # mission watch persists until next change
if not _target_alive(tgt):
    return None                                  # -> ViewscreenForward (forward feed)
mode.SetAttrIDObject("Source", player)
```

Consequences: `_vs_active` is deleted; `AddModeHierarchy` reverts to a pure
no-op; the hold-`Z` trigger is deleted. `_vs_last_player_target` **must** be
initialized to `None` in `CameraObjectClass.__init__` (the `_LoudStub.__getattr__`
truthy-lambda trap).

### Error 2 — the adaptive-fill FOV law was invented, and caused a visual bug

`ZoomTargetMode` produces only `(eye, forward, up)` — **it carries no FOV.** The
v1 adaptive-fill law (`fov = 2·atan(VS_FILL_K·r/dist)`, clamped 6°–40°) was not
BC behaviour; it was invented in the v1 design.

It also caused a real artifact: the backdrop starfield is a **baked 1024²/face
cubemap** (`backdrop_pass.h:kSkyFaceSize`) drawn unconditionally in
`render_space`. A 90° cube face across 1024 texels, sampled at a ~10° FOV into
the 640×360 RTT, magnifies the sky ~5.6× — baked star dots become blurry white
blobs. (Space dust is *not* the cause: the single dust draw call is guarded by
`!for_viewscreen || warp_streaking`, and `g_streak` defaults to 0.)

A per-frame varying FOV is also wrong now that the viewscreen is *always*
target-focused: it would zoom in and out continuously as range changes while
manoeuvring.

**Replacement:** the viewscreen scene uses the **forward feed's FOV times one
constant zoom factor**:

```
VS_ZOOM_FACTOR: float = 0.7      # 1.0 = identical framing to the forward view
fov_y_rad = forward_fov * VS_ZOOM_FACTOR
```

`_adaptive_vs_fov` and `VS_FILL_K` / `VS_FOV_MIN` / `VS_FOV_MAX` are deleted.
`VS_NEAR` / `VS_FAR` remain. The resolver signature becomes
`_viewscreen_scene_feed(player, dt, forward_fov)` — `zoom_held` is gone. The call
site passes `director.fov_y_rad`.

### What Revision 2 does NOT change

Decision 1 (the native `SceneSource` RTT capability), Decision 2 (real
`Game.GetPlayerCamera` + the `"ViewscreenZoomTarget"` mode-factory entry), the
comm > scene > forward precedence, the byte-identical-when-inactive guarantee,
and the player-hull visibility analysis all stand as built.

---

## What it is (v1 — superseded by Revision 2 for activation + FOV)

`ViewscreenZoomTarget` (VZT) is BC's "zoom the bridge main viewer onto the
player's current target." Unlike the modes shipped by the cutscene-camera work
(Placement / ZoomTarget / the full-screen cutscene override), it does **not**
take over the whole screen. The bridge stays visible; only the **viewscreen**
(the bridge main viewer surface) shows a zoomed **exterior** view of a target
ship.

It is a named camera mode on the **player** camera. Two triggers engage it, both
landing on the same mode:

1. **Missions** — `MissionLib.ViewscreenWatchObject(pObject)` (E3M2/E3M4/E3M5,
   E4M4, E6M1/E6M2/E6M4, E7M2/E7M6, E8M2, …) sets the mode's `Target` and forces
   the viewscreen mode hierarchy to `ViewscreenZoomTarget`.
2. **Player** — **hold `Z`** (the existing `camera_zoom_target` action) while in
   bridge view: the viewscreen zooms onto the player's current combat target
   while held, and returns to forward on release. This reuses the same key and
   the same hold feel as the exterior-view zoom-on-target
   (`host_loop.py:5901`, gated on `is_exterior`); the bridge path adds a parallel
   read gated on bridge view. (BC's own trigger is a toggle key,
   `ET_INPUT_VIEWSCREEN_TARGET` → `BridgeHandlers.ViewscreenTarget`; we
   deliberately diverge to hold-to-zoom for consistency with the exterior `Z` —
   see Decision 3.)

## Why it was deferred

VZT needs the bridge viewscreen RTT to render the **live exterior space scene**
(ships + backdrop) from an **arbitrary** camera. The cutscene-camera work never
needed this: the viewscreen RTT renders either a tagged comm set
(`set_viewscreen_comm_source(set_id, …)`), a static image, or a model.

The key discovery that shapes this design: the plain **forward** viewscreen feed
**already** renders the live exterior scene into the RTT —
`native/src/host/host_bindings.cc` `frame()` calls
`render_space(vcam, /*for_viewscreen=*/true)` in the non-comm branch, using
`g_camera` (which host_loop drives to the forward-from-ship pose in bridge view).
So VZT does **not** need a new render path. It needs that same branch to accept
an **arbitrary** camera — exactly how `g_comm_source` already overrides the
branch for comm sets. This collapses the "new native renderer capability" into a
small, symmetric addition with **no shader change**.

## Decisions

### Decision 1 — new RTT source: `set_viewscreen_scene_source`

Add a `SceneSource` struct in `host_bindings.cc` mirroring `CommSource`:

```cpp
struct SceneSource { bool active = false; scenegraph::Camera cam; };
SceneSource g_scene_source;
```

Two pybind bindings (parallel to `set_viewscreen_comm_source` /
`clear_viewscreen_comm_source`):

- `set_viewscreen_scene_source(eye, target, up, fov_y_rad, near, far)` →
  `g_scene_source.active = true` and fill `g_scene_source.cam`.
- `clear_viewscreen_scene_source()` → `g_scene_source.active = false`.

In `frame()`, the viewscreen-RTT branch (currently comm-vs-forward) becomes a
three-way precedence — **comm wins, then scene, then forward**:

```cpp
if (g_comm_source.active && g_bridge_pass) {
    // …existing comm render…
} else if (g_scene_source.active) {
    scenegraph::Camera scam = g_scene_source.cam;
    scam.aspect = float(kViewscreenRttW) / float(kViewscreenRttH);
    render_space(scam, /*for_viewscreen=*/true);
} else {
    scenegraph::Camera vcam = g_camera;                 // unchanged forward feed
    vcam.aspect = float(kViewscreenRttW) / float(kViewscreenRttH);
    render_space(vcam, /*for_viewscreen=*/true);
}
```

- **No shader change** → `dauntless` rebuild only, **no cmake reconfigure**.
- `host_bindings.cc` edits need a `dauntless` rebuild (a module-only rebuild
  leaves `./build/dauntless` stale) — see memory `host_bindings_build_target`.
- Exposed through `engine/renderer.py`: two wrapper functions +
  `set_viewscreen_scene_source` / `clear_viewscreen_scene_source` added to
  `_HOST_SURFACE` (so `host_io` validates them at boot).
- **Byte-identical when inactive:** with `g_scene_source.active == false` the
  `else` branch is the exact current code path.

### Decision 2 — player camera: real `Game.GetPlayerCamera()`

`Game.GetPlayerCamera()` does **not** exist on main. Add it to
`engine/core/game.py` as a lazy, real `CameraObjectClass` named
`"MainPlayerCamera"` (BC's camera created by `Camera.MakePlayerCamera`, which our
shim never runs):

```python
def GetPlayerCamera(self):
    if self._player_camera is None:
        from engine.appc.bridge_set import CameraObjectClass_Create
        self._player_camera = CameraObjectClass_Create(
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")
    return self._player_camera
```

Register the named mode in `CameraObjectClass._MODE_FACTORY`
(`engine/appc/bridge_set.py`):

```python
"ViewscreenZoomTarget": ("ZoomTargetMode", {}),
```

`ZoomTargetMode` already exists in `engine/appc/camera_modes.py` and produces
VZT's pose exactly: eye at `Source` world location, look at `Target`, up from
`Source` col2 (column-vector right-handed; game units). The host pins
`Source = current player` each frame (pull-model — our shim never runs
`MakePlayerCamera_PlayerChanged`, which is where BC wires `Source=player`).

`ViewscreenWatchObject` (`sdk/.../MissionLib.py:1398`) already does
`pGame.GetPlayerCamera().GetNamedCameraMode("ViewscreenZoomTarget")
.SetAttrIDObject("Target", pObject)` — with a real camera + real mode this now
records the watch target instead of falling through `TGObject._Stub` and silently
"succeeding." It then calls `AddModeHierarchy("InvalidViewscreen",
"ViewscreenZoomTarget")` — our engagement seam (Decision 3).

### Decision 3 — activation state + triggers

Two independent engagement sources, unified in the per-frame resolver:

1. **Mission (sticky) — `_vs_active` flag on the player camera.** Set via the
   engagement seam below when `ViewscreenWatchObject` runs; the watched object is
   the `ViewscreenZoomTarget` mode's `Target` attribute (set by the SDK
   function). Sticky: stays engaged until the target dies (resolver falls back to
   forward) or a later `ViewscreenWatchObject` overwrites it.
2. **Player hold (momentary) — `Z` held in bridge view.** Read each frame in
   `host_loop`; the target is the player's live `GetTarget()`.

A separate activation flag is **required** for the mission path (not just "mode
has a valid Target"): in BC, `Camera.PlayerTargetChanged` re-points the mode's
`Target` on **every** target change, so keying activation on the presence of a
target would auto-zoom on every select — the behaviour the user rejected. We do
not model `PlayerTargetChanged` (see below); the mission `Target` is the explicit
object and the hold path reads `player.GetTarget()` directly, so no
target-change handler is needed at all.

**Engagement seam — `CameraObjectClass.AddModeHierarchy`** (currently a no-op
stub) gains one narrow behaviour: when called with the pair
`("InvalidViewscreen", "ViewscreenZoomTarget")` it sets `self._vs_active = True`.
This is the single SDK call `ViewscreenWatchObject` makes to engage VZT, so
missions stay fully SDK-driven with **no SDK edits**. All other `AddModeHierarchy`
argument pairs remain no-ops.

**Trigger wiring:**

- `MissionLib.ViewscreenWatchObject(obj)` — pure SDK: sets the mode `Target` and
  calls `AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")` → engages
  via the seam above. No SDK edit.
- **Player hold `Z`** — reuse the existing `camera_zoom_target` action. Mirror
  the exterior read at `host_loop.py:5901` with a bridge-gated parallel:
  `z_held_bridge = view_mode.is_bridge and host_io.key_state(input_map.code("camera_zoom_target"))`.
  The exterior read stays gated on `is_exterior` and is untouched, so a held `Z`
  drives exterior zoom in space and VZT in bridge view — no new action, no
  keyboard-constant plumbing, no conflict. `z_held_bridge` is passed to the
  resolver.

**Per-frame resolver — `_viewscreen_scene_feed(controller, player, dt, zoom_held)`**
in `engine/host_loop.py`, consulted at the existing feed-selection block
(host_loop ~6251, immediately after the comm-feed check):

```
cam  = game.GetPlayerCamera()
mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")

if cam._vs_active and _target_alive(mode.GetAttrIDObject("Target")):
    tgt = mode.GetAttrIDObject("Target")          # mission watch (sticky) wins
elif zoom_held:
    tgt = player.GetTarget()                       # Z held in bridge → live target
else:
    return None                                    # not engaged → forward feed
if not _target_alive(tgt):
    return None                                    # no live target → forward feed

mode.SetAttrIDObject("Source", player)             # pin Source live (pull-model)
mode.SetAttrIDObject("Target", tgt)
pose = mode.Update(dt)                              # (eye, fwd, up), or invalid → None
if pose is None:
    return None
eye, fwd, up = pose
target = eye + fwd
fov = _adaptive_vs_fov(tgt, eye)                   # adaptive-fill FOV law (below)
return (eye, target, up, fov, VS_NEAR, VS_FAR)
```

Note the pull-model discipline: `_vs_active`, `Target`, and the held-key state
are SDK/input state; the resolver only *reads* them each frame and never writes
`bridge_flag()` / `GetRenderedSet()`.

**Feed precedence at the call site** — comm hail → VZT scene → forward:

```python
_feed = _active_comm_feed(controller)
if _feed is not None:
    ... set_viewscreen_comm_source(...) ...      # unchanged
    r.clear_viewscreen_scene_source()
else:
    r.clear_viewscreen_comm_source()
    _scene = _viewscreen_scene_feed(controller, player, _player_dt, _z_held_bridge)
    if _scene is not None:
        r.set_viewscreen_scene_source(*_scene)
    else:
        r.clear_viewscreen_scene_source()
```

**Adaptive-fill FOV law** (`_adaptive_vs_fov`), so the target subtends a fixed
fraction of the viewscreen at any range ("zoom onto that ship"):

```
dist = |target_world_loc - eye|
r    = target.GetRadius()                        # game units
half = clamp(VS_FILL_K * r / dist, tan(VS_FOV_MIN/2), tan(VS_FOV_MAX/2))
fov_y = 2 * atan(half)
```

Constants (`VS_FILL_K`, `VS_FOV_MIN`, `VS_FOV_MAX`, `VS_NEAR`, `VS_FAR`) live in
Python — tunable with no rebuild. Degenerate cases (`dist == 0`, missing radius)
clamp to `VS_FOV_MAX`. All lengths in game units.

## Visibility + production guarantee

VZT is a bridge frame: the bridge stays visible and no in-space cutscene owns the
frame (`_cc is None`). `host_loop._apply_bridge_player_visibility` already hides
the player hull in bridge frames (so the ship doesn't show on its own screen), so
the eye-at-player VZT RTT camera does **not** clip the player hull — nothing to
change. The watched target is an ordinary world ship (not hidden) and renders in
the RTT.

When neither comm nor VZT is active:

- Native: `g_scene_source.active == false` → the forward `else` branch is the
  exact current code.
- Python: the resolver returns `None` → `clear_viewscreen_scene_source()`; the
  feed-selection block is otherwise unchanged.

Production render path is byte-identical with no VZT active.

## Non-goals (v1)

- Modelling BC's full viewscreen mode hierarchy / `AddModeHierarchy` fallback
  tree (`ViewscreenForward`/`Left`/`Right`/`Back`/`Up`/`Down` directional modes).
  We model only `ViewscreenZoomTarget` + the forward fallback (scene-source
  inactive). The directional viewscreen modes are a separate follow-up.
- BC's `ET_INPUT_VIEWSCREEN_TARGET` toggle + its remote-cam model
  (`GetViewScreenCamera`/`ToggleRemoteCam`/`RenderingRemoteCam` +
  `BridgeHandlers.ViewscreenTarget`). We deliberately diverge: the player trigger
  is **hold `Z`** (the existing `camera_zoom_target` action) in bridge view, for
  consistency with the exterior zoom-on-target. No new input action, no
  keyboard-constant plumbing.
- Modelling `Camera.PlayerTargetChanged` / an `ET_TARGET_WAS_CHANGED` sync
  handler. The mission `Target` is the explicit object; the hold path reads
  `player.GetTarget()` live. (Consequence: after `ViewscreenWatchObject(X)`, if
  the player cycles combat targets, we keep showing `X` where BC would flip to
  the new target — an acceptable, arguably-preferable v1 divergence.)
- Zoom sweep/ease-in animation. `ZoomTargetMode.Update` already sweeps its pose;
  no extra easing on the FOV in v1.

## Testing

- **Unit** (`tests/unit/`): `ViewscreenZoomTarget` registered in
  `_MODE_FACTORY` and returns a live `ZoomTargetMode`; `GetPlayerCamera` is lazy
  + identity-stable; `_adaptive_vs_fov` math (near/far/degenerate clamps);
  `ZoomTargetMode` pose with `Source=player`, `Target=object`.
- **Host** (`tests/host/`): `_viewscreen_scene_feed` returns `None` when neither
  `_vs_active` nor `zoom_held` (even with a live target); returns a pose tuple
  when mission-engaged with a live `Target`; returns a pose framed on
  `player.GetTarget()` when `zoom_held` and not mission-engaged; `None` on a
  dead/absent target either way; mission-sticky wins over the hold target;
  `Source` pinned to live player; `AddModeHierarchy("InvalidViewscreen",
  "ViewscreenZoomTarget")` sets `_vs_active` while other pairs stay no-ops;
  feed-selection precedence comm > scene > forward; renderer surface passthrough
  (`set_viewscreen_scene_source` / `clear_viewscreen_scene_source` reach `_h`);
  byte-identical-when-inactive (scene source cleared, no source set).
- **Gate:** `scripts/check_tests.sh` (builds C++ + runs pytest + ctest, diffs
  against `tests/known_failures.txt`). Must be green before merge.

## Dev harness + live-verify

A Developer-only pause-menu toggle (gated by `--developer`, `dev_mode`) that
fires `MissionLib.ViewscreenWatchObject(player.GetTarget())` on the player's
current target in QuickBattle, with a `print()` diagnostic (the host has no
`logging` handler — dev diagnostics must `print()`, per memory
`npc_subsystem_aim_gap`). Reaching an E-series `ViewscreenWatch` beat live is
impractical, so this is the live-verification path. Also live-verify **hold `Z`**
in bridge view (zoom on release returns to forward) and that the exterior `Z`
zoom still works unchanged. Remove the probe once verified.

## Constraints

- Game units throughout; column-vector right-handed rotations (CLAUDE.md).
- Never write `bridge_flag()` / `GetRenderedSet()`; the viewscreen source is
  derived from SDK state each frame (pull-model discipline from the merged
  cutscene work).
- Production render path byte-identical when no VZT is active.
- Shared git checkout: feature branch, commit with explicit pathspec (never
  `git add -A`), verify committed files survive later merges (memory
  `shared_checkout_hazards`).
- Gate is `scripts/check_tests.sh`; green before merge.

## Reference-only

Commit `622be12f` has a `ViewscreenZoomTargetMode` + `Game.GetPlayerCamera`
reference implementation. It live-regressed and must **not** be merged; use it
only as a reference (`git show 622be12f`). This design differs: it reuses the
already-merged `ZoomTargetMode` (no new mode class), adds the scene-source RTT
capability the reference lacked, and models activation with explicit flags rather
than the hierarchy tree.
