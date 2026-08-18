# Camera Mode Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AddModeHierarchy` real so BC's cinematic camera keys (F2/F3/F5) actually move the camera.

**Architecture:** BC pushes an always-invalid marker mode as current and resolves the effective mode per-frame by walking name→name hierarchy edges; the F-keys re-point one edge. We implement edge storage + resolution on `CameraObjectClass`, seed the player camera with `MakePlayerCamera`'s markers/edges/player-attr table, call the real SDK `PlayerCameraAsCinematic/AsSpace` from the focus toggle, and add one render branch that drives the exterior view from the player camera's resolved mode while cinematic mode is active.

**Tech Stack:** Python 3.11, pytest. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-08-18-camera-mode-hierarchy-design.md`

## Global Constraints

- **Shared checkout.** Never `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. Temporary mutations: `cp` to /tmp, restore by `cp`, `diff` to prove.
- **Branch:** `feat/camera-named-modes-bc-convention` (checked out).
- **Test gate:** `scripts/check_tests.sh`. Baseline: **0 ctest failures, exactly 1 known pytest failure** (`tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`).
- `ZoomCameraObjectClass.AddModeHierarchy` stays a no-op; `host_loop._viewscreen_scene_feed` must not change; `tests/unit/test_viewscreen_zoom_target_mode.py` must stay green.
- Do NOT hand-add rows to `docs/stub_heatmap.md`.
- Do NOT implement Map/DropAndWatch/TorpCam mode classes — out of scope; their keys degrade to the director keeping the frame.
- Game units; column-vector right-handed rotations (CLAUDE.md).

---

### Task 1: Hierarchy storage + resolution on CameraObjectClass

**Files:**
- Modify: `engine/appc/bridge_set.py` (`CameraObjectClass`: `AddNamedCameraMode` new, `AddModeHierarchy` at `:533` becomes real, `GetCurrentCameraMode` at `:529` resolves)
- Test: `tests/unit/test_camera_mode_stack.py`

**Interfaces:**
- Produces:
  - `CameraObjectClass.AddNamedCameraMode(name: str, mode) -> None` — stores into `_named_modes`, tags `mode._named = name`, sets `mode._owner_camera = self`.
  - `CameraObjectClass.AddModeHierarchy(parent: str, child: str) -> None` — `self._mode_hierarchy[parent] = child` (dict, REPLACING).
  - `CameraObjectClass.GetCurrentCameraMode(*args)` — `(0)` → raw top of stack; no-arg/truthy → hierarchy-resolved (walk edges by `_named` while invalid, cycle-guarded, return first valid else last reached).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_camera_mode_stack.py`:

```python
# ── Mode hierarchy (AddModeHierarchy for real) ───────────────────────────────
# BC pushes an always-invalid marker mode and resolves the EFFECTIVE mode by
# walking name->name hierarchy edges (Camera.py:630-646). The cinematic F-keys
# re-point one edge (CinematicInterfaceHandlers.CameraChase:339) — the
# hierarchy IS the camera selector. GetCurrentCameraMode(0) is the raw top
# (NewMode's identity compare, Camera.py:463); no-arg is resolved
# (Camera.py:478 "may not be the mode we pushed").

def _valid_chase(cam, ship):
    m = cam.GetNamedCameraMode("Chase")
    m.SetAttrIDObject("Target", ship)
    return m


def test_add_named_camera_mode_preempts_the_builder():
    c = _cam()
    marker = ChaseMode()                     # bare: no Target -> never valid
    c.AddNamedCameraMode("InvalidCinematic", marker)
    assert c.GetNamedCameraMode("InvalidCinematic") is marker
    assert marker._named == "InvalidCinematic"


def test_resolution_walks_an_edge_to_a_valid_mode():
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    chase = _valid_chase(c, ship)
    c.AddModeHierarchy("InvalidCinematic", "Chase")
    c.PushCameraMode(marker)
    assert c.GetCurrentCameraMode(0) is marker          # raw
    assert c.GetCurrentCameraMode() is chase            # resolved


def test_edges_replace_not_append():
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    chase = _valid_chase(c, ship)
    target = c.GetNamedCameraMode("Target")
    target.SetAttrIDObject("Source", ship)
    target.SetAttrIDObject("Target", ship)
    c.AddModeHierarchy("InvalidCinematic", "Chase")
    c.AddModeHierarchy("InvalidCinematic", "Target")    # F-key re-point
    c.PushCameraMode(marker)
    assert c.GetCurrentCameraMode() is target


