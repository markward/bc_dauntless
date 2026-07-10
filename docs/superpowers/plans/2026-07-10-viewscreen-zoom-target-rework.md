# ViewscreenZoomTarget — Revision 2 rework plan

> **For agentic workers:** execute task-by-task, test-first, gate + commit between tasks.

**Goal:** Make the bridge viewscreen **auto-focus the player's current target** (BC's real behaviour), and replace the invented adaptive-fill FOV with the forward feed's FOV × one constant zoom factor — which also removes the magnified-starfield blobs seen in live-verify.

**Context:** Branch `feat/viewscreen-zoom-target` already ships the native `SceneSource` RTT capability, `Game.GetPlayerCamera()`, the `"ViewscreenZoomTarget"` mode-factory entry, the `_viewscreen_scene_feed` resolver, comm>scene>forward precedence, and a dev probe. Gate is green. Live-verify passed *functionally* but exposed two design errors (see spec "Revision 2").

**Spec (authoritative):** `docs/superpowers/specs/2026-07-09-viewscreen-zoom-target-design.md` → section **"Revision 2"**.

## Global Constraints

- Game units (GU) throughout; column-vector right-handed rotations. Never name a spatial var `*_m`/`*_mps`.
- **Pull-model:** never write `bridge_flag()` / `GetRenderedSet()`. Derive viewscreen state from SDK/input state each frame.
- **Production render path byte-identical when no target is selected** (resolver returns `None` → `clear_viewscreen_scene_source()`).
- The SDK tree (`sdk/Build/scripts/`) must **NOT** be modified.
- `_LoudStub.__getattr__` / `TGObject._Stub.__getattr__` return a **truthy** `lambda *a, **k: None` for any missing attribute. Any new flag/field MUST be initialized in `__init__`; never rely on `getattr(obj, "x", default)`.
- `CameraMode.Update(dt)` does **not** return `None` for an invalid mode — it returns a bogus fallback pose. Guard with `IsValid()` before calling `Update`.
- `mode.Update()` returns `(eye, fwd, up)` where `fwd` is a **direction**; the renderer needs a look-at **point** = `eye + fwd`.
- Shared git checkout: explicit pathspec on every commit (never `git add -A`).
- Gate: `scripts/check_tests.sh` must be green (exit 0) before merge.
- Stay on branch `feat/viewscreen-zoom-target`.

---

### Task R1: Faithful activation — delete `_vs_active`, add target-change memory

**Files:**
- Modify: `engine/appc/bridge_set.py` (`CameraObjectClass.__init__`, `AddModeHierarchy`)
- Modify: `tests/unit/test_viewscreen_zoom_target_mode.py`

**Interfaces produced:**
- `cam._vs_last_player_target` — real attribute, initialized `None`. Stands in for BC's `Camera.PlayerTargetChanged` (our engine never dispatches `ET_TARGET_WAS_CHANGED`).
- `cam.AddModeHierarchy(*args)` — pure no-op returning `None` (as it was before this branch).
- `cam._vs_active` — **removed entirely.**

- [ ] **Step 1: Update the tests first.** In `tests/unit/test_viewscreen_zoom_target_mode.py`:
  - DELETE `test_vs_active_defaults_false_not_stub`, `test_addmodehierarchy_engagement_seam`, `test_addmodehierarchy_other_pairs_are_noops`.
  - KEEP `test_viewscreen_zoom_target_is_zoomtarget_mode` unchanged.
  - ADD:

```python
def test_vs_last_player_target_defaults_none_not_stub():
    cam = _cam()
    # Real attribute — must be exactly None, NOT a truthy _LoudStub lambda.
    assert cam._vs_last_player_target is None


def test_addmodehierarchy_is_a_pure_noop():
    cam = _cam()
    # BC installs the InvalidViewscreen -> ViewscreenZoomTarget -> ViewscreenForward
    # chain at camera creation; we model first-valid-wins in the resolver instead,
    # so this stays a no-op and must not create hidden state.
    assert cam.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget") is None
    assert cam.AddModeHierarchy("InvalidSpace", "Target") is None
    assert not hasattr(cam, "_vs_active") or cam._vs_active is None
```

  Note the last assertion is deliberately lenient because `_LoudStub.__getattr__` makes `hasattr` always True; the real guarantee is that nothing reads `_vs_active` any more (Task R2 removes the only reader).

- [ ] **Step 2: Run the tests, confirm the new ones fail.**