def test_resolution_dead_end_returns_the_invalid_tail():
    """A chain that never reaches a valid mode returns the last (invalid) mode
    — callers gate on IsValid(), so the director keeps the frame."""
    c = _cam()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    c.PushCameraMode(marker)
    resolved = c.GetCurrentCameraMode()
    assert resolved is marker and not resolved.IsValid()


def test_resolution_survives_an_edge_cycle():
    c = _cam()
    a, b = ChaseMode(), ChaseMode()
    c.AddNamedCameraMode("A", a)
    c.AddNamedCameraMode("B", b)
    c.AddModeHierarchy("A", "B")
    c.AddModeHierarchy("B", "A")
    c.PushCameraMode(a)
    resolved = c.GetCurrentCameraMode()      # must terminate
    assert resolved in (a, b)


def test_camera_without_edges_resolves_to_raw_top():
    """Cameras nobody seeds (mission CutsceneCam) behave exactly as today."""
    c = _cam()
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
```

Add the import at the point the file's other camera_modes imports sit: `from engine.appc.camera_modes import ChaseMode` (already imported at top — verify) and reuse the file's existing `_FakeShip`.

- [ ] **Step 2: Run to verify RED**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py -q -k "hierarchy or named_camera_mode or resolution or edges_replace or raw_top"`
Expected: `test_add_named_camera_mode_preempts_the_builder` fails with `AttributeError: ... has no attribute 'AddNamedCameraMode'`; the resolution tests fail returning the marker.
`test_camera_without_edges_resolves_to_raw_top` passes already (regression guard).

- [ ] **Step 3: Implement**

In `engine/appc/bridge_set.py`, on `CameraObjectClass`: replace the `AddModeHierarchy` no-op and extend `GetCurrentCameraMode`:

```python
    def AddNamedCameraMode(self, name, mode) -> None:
        """Register `mode` under `name`, pre-empting the CameraModes.<name>
        builder. BC's MakePlayerCamera uses this for the four always-invalid
        Invalid* markers (Camera.py:624-628)."""
        if "_named_modes" not in self.__dict__:
            self._named_modes = {}
            self._mode_stack = []
        mode._named = name
        mode._owner_camera = self
        self._named_modes[name] = mode

    def AddModeHierarchy(self, parent, child) -> None:
        """Record the fallback edge parent->child (REPLACING any existing edge
        from `parent` — the cinematic F-keys re-point the InvalidCinematic edge
        on every press, CinematicInterfaceHandlers.py:339). Resolution happens
        in GetCurrentCameraMode."""
        if "_mode_hierarchy" not in self.__dict__:
            self._mode_hierarchy = {}
        self._mode_hierarchy[str(parent)] = str(child)

    def GetCurrentCameraMode(self, *args):
        """BC's two reads (Camera.py:463 vs :478): with a falsy first arg,
        the RAW top of the mode stack; with no arg, the hierarchy-RESOLVED
        mode — from the raw top, follow _mode_hierarchy edges by _named tag
        while the mode is invalid. Returns the first valid mode, or the last
        mode reached when the walk dead-ends (callers gate on IsValid())."""
        stack = self._ensure_stack()
        top = stack[-1] if stack else None
        if args and not args[0]:
            return top
        mode = top
        edges = getattr(self, "_mode_hierarchy", None)
        if mode is None or not edges:
            return mode
        seen = set()
        while not mode.IsValid():
            name = getattr(mode, "_named", None)
            nxt = edges.get(name) if name is not None else None
            if nxt is None or nxt in seen:
                return mode
            seen.add(nxt)
            nxt_mode = self.GetNamedCameraMode(nxt)
            if nxt_mode is None:
                return mode
            mode = nxt_mode
        return mode
```

Delete the old no-op comment block at `:445` region ONLY if it is the `AddModeHierarchy stays a no-op` line for THIS class — update it to describe the new behaviour instead. The `ZoomCameraObjectClass` `_LoudStub` path is untouched.

- [ ] **Step 4: Run to verify GREEN**

Run: `uv run pytest tests/unit/test_camera_mode_stack.py tests/unit/test_viewscreen_zoom_target_mode.py tests/unit/test_camera_modes.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_camera_mode_stack.py
git commit -m "feat(camera): real AddModeHierarchy + resolved GetCurrentCameraMode"
```

---

### Task 2: Seed the player camera; player attrs on SetPlayer

**Files:**
- Modify: `engine/core/game.py` (`GetPlayerCamera` at `:375`; `SetPlayer`)
- Test: `tests/unit/test_player_camera_seeding.py` (new)

**Interfaces:**
- Consumes: Task 1's `AddNamedCameraMode` / `AddModeHierarchy`.
- Produces: the lazy player camera carries the four `Invalid*` markers + BC's default edges; after `SetPlayer(ship)`, the 18-row table's modes hold the player.