Run: `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py -v`
Expected: `test_vs_last_player_target_defaults_none_not_stub` FAILS (attribute is a truthy lambda, not `None`); `test_addmodehierarchy_is_a_pure_noop` FAILS on the `_vs_active` engage seam still existing.

- [ ] **Step 3: Edit `engine/appc/bridge_set.py`.** In `CameraObjectClass.__init__`, REPLACE the `_vs_active` block with:

```python
        # Last player target this camera observed, used by
        # host_loop._viewscreen_scene_feed to stand in for BC's
        # Camera.PlayerTargetChanged (our engine never dispatches
        # ET_TARGET_WAS_CHANGED). MUST be a real attribute: _LoudStub.__getattr__
        # hands back a truthy lambda for any missing name.
        self._vs_last_player_target = None
```

  And revert `AddModeHierarchy` to the pure no-op it was:

```python
    def AddModeHierarchy(self, *args):
        # BC's viewscreen mode chain (InvalidViewscreen -> ViewscreenZoomTarget
        # -> ViewscreenForward) is first-valid-wins and is installed at camera
        # creation. We resolve that chain in host_loop._viewscreen_scene_feed by
        # asking whether ViewscreenZoomTarget has a live Target, so nothing needs
        # to be recorded here.
        return None
```

- [ ] **Step 4: Run the tests, confirm they pass.**

Run: `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py -v`
Expected: 3 passed. Then `uv run pytest tests/unit/ tests/host/ -q` — note `tests/host/test_viewscreen_scene_feed.py` WILL fail here because it still uses `_vs_active`; that is expected and Task R2 fixes it. Record the failures; do not "fix" them by weakening tests.

- [ ] **Step 5: Commit.**

```bash
git add engine/appc/bridge_set.py tests/unit/test_viewscreen_zoom_target_mode.py
git commit -m "refactor(camera): drop _vs_active flag; VZT chain is first-valid-wins

BC's MakePlayerCamera installs InvalidViewscreen -> ViewscreenZoomTarget ->
ViewscreenForward at camera creation and the chain resolves first-valid-wins,
so a live Target IS the engagement. Replaces the invented sticky flag with a
_vs_last_player_target memory used to stand in for PlayerTargetChanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(The tree is briefly red between R1 and R2 — that's why they are adjacent. Do not run the full gate until R2 lands.)

---

### Task R2: Auto-focus resolver + constant-zoom FOV + drop hold-`Z`

**Files:**
- Modify: `engine/host_loop.py` (constants + `_adaptive_vs_fov` removal + `_viewscreen_scene_feed` + the `run()` call site)
- Delete: `tests/unit/test_adaptive_vs_fov.py`
- Modify: `tests/host/test_viewscreen_scene_feed.py`

**Interfaces produced:**
- `VS_ZOOM_FACTOR: float = 0.7` (module constant; `1.0` = same framing as forward view).
- `VS_NEAR` / `VS_FAR` unchanged. `VS_FILL_K`, `VS_FOV_MIN`, `VS_FOV_MAX`, `_adaptive_vs_fov` **deleted**.
- `_viewscreen_scene_feed(player, dt, forward_fov) -> tuple | None` returning `(eye, target, up, fov_y_rad, near, far)`.

- [ ] **Step 1: Rewrite the resolver tests first.** In `tests/host/test_viewscreen_scene_feed.py`, keep the `_Pt` / `_Rot` / `_Ship` / `_Game` helpers and the `wired` fixture. Replace the 8 tests with:

```python
FWD_FOV = 1.0   # radians; the forward feed's FOV handed to the resolver


def test_none_when_no_target(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None


def test_auto_focus_on_player_target(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    assert out is not None
    eye, target, up, fov, near, far = out
    assert eye == (0.0, 0.0, 0.0)            # eye at player (Source)
    assert target[0] > 0.0 and abs(target[1]) < 1e-6   # looks at the target (+X)
    assert near == host_loop.VS_NEAR and far == host_loop.VS_FAR


def test_fov_is_forward_fov_times_zoom_factor(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    fov = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)[3]
    assert abs(fov - FWD_FOV * host_loop.VS_ZOOM_FACTOR) < 1e-9
    # ...and it must TRACK the forward fov, not be a constant
    fov2 = host_loop._viewscreen_scene_feed(player, 0.016, 2.0 * FWD_FOV)[3]
    assert abs(fov2 - 2.0 * FWD_FOV * host_loop.VS_ZOOM_FACTOR) < 1e-9


def test_dead_target_falls_back_to_forward(wired):
    dead = _Ship(_Pt(500.0, 0.0, 0.0), dying=True)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=dead)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None


def test_mission_watch_object_overrides_player_target(wired):
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    # settle the "last seen player target" memory
    host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    # MissionLib.ViewscreenWatchObject writes a different object into the mode
    wired.GetNamedCameraMode("ViewscreenZoomTarget").SetAttrIDObject("Target", watched)
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    target = out[1]
    assert target[1] > 0.0 and abs(target[0]) < 1e-6   # watched (+Y), not combat (+X)


def test_changing_player_target_overwrites_mission_watch(wired):
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    wired.GetNamedCameraMode("ViewscreenZoomTarget").SetAttrIDObject("Target", watched)
    # BC: PlayerTargetChanged re-points the mode on the next target change.
    newtgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player._target = newtgt
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    target = out[1]
    assert target[2] > 0.0 and abs(target[1]) < 1e-6   # new target (+Z), not watched (+Y)


def test_source_pinned_to_live_player(wired):
    tgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)[0] == (10.0, 20.0, 30.0)


def test_target_point_is_eye_plus_forward_not_bare_forward(wired):
    # player off-origin so eye+fwd != fwd; a bare `target = fwd` returns (0,0,1).
    tgt = _Ship(_Pt(10.0, 20.0, 130.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    target = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)[1]
    for got, want in zip(target, (10.0, 20.0, 31.0)):
        assert abs(got - want) < 1e-6


def test_invalid_mode_returns_none_not_fallback_pose(wired):
    # Dying player => ZoomTargetMode._ideal() -> None => IsValid() false.
    # Without the IsValid() guard, Update() would return a bogus fallback pose.
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt, dying=True)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None
```

  You must extend the `_Ship` helper to accept `dying=False` and have `IsDying()` return `1` when set. Keep every other helper as-is.

- [ ] **Step 2: Run, confirm failures.** `uv run pytest tests/host/test_viewscreen_scene_feed.py -v` — expect failures (old 4-arg signature / `_vs_active`).

- [ ] **Step 3: Replace the constants + delete the FOV law.** In `engine/host_loop.py`, replace the whole `VS_*` constants block and the entire `_adaptive_vs_fov` function with:

```python
# ── ViewscreenZoomTarget (VZT) framing ─────────────────────────────────────────
# The bridge viewscreen auto-focuses the player's current target (BC's
# first-valid-wins viewscreen mode chain). BC's ZoomTargetMode carries only
# eye+direction — no FOV — so the scene render reuses the forward feed's FOV,
# scaled by one constant. Tunable here (no rebuild). Lengths in game units.
VS_NEAR: float = 1.0
VS_FAR: float = 5000.0
VS_ZOOM_FACTOR: float = 0.7   # 1.0 == identical framing to the forward view
```

- [ ] **Step 4: Rewrite the resolver.** Replace `_viewscreen_scene_feed` entirely with:

```python
def _viewscreen_scene_feed(player, dt, forward_fov):
    """Resolve the ViewscreenZoomTarget scene feed. Returns
    (eye, target, up, fov_y_rad, near, far) to render the live exterior scene
    focused on the player's target into the bridge viewscreen RTT, or None to
    leave the plain forward feed.

    BC's viewscreen mode chain (InvalidViewscreen -> ViewscreenZoomTarget ->
    ViewscreenForward, installed by Camera.MakePlayerCamera) is first-valid-wins,
    and ViewscreenZoomTarget is valid exactly when it holds a live Target. So a
    selected target IS the engagement; no target falls through to forward.

    Our engine never dispatches ET_TARGET_WAS_CHANGED, so the frame-to-frame
    `_vs_last_player_target` comparison stands in for Camera.PlayerTargetChanged:
    on a target change we re-point the mode, which is what lets a later
    MissionLib.ViewscreenWatchObject(obj) override persist until the player
    picks a different target (BC's last-writer-wins).

    Pull-model: reads SDK state, never writes bridge_flag()/GetRenderedSet()."""
    if player is None:
        return None
    from engine.appc.camera_modes import _target_alive
    game = Game_GetCurrentGame()
    if game is None:
        return None
    cam = game.GetPlayerCamera()
    if cam is None:
        return None
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")
    if mode is None:
        return None

    cur = player.GetTarget()
    if cur is not cam._vs_last_player_target:      # stands in for PlayerTargetChanged
        mode.SetAttrIDObject("Target", cur)
        cam._vs_last_player_target = cur

    tgt = mode.GetAttrIDObject("Target")            # mission watch persists until then
    if not _target_alive(tgt):
        return None                                  # -> ViewscreenForward

    mode.SetAttrIDObject("Source", player)           # pin Source to the live player
    if not mode.IsValid():                           # _ideal() resolvable?
        return None
    eye, fwd, up = mode.Update(dt)
    target = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
    return (eye, target, up, forward_fov * VS_ZOOM_FACTOR, VS_NEAR, VS_FAR)