- [ ] **Step 1: Write the failing tests** (new file `tests/unit/test_player_camera_seeding.py`)

```python
"""GetPlayerCamera seeds what Camera.MakePlayerCamera would have: the four
always-invalid Invalid* markers (Camera.py:624-628) and the default hierarchy
edges (Camera.py:630-646). Game.SetPlayer applies the player-attr table
(Camera.py:685-703) so Chase/Target/... anchor on the player."""
import App
from engine.appc.camera_modes import ChaseMode


def _game():
    from engine.core.game import Game
    return Game()


def test_player_camera_has_the_four_invalid_markers():
    cam = _game().GetPlayerCamera()
    for name in ("InvalidViewscreen", "InvalidSpace",
                 "InvalidCinematic", "InvalidMap"):
        m = cam.GetNamedCameraMode(name)
        assert isinstance(m, ChaseMode), name
        assert not m.IsValid(), name          # never given a Target


def test_player_camera_has_bc_default_edges():
    cam = _game().GetPlayerCamera()
    e = cam._mode_hierarchy
    assert e["InvalidCinematic"] == "DropAndWatch"
    assert e["InvalidSpace"] == "Target"
    assert e["Target"] == "Chase"
    assert e["ZoomTarget"] == "Chase"
    assert e["TorpCam"] == "Chase"
    assert e["CinematicReverseTarget"] == "Chase"
    assert e["InvalidMap"] == "Map"
    assert e["InvalidViewscreen"] == "ViewscreenZoomTarget"
    assert e["ViewscreenZoomTarget"] == "ViewscreenForward"


def test_set_player_puts_the_player_on_the_mode_table():
    from engine.appc.ships import ShipClass_Create
    g = _game()
    cam = g.GetPlayerCamera()
    ship = ShipClass_Create("SeedPlayer")
    g.SetPlayer(ship)
    chase = cam.GetNamedCameraMode("Chase")
    assert chase.GetAttrIDObject("Target") is ship
    assert chase.IsValid()
    tgt = cam.GetNamedCameraMode("Target")
    assert tgt.GetAttrIDObject("Source") is ship
    rev = cam.GetNamedCameraMode("CinematicReverseTarget")
    assert rev.GetAttrIDObject("Target") is ship


def test_set_player_none_is_safe():
    g = _game()
    g.GetPlayerCamera()
    g.SetPlayer(None)                        # must not raise
```

NOTE for the implementer: check how existing tests construct `Game` /
obtain the singleton (`engine/core/game.py`, `tests/` neighbours) — if a
factory or fixture is the established route, use it instead of bare
`Game()`, and adjust `_game()` accordingly. Check the real `SetPlayer`
signature before writing the seeding call into it.

- [ ] **Step 2: RED** — `uv run pytest tests/unit/test_player_camera_seeding.py -q`; expected failures: no markers (builder returns bare modes but `InvalidCinematic` has no `CameraModes` builder → `GetNamedCameraMode` returns None → isinstance fails), no `_mode_hierarchy`, attrs unset.

- [ ] **Step 3: Implement**

In `GetPlayerCamera`'s lazy-create branch, after constructing the camera, seed exactly BC's defaults:

```python
            from engine.appc.camera_modes import CameraMode_Create
            cam = self._player_camera
            # MakePlayerCamera's four always-invalid markers: bare Chase modes
            # never given a Target (Camera.py:624-628).
            for _name in ("InvalidViewscreen", "InvalidSpace",
                          "InvalidCinematic", "InvalidMap"):
                cam.AddNamedCameraMode(_name, CameraMode_Create("Chase", cam))
            # Default fallback edges, verbatim Camera.py:630-646.
            for _parent, _child in (
                ("InvalidViewscreen", "ViewscreenZoomTarget"),
                ("ViewscreenZoomTarget", "ViewscreenForward"),
                ("InvalidSpace", "Target"),
                ("Target", "Chase"),
                ("ZoomTarget", "Chase"),
                ("InvalidCinematic", "DropAndWatch"),
                ("TorpCam", "Chase"),
                ("CinematicReverseTarget", "Chase"),
                ("InvalidMap", "Map"),
            ):
                cam.AddModeHierarchy(_parent, _child)
```

In `SetPlayer`, after the player is stored (find the exact point by reading the method), apply the table — guard on `player is not None`, and only touch the camera if `self._player_camera` exists OR create it via `GetPlayerCamera()` (BC applies on every player change; creating is correct):