```

- [ ] **Step 5: Update the single call site in `run()`.** Remove the `_z_held_bridge` assignment and its comment entirely, and change the resolver call so the block reads:

```python
            _feed = _active_comm_feed(controller)
            _scene = None
            if _feed is None:
                _scene = _viewscreen_scene_feed(
                    player, _player_dt, director.fov_y_rad)
            _vs_src = _select_viewscreen_source(r, _feed, _scene)
```

  Leave the rest of the block (the `if _vs_src == "comm":` branch) untouched.
  **Do not touch** the exterior `z_held_now` read (gated on `is_exterior`).

- [ ] **Step 6: Delete the obsolete FOV test.**

```bash
git rm tests/unit/test_adaptive_vs_fov.py
```

- [ ] **Step 7: Run everything.**

```
uv run pytest tests/host/test_viewscreen_scene_feed.py -v        # 9 passed
uv run pytest tests/unit/ tests/host/ -q                          # no regressions
grep -rn "_adaptive_vs_fov\|VS_FILL_K\|VS_FOV_MIN\|VS_FOV_MAX\|_vs_active\|_z_held_bridge" engine/ tests/
```
The grep must return NOTHING. Report the real output of each.

- [ ] **Step 8: Commit.**

```bash
git add engine/host_loop.py tests/host/test_viewscreen_scene_feed.py
git rm --cached tests/unit/test_adaptive_vs_fov.py 2>/dev/null || true
git commit -m "feat(camera): viewscreen auto-focuses the player's target

BC's viewscreen mode chain is first-valid-wins, so a live target IS the
engagement. Drops the hold-Z trigger. Replaces the invented adaptive-fill FOV
(which magnified the baked 1024/face sky cubemap ~5.6x into blurry star blobs)
with the forward feed's FOV times a constant VS_ZOOM_FACTOR.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task R3: Repoint the dev probe at a NON-target object

**Files:**
- Modify: `engine/dev_viewscreen_probe.py`
- Modify: `tests/host/test_vzt_probe_registers.py`

**Why:** with auto-focus, `ViewscreenWatchObject(player.GetTarget())` is indistinguishable from doing nothing. To live-verify the mission override we must watch an object that is **not** the player's target.

- [ ] **Step 1: Rewrite the probe body.** Keep the module docstring, the dev-only registration, and `print()` diagnostics (the host has no `logging` handler). Replace `watch_current_target` with:

```python
def watch_non_target_ship(*_args):
    """Fire MissionLib.ViewscreenWatchObject on a ship that is NOT the player's
    current target, so the mission override is visibly distinct from the
    auto-focus behaviour. Throwaway; removed after live-verify."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player is None:
        print("[vzt-probe] no current player")
        return
    target = player.GetTarget()
    pick = None
    pSet = player.GetContainingSet()
    if pSet is not None:
        for obj in pSet.GetObjectList():
            if obj is player or obj is target:
                continue
            if hasattr(obj, "GetRadius"):
                pick = obj
                break
    if pick is None:
        print("[vzt-probe] no non-target object found in the player's set")
        return
    import MissionLib
    ok = MissionLib.ViewscreenWatchObject(pick)
    name = getattr(pick, "GetName", lambda: "?")()
    print("[vzt-probe] ViewscreenWatchObject(%s) -> %s "
          "(player target = %s)" % (name, ok,
                                    getattr(target, "GetName", lambda: None)()))
```

  **Verify `GetObjectList()` (or the correct enumerator) actually exists** on the set class in `engine/appc/sets.py` before using it; if the real method has a different name, use the real one and say so in your report. Do NOT invent an API.

- [ ] **Step 2: Update the registration label + import** in `engine/host_loop.py` (the dev-gated block) to `watch_non_target_ship` / label `"VZT: Watch Non-Target Ship"`.

- [ ] **Step 3: Update `tests/host/test_vzt_probe_registers.py`** to import `watch_non_target_ship` and keep the no-player safety test (monkeypatch `engine.core.game.Game_GetCurrentGame` → `None`, assert `"no current player"` on stdout). The late-binding import inside the function is load-bearing — keep it.