```python
        # Camera.MakePlayerCamera_PlayerChanged's table (Camera.py:685-703):
        # anchor every player-relative camera mode on the new player.
        if player is not None:
            cam = self.GetPlayerCamera()
            for _mode_name, _attr in (
                ("Chase", "Target"), ("Target", "Source"),
                ("ReverseChase", "Target"), ("ZoomTarget", "Source"),
                ("Map", "Target"), ("WideTarget", "Source"),
                ("FreeOrbit", "Target"), ("DropAndWatch", "Target"),
                ("ViewscreenZoomTarget", "Source"),
                ("ViewscreenForward", "Target"), ("ViewscreenBack", "Target"),
                ("ViewscreenLeft", "Target"), ("ViewscreenRight", "Target"),
                ("ViewscreenUp", "Target"), ("ViewscreenDown", "Target"),
                ("FirstPerson", "Target"), ("TorpCam", "Target"),
                ("CinematicReverseTarget", "Target"),
            ):
                _mode = cam.GetNamedCameraMode(_mode_name)
                if _mode is not None:
                    _mode.SetAttrIDObject(_attr, player)
```

- [ ] **Step 4: GREEN** — the new file plus `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py tests/host/test_comm_viewscreen_feed.py tests/host/test_viewscreen_scene_feed.py -q` (SetPlayer + viewscreen interplay).

- [ ] **Step 5: Commit**

```bash
git add engine/core/game.py tests/unit/test_player_camera_seeding.py
git commit -m "feat(camera): seed MakePlayerCamera markers, edges and player attrs"
```

---

### Task 3: Toggle drives the SDK camera switch

**Files:**
- Modify: `engine/appc/top_window.py` (`ToggleCinematicWindow`)
- Test: `tests/unit/test_top_window.py`

**Interfaces:**
- Consumes: Tasks 1+2; the real SDK `Camera.PlayerCameraAsCinematic/AsSpace` (`Camera.py:810-823`), which call `Game_GetCurrentGame().GetPlayerCamera()` and `NewMode(..., UseInvalid=1)`.
- Produces: entering cinematic mode leaves the player camera's RAW current mode named `InvalidCinematic`; exiting leaves it `InvalidSpace`; stack depth stable across toggles (NewMode uses bReplace=1).

- [ ] **Step 1: Failing tests** (append to `tests/unit/test_top_window.py`)

```python
def test_toggle_switches_the_player_camera_to_cinematic_and_back():
    """BC's engine calls Camera.PlayerCameraAsCinematic/AsSpace on window
    switch; our toggle is that seam. Raw mode (arg 0) is the marker; NewMode
    replaces (bReplace=1) so the stack must not grow with repeated toggles."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cam = App.Game_GetCurrentGame().GetPlayerCamera()

    tw.ToggleCinematicWindow()               # enter
    raw = cam.GetCurrentCameraMode(0)
    assert getattr(raw, "_named", None) == "InvalidCinematic"

    tw.ToggleCinematicWindow()               # exit
    raw = cam.GetCurrentCameraMode(0)
    assert getattr(raw, "_named", None) == "InvalidSpace"

    depth_before = len(cam._mode_stack)
    for _ in range(4):
        tw.ToggleCinematicWindow()
    assert len(cam._mode_stack) == depth_before
```

NOTE: check how this file obtains a Game with a working
`Game_GetCurrentGame()` (other tests in the suite use it — mirror them). If
the fixture environment needs a game created first, do what the neighbouring
tests do.

- [ ] **Step 2: RED** — the raw mode has no `_named` / stack unchanged by toggle.

- [ ] **Step 3: Implement** — in `ToggleCinematicWindow`, after the focus flip (and the existing crew-menu drop + handler init), call the SDK:

```python
        # BC's engine switches the player camera on window activation
        # (PlayerCameraAsCinematic/AsSpace); this toggle is our seam for it.
        # Guarded like _init_cinematic_handlers: a Camera failure must not
        # wedge the toggle, but must not be silent.
        try:
            import Camera
            if self._focus is cine:
                Camera.PlayerCameraAsCinematic()
            else:
                Camera.PlayerCameraAsSpace()
        except Exception as exc:  # noqa: BLE001
            print("[cinematic] player-camera mode switch failed:", exc)
```

Mind the ordering: the focus flip has already happened, so `self._focus is cine` distinguishes enter from exit. `Camera.PlayerCameraAs*` calls `pCamera.Update(...)` at the end — if that method does not exist on our camera, check what the SDK passes and add a tolerant no-op `Update(*args)` ONLY if `CameraObjectClass` lacks one (check first; `CameraMode.Update` exists but the CAMERA's may not).

- [ ] **Step 4: GREEN** — `uv run pytest tests/unit/test_top_window.py tests/integration/test_cinematic_key_routing.py -q`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(cinematic): toggle switches the player camera via the SDK Camera module"
```

---

### Task 4: Render branch — drive the frame from the resolved mode

**Files:**
- Modify: `engine/host_loop.py` (`_active_cutscene_camera` at ~`:5218`)
- Test: `tests/host/test_cutscene_camera_selection.py`

**Interfaces:**
- Consumes: `TopWindow.is_cinematic_active()`, `Game.GetPlayerCamera()`, Task 1's resolved `GetCurrentCameraMode()`.
- Produces: while cinematic mode is active and the player camera's resolved mode is valid, `_active_cutscene_camera` returns `(player_camera, resolved_mode)`; otherwise existing behaviour byte-for-byte.

- [ ] **Step 1: Failing tests** (append to `tests/host/test_cutscene_camera_selection.py` — read the file's existing fixtures first and reuse them; they already fake the rendered set and modes)

```python
def test_cinematic_mode_drives_the_player_camera_resolved_mode():
    """F9 active + valid resolved mode -> the exterior view comes from the
    player camera, not the mission cutscene camera or the director."""
    import App
    from engine.appc import top_window
    from engine.host_loop import _active_cutscene_camera
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    game = App.Game_GetCurrentGame()
    cam = game.GetPlayerCamera()

    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("CinePlayer")
    game.SetPlayer(ship)
    tw.ToggleCinematicWindow()
    # F2: re-point the edge to Chase (what CameraChase does).
    cam.AddModeHierarchy("InvalidCinematic", "Chase")

    got = _active_cutscene_camera()
    assert got is not None
    got_cam, got_mode = got
    assert got_cam is cam
    assert getattr(got_mode, "_named", None) == "Chase"
    assert got_mode.IsValid()


def test_cinematic_mode_with_unresolvable_mode_falls_through():
    """Default edge (InvalidCinematic->DropAndWatch) dead-ends invalid when no
    F-key has re-pointed it: the director keeps the frame (return None here,
    absent a mission cutscene camera)."""
    import App
    from engine.appc import top_window
    from engine.host_loop import _active_cutscene_camera
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    game = App.Game_GetCurrentGame()
    game.GetPlayerCamera()
    tw.ToggleCinematicWindow()
    assert _active_cutscene_camera() is None


def test_cinematic_inactive_changes_nothing():
    from engine.appc import top_window
    from engine.host_loop import _active_cutscene_camera
    top_window.reset_for_tests()
    assert _active_cutscene_camera() is None
```

(Adapt to the file's fixture conventions — e.g. if the existing tests monkeypatch `g_kSetManager` or need a rendered set, follow suit; the assertions above are the contract.)

- [ ] **Step 2: RED** — first test returns None today.

- [ ] **Step 3: Implement** — at the TOP of `_active_cutscene_camera`, before the rendered-set logic:

```python
    # BC's cinematic mode (F9): the player camera's hierarchy-resolved mode
    # drives the exterior view. Only while the cinematic window holds focus,
    # and only when the resolution actually lands on a valid mode — the
    # default InvalidCinematic->DropAndWatch edge dead-ends invalid until an
    # F-key re-points it, and then the director keeps the frame as before.
    import App as _App
    _top = _App.TopWindow_GetTopWindow()
    if _top is not None and getattr(_top, "is_cinematic_active", None) \
            and _top.is_cinematic_active():
        _game = _App.Game_GetCurrentGame()
        _pcam = _game.GetPlayerCamera() if _game is not None else None
        if _pcam is not None:
            _mode = _pcam.GetCurrentCameraMode()
            if _mode is not None and _mode.IsValid():
                return (_pcam, _mode)
```

Keep the existing body unchanged below it.

- [ ] **Step 4: GREEN + gate** — `uv run pytest tests/host/test_cutscene_camera_selection.py tests/host/test_comm_viewscreen_feed.py tests/host/test_viewscreen_scene_feed.py -q`, then the full `scripts/check_tests.sh`.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_cutscene_camera_selection.py
git commit -m "feat(cinematic): drive the exterior view from the resolved player-camera mode"
```

---

## After the plan

**Live pass required:** F9 → F2 (chase), F3 (reverse-target cycle), F5 (wide
target); F9 again returns the director. Regression checks: bridge viewscreen
zoom, one mission cutscene (E1M1 intro or a warp), F1–F5 crew menus outside
cinematic mode. F1/F4/F6 are expected no-ops (mode classes out of scope).