- [ ] **Step 4: Run.** `uv run pytest tests/host/test_vzt_probe_registers.py -v` (2 passed).

- [ ] **Step 5: Commit** (explicit pathspec).

```bash
git add engine/dev_viewscreen_probe.py engine/host_loop.py tests/host/test_vzt_probe_registers.py
git commit -m "chore(dev): probe watches a non-target ship to prove the mission override

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task R4: Gate + live-verify + remove probe

- [ ] **Step 1:** `scripts/check_tests.sh` → must exit 0. Any failure not in `tests/known_failures.txt` is a regression introduced here.
- [ ] **Step 2 (human):** `./build/dauntless --developer`, QuickBattle.
  - Select a target → viewscreen focuses it automatically. Deselect → returns to forward.
  - Cycle targets → viewscreen follows.
  - Starfield is crisp (no blurry blobs).
  - Pause menu → **VZT: Watch Non-Target Ship** → viewscreen swings to a *different* ship than your target. Then cycle your target → viewscreen returns to following your target.
  - Exterior view: hold `Z` → exterior zoom still works (unchanged).
- [ ] **Step 3:** Tune `VS_ZOOM_FACTOR` if framing feels off (pure Python, no rebuild). `1.0` = same as forward.
- [ ] **Step 4:** Remove the probe: delete `engine/dev_viewscreen_probe.py` + `tests/host/test_vzt_probe_registers.py`, remove the registration block from `engine/host_loop.py`.
- [ ] **Step 5:** `scripts/check_tests.sh` → exit 0. Commit (explicit pathspec).

---

## Revision 3 — real fill framing + sharp sky under zoom

Live-verify #2: `VS_ZOOM_FACTOR = 0.7` is far too weak; the target must fill ~60%
of the viewscreen height. That demands large zoom, which exposes two *separate*
sky problems (measured, not guessed):

- **Texel blur (dominant).** The sky is a baked 1024²/face cubemap. One face =
  90°. At a 6° FOV only ~68 texels cover the 640px-wide RTT → ~9× texel
  magnification → smeared blobs.
- **Star growth.** `backdrop.frag:proc_stars` places stars as **fixed angular
  disks** (`g = dir*220.0`, radius `0.6` → angular radius ≈ 2.7 mrad). A star's
  pixel radius is `2.7mrad ÷ (fov ÷ height)`, so it grows as FOV shrinks:
  ~2.8 px at 20°/360px (identical to the main view at 60°/1080px — which is why
  the forward feed never blobbed), but ~9.3 px at 6°/360px.

Raising the RTT resolution does **not** help star growth (numerator and
denominator both scale). Both fixes below are required.

### Task R5 — native + shader: sharp sky for the zoomed viewscreen

**Files:** `native/src/renderer/shaders/backdrop.frag`, `native/src/renderer/backdrop_pass.{h,cc}`, `native/src/host/host_bindings.cc`

1. **Shader** (`backdrop.frag`): add `uniform float u_star_scale;` (semantic: 1.0 = current behaviour). In `proc_stars`, scale the disk radius:
   `float core = present * smoothstep(0.6 * u_star_scale, 0.0, d);`
   Keeping the star's angular radius proportional to the FOV holds its *pixel* size roughly constant. Apply to both `proc_stars` calls (the scale lives inside the function, so this is automatic).
2. **`BackdropPass::render`** gains a trailing `float star_scale = 1.0f` parameter, forwarded through `draw_backdrops` to `shader.set_float("u_star_scale", star_scale)`. `render_cubemap` is untouched (the bake always uses 1.0).
3. **`host_bindings.cc`**: give the `render_space` lambda a third parameter `bool sharp_sky = false`. When `sharp_sky` is true, bypass the baked cubemap and call `g_backdrop_pass->render(g_backdrops, cam, *g_pipeline, sky_procedural, now, star_scale)` where
   `star_scale = clamp(cam.fov_y_rad / radians(60.0f), 0.15f, 1.0f)`.
   Pass `sharp_sky=true` **only** from the `g_scene_source.active` branch. The two existing call sites pass `false` and must be byte-identical.

**Shader files changed → `cmake -B build -S .` reconfigure BEFORE `cmake --build build -j`.**

Byte-identical guarantee: with `g_scene_source.active == false`, no call site passes `sharp_sky=true` and `u_star_scale` defaults to 1.0, so both the main view and the forward viewscreen feed render exactly as today.

### Task R6 — python: adaptive fill framing

**Files:** `engine/host_loop.py`, `tests/host/test_viewscreen_scene_feed.py`

Replace `VS_ZOOM_FACTOR` with:

```python
VS_TARGET_FILL: float = 0.60          # target diameter as a fraction of viewscreen height
VS_FOV_MIN: float = _math.radians(4.0)  # max-zoom clamp
```

Add, next to the resolver:

```python
def _viewscreen_fov(target, eye, forward_fov) -> float:
    """Vertical FOV (radians) that makes `target` span VS_TARGET_FILL of the
    viewscreen height. Never wider than the forward view (forward_fov is the
    upper clamp); never tighter than VS_FOV_MIN. Degenerate inputs -> forward_fov.

    Derivation: the target's diameter fraction of screen height is
    (r/dist) / tan(fov/2); setting that to VS_TARGET_FILL gives
    tan(fov/2) = (r/dist) / VS_TARGET_FILL."""
    try:
        loc = target.GetWorldLocation()
        r = float(target.GetRadius())
    except Exception:
        return forward_fov
    dx = loc.x - eye[0]; dy = loc.y - eye[1]; dz = loc.z - eye[2]
    dist = _math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist <= 0.0 or r <= 0.0:
        return forward_fov
    fov = 2.0 * _math.atan((r / dist) / VS_TARGET_FILL)
    return max(VS_FOV_MIN, min(forward_fov, fov))
```

The resolver's last line becomes:

```python
    return (eye, target, up, _viewscreen_fov(tgt, eye, forward_fov), VS_NEAR, VS_FAR)
```

Tests must cover: exact fill math in the unclamped band; clamp to `forward_fov` for a very close target; clamp to `VS_FOV_MIN` for a very distant one; degenerate (zero distance / zero radius) → `forward_fov`. Choose values that provably land in the unclamped band (verify the arithmetic; do not let a clamp silently satisfy a "matches formula" assertion).

---

## Revision 4 — reproduce the exterior Z view EXACTLY (supersedes R5 + R6)

Live-verify #3 (Mark): the viewscreen zoom must be "basically the same as what we
render in the exterior view when pressing Z." Reverse-engineering that path
(`director.start_zoom_target` -> `_TrackingCamera` with `zoom_target_active`)
shows why every prior attempt was wrong:

- The exterior Z zoom keeps **FOV constant at EXTERIOR_FOV_Y_RAD (35°)**
  (`tracking.py:v_fov_rad`, never narrowed; `zoom_in`/`zoom_out` change the
  *distance* `d_chase_zoom`, not the FOV).
- The "zoom" comes from **placing the eye close behind the target** on the
  ship->target axis (`_compute_zoom_target`: eye = T - d_chase_zoom·e1, look-at =
  T, up = body-up perpendicularised). `d_chase_zoom = ZOOM_DEFAULT_RADII · player
  radius`, clamped to 0.9·D when the target is closer than that.
- The framed point is `target_aim_point(player)` — the locked subsystem's world
  position, or the target hull centre.

Because the FOV stays 35°, the sky renders at 1:1 exactly as in the exterior
view — **no magnification, so the blobs never appear.** This makes R5 (sharp-sky
shader) and R6 (adaptive-fill FOV) unnecessary; both are reverted.

### Task RB — revert R5 (native sharp-sky)

`git revert --no-edit 41239dd9` (the "sharp procedural starfield" commit). It
reverts `backdrop.frag`, `backdrop_pass.{h,cc}`, and the `sharp_sky` param +
VZT call site in `host_bindings.cc`, restoring the sky to the normal
baked/procedural path everywhere. **Shader file reverts → `cmake -B build -S .`
reconfigure, then `cmake --build build -j`.** Verify the build + `ctest -R Frame`
(36/36). If the revert conflicts (it should not — R6 touched only host_loop.py),
resolve by hand to the pre-R5 state of those four files and note it.

### Task RA — resolver reuses the tracking-camera zoom-target geometry

**Files:** `engine/host_loop.py`, `engine/appc/bridge_set.py` (only if a helper field is needed — prefer stateless), `tests/host/test_viewscreen_scene_feed.py`

1. Delete R6's additions from `engine/host_loop.py`: `VS_TARGET_FILL`,
   `VS_FOV_MIN`, and the whole `_viewscreen_fov` function. Keep `VS_NEAR` /
   `VS_FAR`.
2. Rewrite `_viewscreen_scene_feed`. It no longer needs `dt` (the framing is
   stateless/rigid — see note) or `ZoomTargetMode.Update`. New signature
   `_viewscreen_scene_feed(player, forward_fov)`:

```python
def _viewscreen_scene_feed(player, forward_fov):
    """Resolve the ViewscreenZoomTarget scene feed: the SAME framing the
    exterior view shows when holding Z (camera_zoom_target), rendered into the
    bridge viewscreen RTT. Returns (eye, target, up, fov_y_rad, near, far) or
    None to leave the plain forward feed.

    BC's viewscreen mode chain is first-valid-wins, so a live Target IS the
    engagement. The frame-to-frame `_vs_last_player_target` compare stands in for
    Camera.PlayerTargetChanged (we never dispatch ET_TARGET_WAS_CHANGED), which
    lets MissionLib.ViewscreenWatchObject(obj) persist until the player retargets.

    Framing reuses engine.cameras.tracking._TrackingCamera in ZoomTarget mode —
    the identical solver the exterior Z zoom uses (eye close behind the target on
    the ship->target axis, look-at the subsystem aim point, FOV unchanged at the
    exterior value). Rigid (dt=None): no spring smoothing, which for an inset
    reads as a clean lock rather than a swoop."""
    if player is None:
        return None
    from engine.appc.camera_modes import _target_alive
    game = Game_GetCurrentGame()
    if game is None:
        return None
    cam = game.GetPlayerCamera()
    if cam is None:
        return None
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")   # Target holder only
    if mode is None:
        return None

    cur = player.GetTarget()
    if cur is not cam._vs_last_player_target:      # stands in for PlayerTargetChanged
        mode.SetAttrIDObject("Target", cur)
        cam._vs_last_player_target = cur

    tgt = mode.GetAttrIDObject("Target")
    if not _target_alive(tgt):
        return None                                 # -> ViewscreenForward

    from engine.cameras.tracking import _TrackingCamera
    from engine.ui.target_reticle import target_aim_point
    tc = _TrackingCamera()
    tc.set_ship_radius(max(player.GetRadius(), 1e-6))
    tc.enter_zoom_target()
    # Subsystem-aware aim only when watching the player's OWN target; a mission
    # ViewscreenWatchObject on a different object frames that object's centre.
    aim = target_aim_point(player) if tgt is player.GetTarget() else None
    eye, look_at, up = tc.compute(player=player, target=tgt, dt=None, aim_point=aim)
    return (eye, look_at, up, forward_fov, VS_NEAR, VS_FAR)
```

3. Update the call site in `run()`:
   `_scene = _viewscreen_scene_feed(player, director.fov_y_rad)` (drop `_player_dt`).

**Tests** (`tests/host/test_viewscreen_scene_feed.py`): the `_Ship` helper already
has GetWorldLocation/GetWorldRotation/GetRadius/GetTarget/IsDying. Rewrite the fov
+ framing tests:
- none-when-no-target; dead-target -> None (keep).
- `fov` returned == `forward_fov` exactly (proves NO custom FOV). Call with two
  different forward_fov values and assert it tracks.
- eye is near the TARGET, not at the player: player at origin, target at
  (500,0,0), small radius -> `eye[0]` well past the midpoint (e.g. `> 250`) and
  `abs(eye[1]) < 1e-6`; distinguishes new (eye behind target) from old (eye at
  player origin).
- mission override: set the mode Target to a different object than
  `player.GetTarget()` and assert the framing centres on it (eye near it).
- auto-focus follows player target; source/point sanity.
  Keep tests that still apply; delete assertions tied to the removed FOV law.
- Delete `tests/unit/test_adaptive_vs_fov.py` already gone; nothing else to remove.

**Note (rigid vs springs):** dt=None gives the exterior Z *framing* without the
spring sway. If Mark wants the exact spring dynamics, upgrade to a persistent
`_TrackingCamera` on the player camera advanced with real dt (needs
`_vs_tracking*` fields initialised in `CameraObjectClass.__init__` — the
`_LoudStub` trap). Deferred unless requested.

Gate: `scripts/check_tests.sh` green after RB + RA.

---

## Revision 5 — viewscreen renders the FULL space scene (match the exterior camera)

Live-verify #4 (Mark): "many visual effects including damage vfx and cloak vfx
don't apply in this view. we want it to match the exterior camera. can we not
just copy the space render pass and apply it on the viewscreen?"

Yes. The `render_space` lambda already contains every space pass; it just (a)
gates ~6 of them behind `!for_viewscreen`, and (b) hardcodes the MAIN HDR target
(`g_hdr_target`) / main framebuffer size (`fw`,`fh`) in the three
framebuffer-coupled passes, so they can't run against the viewscreen RTT.
Cloak refraction runs OUTSIDE `render_space`, main-view only.

KEY FINDING: the three coupled passes ALREADY take their target textures/dims as
parameters — `lens_flare(…, viewport_w, viewport_h, …)`,
`nebula_volumetric(…, hdr_color_tex, hdr_depth_tex, …)`,
`nebula_godray(…, hdr_color_tex)` — and `g_viewscreen_hdr` is the same
`renderer::HdrTarget` class as `g_hdr_target`, with `color_texture()` and
`depth_texture()`. So NO pass-level API changes are needed; we only thread the
BOUND target's handles into `render_space`. Cloak already reads the live viewport
and copies the bound FBO (`cloak_pass.cc:70-76`), so it works in the RTT unchanged.

**Rule after this change: the viewscreen renders identically to the exterior
view, EXCEPT camera dust stays cockpit-only (Mark).** No shader change →
`dauntless` rebuild only, no cmake reconfigure.

### Task R7 — parameterize `render_space` on its render target; run all passes + cloak on the viewscreen

**File:** `native/src/host/host_bindings.cc`

1. Change the lambda signature (line ~645) to:
   `auto render_space = [&](const scenegraph::Camera& cam, bool for_viewscreen, renderer::HdrTarget& target, int vw, int vh) {`
2. Inside, replace the four hardcodes:
   - volumetric nebula guard `&& g_hdr_target` → drop it (target is always valid; keep the `dauntless_volumetric_nebulae::enabled() && g_nebula_volumetric_pass` conditions).
   - `g_hdr_target->color_texture(), g_hdr_target->depth_texture()` (volumetric) → `target.color_texture(), target.depth_texture()`.
   - `g_hdr_target->color_texture()` (godray) → `target.color_texture()`.
   - `g_lens_flare_pass->render(g_lens_flares, cam, *g_pipeline, fw, fh, now)` → `…, vw, vh, now`.
3. Remove the `!for_viewscreen &&` prefix from these passes so they run on the viewscreen too: nebulae block (line ~685), nebula godrays (~706), lens flares (~710), hull discharges (~716), shockwave (~719), particles (~724). Do NOT remove it from DUST (~681) — dust stays `(!for_viewscreen || warp_streaking)`.
4. Ambient dim: to match the exterior, make the viewscreen use the same filmic ambient. Change line ~656 from `(!for_viewscreen) ? dauntless_filmic::ambient_scale() : 1.0f` to just `dauntless_filmic::ambient_scale()`. (Behaviour change on the viewscreen tone — flagged for live-verify.)
5. Move the CLOAK pass into `render_space`, at the very end of the lambda body (after the particle block), using `cam` and the local `ambient_scale`:
   ```cpp
   if (g_cloak_pass && !g_cloak_ships.empty())
       g_cloak_pass->render(g_cloak_ships, g_world, cam, *g_pipeline, lookup,
                            static_cast<float>(now), g_lighting, ambient_scale);
   ```
   Then DELETE the old standalone cloak call (the `if (!viewer_mode && !bridge_active && g_cloak_pass …)` block, ~line 863-866).
6. Update the three call sites:
   - viewscreen scene source (~822): `render_space(scam, /*for_viewscreen=*/true, *g_viewscreen_hdr, kViewscreenRttW, kViewscreenRttH);`
   - viewscreen forward (~827): `render_space(vcam, /*for_viewscreen=*/true, *g_viewscreen_hdr, kViewscreenRttW, kViewscreenRttH);`
   - main (~857): `render_space(g_camera, /*for_viewscreen=*/false, *g_hdr_target, fw, fh);`

**Byte-identical for the MAIN view:** the main call passes `*g_hdr_target, fw, fh` (== the old hardcodes) and `for_viewscreen=false` (all gates already open for it). Cloak moves from just-after-`render_space` to the end of the lambda body — the same sequence point for the main view (nothing ran between). So the main exterior view is unchanged. The viewscreen forward feed (no target) gains the extra passes too — that's the intended "match".

**Verify:** `cmake --build build -j` (NO reconfigure — no shader change); `PYTHONPATH=build/python python -c "import _dauntless_host"`; `ctest --test-dir build -R Frame` (36/36); then full `scripts/check_tests.sh` green. Live-verify: bridge viewscreen shows smoke/debris/explosions/shockwaves and cloak shimmer, matching the exterior view; main view unchanged.
