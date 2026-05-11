# Bridge Interior Render PoC — Design

**Status:** Draft, pre-implementation.
**Sub-project:** Bridge view modality, stage 2 — replaces the empty
"forward-from-ship-origin" stub from the previous PoC
([2026-05-11-bridge-view-poc-design.md](2026-05-11-bridge-view-poc-design.md))
with an actual rendered DBridge interior, mouse-look, and a clean
two-pass renderer architecture that pays forward to the eventual
viewscreen render-to-texture.

## Why this scope

The previous bridge PoC proved the input/camera dispatch seam: pressing
space toggles a `_ViewModeController` flag, the player input is rerouted
through a no-input reader (so engines keep coasting), and a "BRIDGE
VIEW" label appears. But the camera just anchors at ship origin looking
along ship-Y — there's no actual bridge to see. Any ship in the scene
is invisible from the inside; the player effectively flies a blank
camera around space.

This stage replaces the stub with the real thing: load `DBridge.nif`,
add a second renderer pass for it, lock the cursor, and let the player
mouse-look around the rendered bridge interior. Doing this on top of
the working dispatch seam means the architecture stays clean — every
addition (RTT viewscreen, crew, lighting, click-to-station) plugs into
the same pass abstraction without restructuring.

The two-pass architecture is the key load-bearing decision. The
original BC engine renders bridge and space as separate `SetClass`
instances that the C++ engine selects between via a `TopWindow` flag,
with the space scene continuously ticked so its viewscreen camera can
be sampled and applied as a texture to the bridge's viewscreen
geometry. We're not building the texture sample yet, but we are
building the pass split, so the eventual RTT lands as a target
redirect rather than a refactor.

## Goals

1. Add a **bridge pass** to the C++ renderer, sibling to the existing
   space pass. Each frame: render space pass + special passes
   (backdrop, dust, sun, glow, specular) → if bridge pass enabled,
   `glClear(GL_DEPTH_BUFFER_BIT)` and render bridge pass.
2. Load `game/data/Models/Sets/DBridge/DBridge.nif` eagerly at host
   startup. Single bridge instance, owned by the renderer host across
   mission swaps (bridge geometry is mission-independent).
3. Add a `_BridgeCamera` controller in
   [engine/host_loop.py](../../../engine/host_loop.py) that anchors at
   the bridge-local pose pinned by
   [MissionLib.py:1475-1483](../../../sdk/Build/scripts/MissionLib.py#L1475-L1483)
   (position `(0, 50, 47)`, axis-angle rotation `(-1.55, 0, 0, 1)`,
   near/far `(1.0, 800.0)`) and accumulates yaw/pitch from mouse
   motion. The bridge frame is **ship-local**, so the bridge banks and
   pitches with the ship as it manoeuvres.
4. Expose mouse-delta and cursor-lock from the C++ host bindings:
   `consume_mouse_delta()` and `set_cursor_locked(bool)`. Cursor locks
   on enter-bridge and unlocks on enter-exterior, ESC, or window
   focus loss.
5. Wire the toggle: on enter-bridge — `bridge_pass_set_enabled(True)`,
   `set_cursor_locked(True)`. On exit (toggle back, ESC) — both
   `False`. The existing space-coast behaviour from the previous PoC
   is preserved.
6. Cover with unit tests (camera math, mouse accumulation, ship
   coupling, toggle wiring) and a live visual-verification step.

## Non-goals (this stage)

These are deferred deliberately. Each gets a thorough treatment in the
**Deferred work** section below so the future implementer doesn't have
to redo the research.

- Render-to-texture viewscreen showing the live space scene on the
  bridge wall.
- Loading `DBridgeViewScreen.nif` — the viewscreen geometry sub-NIF.
  A hole in the front wall is acceptable for the PoC.
- Bridge crew (Felix, Saffi, Miguel, Brex, Kiska) and their per-ship
  animations, station hardpoints, and dialog.
- Per-ship-class bridge selection (the original engine has a hardcoded
  conditional in `MissionLib`; we hardcode DBridge unconditionally).
- Interior lighting tuning beyond a flat ambient. No directionals,
  no point lights, no console emissive.
- Click-to-station / interactive consoles, menu wiring (`HelmMenuHandlers`,
  `TacticalMenuHandlers`, etc.).
- Bridge ambient audio (the bridge hum loop).
- Smooth space ↔ bridge transition (today: hard cut on space-press).
- Mouse-look in exterior mode (orbit camera stays arrow-key driven).

## Architecture

### Two-pass renderer

Conceptually the C++ frame loop becomes:

```
each frame:
    clear color + depth
    render space pass (camera = exterior camera, instances = ships + planets)
    render special passes (backdrop, dust, sun, glow, specular)
    if bridge_pass_enabled:
        clear depth only
        render bridge pass (camera = bridge camera, instances = bridge instances)
    present
```

In bridge mode the space pass and special passes still execute even
though they're entirely occluded by the bridge geometry. This is
slightly wasteful — but it's the same set of GPU calls we make today,
and it means the eventual RTT viewscreen lands by changing the space
pass's *target* (texture instead of main framebuffer) rather than by
adding a "render space here" path that didn't exist before.

The bridge pass uses the existing standard mesh shader. No new shaders
needed. Lighting is a flat ambient hardcoded in the C++ frame routine
(`(1.0, 1.0, 1.0) × 19` per `MissionLib`'s ambient light constant,
scaled appropriately for our renderer's lighting math).

### Instance ownership

Bridge instances are tracked separately from space instances:

- C++: a new `std::vector<InstanceHandle> bridge_instances_` member on
  the renderer state, distinct from the existing instance list. The
  bridge pass iterates only this vector.
- Python: `HostController` gets a `bridge_instance: Optional[int]`
  field for the single DBridge geometry instance. It's created once in
  `host_loop.run()`'s startup block and persists across mission swaps
  (since `MissionSession.teardown` only destroys ship/planet instances,
  not bridge instances). The DBridge handle is cached in
  `HostController.nif_to_handle` like any other NIF.

### Camera split

The bridge pass has its own camera, separate from the space camera.
The host loop calls `r.set_camera(...)` for the space pass each tick
(unchanged from today) and `r.set_bridge_camera(...)` only when in
bridge mode. The C++ side holds two camera state structs and the
frame loop selects the right one per pass.

## C++ binding additions

Five new functions in [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc):

| Binding | Signature | Purpose |
|---|---|---|
| `r.create_bridge_instance` | `(int handle) -> int iid` | Like `create_instance` but adds to the bridge pass list. |
| `r.set_bridge_camera` | `(eye, target, up, fov_y_rad, near, far)` | Per-pass camera state. Same arg shape as `set_camera`. |
| `r.bridge_pass_set_enabled` | `(bool enabled)` | Mode flag the frame loop checks. Default `False`. |
| `r.consume_mouse_delta` | `() -> (float dx, float dy)` | Accumulator-and-reset for mouse motion in pixels. Mirrors `consume_scroll_y`. |
| `r.set_cursor_locked` | `(bool locked)` | GLFW: `glfwSetInputMode(win, CURSOR, locked ? CURSOR_DISABLED : CURSOR_NORMAL)`. Disabled mode hides the cursor and provides raw deltas via the cursor-pos callback. |

The `consume_mouse_delta` accumulator lives in C++, fed by GLFW's
cursor-position callback (`glfwSetCursorPosCallback`). Each callback
fires `dx = newX - lastX; dy = newY - lastY; accum_x += dx; accum_y += dy;
lastX = newX; lastY = newY;`. `consume_mouse_delta()` returns
`(accum_x, accum_y)` and zeroes them. When the cursor is unlocked, the
callback still fires but accumulation is gated off (or the values are
returned but ignored Python-side — we'll pick the simpler one during
implementation).

### Frame loop changes

In whichever C++ file owns `r.frame()` (likely
[native/src/renderer/](../../../native/src/renderer/) — confirmed
during implementation), append after the existing draw calls:

```cpp
if (bridge_pass_enabled_) {
    glClear(GL_DEPTH_BUFFER_BIT);
    bind_camera(bridge_camera_);
    draw_instances(bridge_instances_);
}
```

The `draw_instances` helper already exists for the space pass; the
only new code is the conditional, the depth clear, and the camera
swap. No new shader, no new descriptor sets.

## Python wiring

### Startup (in `host_loop.run()`)

After the renderer init and before the mission loader runs:

```python
DBRIDGE_NIF_PATH = str(PROJECT_ROOT / "game" / "data" / "Models" / "Sets" / "DBridge" / "DBridge.nif")
DBRIDGE_TEX_SEARCH = str(PROJECT_ROOT / "game" / "data" / "Models" / "Sets" / "DBridge")

IDENTITY_MAT4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]
bridge_handle = r.load_model(DBRIDGE_NIF_PATH, DBRIDGE_TEX_SEARCH)
controller.bridge_instance = r.create_bridge_instance(bridge_handle)
# Bridge instance world transform is irrelevant — the bridge pass
# camera works in bridge-local frame, and only the bridge pass renders
# this instance. Identity transform, set once.
r.set_world_transform(controller.bridge_instance, IDENTITY_MAT4)
```

No per-tick transform updates are needed; the bridge geometry doesn't
move, the camera does the work.

### Per-tick (in `host_loop.run()`'s while loop)

A new `_BridgeCamera` instance constructed alongside the existing
`_PlayerControl` / `_CameraControl` / `_ViewModeController`. The
existing `_apply_input` and `_compute_camera` helpers gain bridge-mode
handling:

- `_apply_input` in bridge mode (already calls `player.apply()` with
  no-input reader) additionally calls `bridge_camera.apply(player, dt,
  mouse_dx, mouse_dy)`.
- `_compute_camera` in bridge mode returns the bridge pass's camera
  pose (still wired into `r.set_camera(...)` for the space pass —
  unchanged — and `r.set_bridge_camera(...)` is called separately).

The toggle gains side-effects:

- On toggle to bridge: `r.bridge_pass_set_enabled(True)`,
  `r.set_cursor_locked(True)`.
- On toggle to exterior: `r.bridge_pass_set_enabled(False)`,
  `r.set_cursor_locked(False)`.
- ESC handler also forces both `False` and toggles to exterior (in
  addition to its existing mission-picker dismissal).

The "BRIDGE VIEW" UI panel from the previous stage is unchanged.

## `_BridgeCamera` design

```python
class _BridgeCamera:
    """First-person bridge camera with mouse-look.

    Anchored at the MissionLib-pinned DBridge captain's-chair pose in
    ship-local frame. Mouse motion accumulates yaw (around bridge-up)
    and pitch (around bridge-right). Yaw wraps freely; pitch clamps at
    ±85° to avoid pole flip.

    Camera world pose = ship_world_pose * bridge_local_pose * mouse_rotation,
    so the bridge banks and pitches with the ship as it manoeuvres.
    """

    # MissionLib.py:1475-1483 — DBridge maincamera pose.
    BRIDGE_LOCAL_OFFSET = (0.0, 50.0, 47.0)
    # Axis-angle (-1.55, 0, 0, 1): -1.55 rad ≈ -88.8° around X axis.
    # Convention to verify on first run; iterating visually is cheap.
    BRIDGE_BASE_PITCH_RAD = -1.55

    NEAR = 1.0
    FAR  = 800.0
    # FOV_Y_RAD and MOUSE_SENSITIVITY are PoC starting values, expected
    # to be tuned by feel during visual verification.
    FOV_Y_RAD = math.radians(60.0)
    MOUSE_SENSITIVITY = 0.005       # rad per pixel
    PITCH_LIMIT_RAD   = math.radians(85)

    def __init__(self):
        self.yaw_rad   = 0.0   # accumulated mouse yaw
        self.pitch_rad = 0.0   # accumulated mouse pitch (clamped)

    def apply(self, mouse_dx: float, mouse_dy: float) -> None:
        """Accumulate mouse delta into yaw/pitch."""
        self.yaw_rad   -= mouse_dx * self.MOUSE_SENSITIVITY
        self.pitch_rad += mouse_dy * self.MOUSE_SENSITIVITY
        if self.pitch_rad >  self.PITCH_LIMIT_RAD: self.pitch_rad =  self.PITCH_LIMIT_RAD
        if self.pitch_rad < -self.PITCH_LIMIT_RAD: self.pitch_rad = -self.PITCH_LIMIT_RAD

    def compute_camera(self, ship_loc, ship_rot) -> tuple:
        """Return (eye, target, up) in world space for r.set_bridge_camera."""
        # 1. Build local pose: BRIDGE_LOCAL_OFFSET, base pitch, then yaw + pitch.
        # 2. Rotate the local forward/up by accumulated yaw (around local-up)
        #    then pitch (around local-right).
        # 3. Transform local eye/target/up by ship_rot, then translate by ship_loc.
        # Math expanded during implementation; see test cases for invariants.
        ...
```

## Testing

Unit tests in a new file
[tests/host/test_bridge_camera.py](../../../tests/host/test_bridge_camera.py),
mirroring the `_CameraControl` test pattern:

1. `test_bridge_camera_starts_at_zero_yaw_pitch` — fresh instance has
   `yaw_rad == 0`, `pitch_rad == 0`.
2. `test_mouse_delta_accumulates_yaw_and_pitch` — non-zero `(dx, dy)`
   updates accumulators with the right signs (right→look-right,
   up→look-up).
3. `test_pitch_clamps_at_limit` — driving pitch past PITCH_LIMIT_RAD
   in either direction settles at the clamp.
4. `test_yaw_wraps_freely` — driving yaw past π radians does not
   clamp; large rotations produce the expected total.
5. `test_camera_anchor_at_ship_origin_with_identity_ship` — at zero
   yaw/pitch with identity ship rotation and ship at origin, eye =
   `BRIDGE_LOCAL_OFFSET` (rotated by base pitch), target along the
   resulting forward direction.
6. `test_camera_couples_to_ship_rotation` — rotating the ship 90°
   around its Z axis rotates the bridge camera's eye and forward by
   the same 90° (the bridge is rigidly attached to the ship).

Plus, in
[tests/host/test_view_mode.py](../../../tests/host/test_view_mode.py)
(extended from the previous PoC):

7. `test_toggle_to_bridge_enables_pass_and_locks_cursor` — given a
   recording fake renderer, toggling to bridge calls
   `bridge_pass_set_enabled(True)` and `set_cursor_locked(True)`
   exactly once each.
8. `test_toggle_to_exterior_disables_pass_and_releases_cursor` — the
   reverse on the second toggle.
9. `test_esc_in_bridge_mode_returns_to_exterior` — ESC handler in
   bridge mode disables the pass and releases the cursor.

C++ binding-level smoke test in a new
[tests/host/test_bridge_bindings.py](../../../tests/host/test_bridge_bindings.py):

10. All five new bindings exist on `_open_stbc_host`, accept the
    documented argument shapes without raising, and (where applicable)
    return values of the expected type.

Live visual verification:

11. Launch `./build/open_stbc`. Default exterior view unchanged.
    Press space → bridge interior renders, cursor disappears, mouse
    motion looks around the bridge. Press space again → return to
    exterior, cursor reappears, ship resumes. Engages → ship coasts
    while in bridge view (existing PoC behaviour preserved). Press
    ESC during bridge mode → return to exterior, cursor released.

## Files touched

- **Create**
  - [tests/host/test_bridge_camera.py](../../../tests/host/test_bridge_camera.py)
  - [tests/host/test_bridge_bindings.py](../../../tests/host/test_bridge_bindings.py)
- **Modify**
  - [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc)
    — add five bindings, GLFW cursor callback, mouse-delta accumulator.
  - [native/src/renderer/](../../../native/src/renderer/) — add bridge
    pass to the frame loop, bridge instance vector, bridge camera
    state. Exact files to be picked during implementation by reading
    the existing pass code (backdrop / dust / sun).
  - [engine/host_loop.py](../../../engine/host_loop.py) — add
    `_BridgeCamera`, extend `_apply_input`/`_compute_camera`, extend
    `_ViewModeController.toggle()` side-effects, ESC handler, startup
    bridge load.
  - [tests/host/test_view_mode.py](../../../tests/host/test_view_mode.py)
    — three new toggle/ESC tests.

---

## Deferred work — thorough record

Each item below is explicitly out of scope for this stage, but is
recorded with enough mechanism, file references, and source of
evidence that the future implementer can pick it up cold.

### D1. Render-to-texture viewscreen

**Goal:** Show the live space scene on the bridge's main viewscreen
surface (the front wall console where `DBridgeViewScreen.nif` lives).

**Original engine mechanism:**

The engine wires a "remote camera" from the space set into the
viewscreen object via Python:

```python
# LoadBridge.py:88-113, BridgeHandlers.py:1277-1305
pCamera = MissionLib.GetViewScreenCamera()        # camera in the "space" set
pViewScreen.SetRemoteCam(pCamera)
pViewScreen.SetIsOn(1)                            # turn the viewscreen on
# Per tick, C++ renders pCamera's view to a texture and applies it to
# the viewscreen geometry's primary material.
```

The `ViewScreenObject` is created from a NIF
(`ViewScreenObject_Create("data/Models/Sets/DBridge/DBridgeViewScreen.nif")`)
and added to the bridge set. The viewscreen camera is independent of
the player's main exterior camera — it can pan
forward/port/starboard/aft/up/down and zoom independently
([BridgeHandlers.py:1277-1338](../../../sdk/Build/scripts/BridgeHandlers.py#L1277-L1338)).

**What we already have that pays forward:**

The two-pass architecture from this PoC. To add RTT:

1. Add a `RenderTarget` abstraction in C++ — colour texture + depth
   renderbuffer at a fixed resolution (start with 1024×1024).
2. Change the space pass binding to optionally target a
   `RenderTarget` instead of the main framebuffer. New API:
   `r.set_space_pass_target("main" | "viewscreen")`.
3. Identify the viewscreen mesh inside `DBridgeViewScreen.nif` (likely
   a named node — needs NifSkope inspection; see OQ-V1 in the agent
   research). Mark its primary material to sample from the
   `viewscreen` render target instead of its disk texture.
4. In bridge mode, set the space pass target to `viewscreen`, render
   space pass into the texture, then render bridge pass (which
   samples that texture for the viewscreen mesh) into main.

**What needs research before implementation:**

- The viewscreen mesh's identification in the NIF. Inspect
  `DBridgeViewScreen.nif` in NifSkope to find the named geometry node
  and its current material/texture binding.
- Texture resolution and format — empirical, start at 1024×1024 RGBA8.
- Mipmap policy for the viewscreen texture (probably none — it's
  always sampled at near-1:1 from the bridge camera).
- Whether the viewscreen camera's FOV / aspect ratio differs from the
  space camera's. The original engine has a separate frustum
  ([MissionLib.py:1487-1489](../../../sdk/Build/scripts/MissionLib.py#L1487-L1489)
  shows the viewscreen camera's frustum is halved in width).

### D2. `DBridgeViewScreen.nif` static load

**Goal:** Load the viewscreen geometry sub-NIF so there isn't a hole
in the bridge's front wall.

**Mechanism:** `r.load_model("data/Models/Sets/DBridge/DBridgeViewScreen.nif", ...)`
plus `r.create_bridge_instance(handle)` and an identity world
transform, mirroring the DBridge.nif load. Same pattern as the main
bridge geometry; one extra instance in the bridge pass list.

**Caveat:** Without RTT (D1), the viewscreen surface will sample its
disk-baked default texture (a generic black/blue panel). Acceptable
visual stub but visually distinct from the working viewscreen.

### D3. Bridge crew

**Goal:** Render the five core crew (Helm, Tactical, XO, Science,
Engineer) at their stations, with appropriate animations.

**Original mechanism:** `LoadBridge.py:176-234` calls character
factories like `Bridge.Characters.Felix.CreateCharacter(pBridgeSet)`
for each crew member. They are added to the bridge set and remain
across bridge config changes. Per-bridge `ConfigureCharacters()`
sets the animations appropriate to that bridge layout (which is why
the Sovereign-bridge file has the long list of `EB_*.nif` animation
loads in
[SovereignBridge.py:201-223](../../../sdk/Build/scripts/Bridge/SovereignBridge.py#L201-L223)).

**Crew identities** (from
[docs/original_game_reference/ui/bridge-mode.md:48-57](../../../docs/original_game_reference/ui/bridge-mode.md#L48-L57)):

| Station | Default character | Position |
|---|---|---|
| Helm / Conn | Ensign Kiska LoMar | Port-forward |
| Tactical | Lt. Felix Savali | Starboard-forward |
| XO / First Officer | Cmdr. Saffi Larsen | Centre-aft of captain |
| Science | Lt. Cmdr. Miguel Diaz | Starboard-aft |
| Engineering | Lt. Cmdr. Brex | Port-aft / Engineering set |
| Guest (variable) | Picard, Data, Saalek, etc. | Optional next to captain |

**What needs implementation:**

- A character/skeletal-mesh renderer (we don't have one yet — current
  renderer handles static meshes only).
- Animation playback (state machine driven by which station the
  character is at, what they're doing).
- Station hardpoints — the bridge NIF has named nodes for crew
  positions; characters get parented to those nodes.
- Per-character menu handlers (`HelmCharacterHandlers.py`,
  `TacticalCharacterHandlers.py`, etc.) for click-to-talk dialogues.

This is genuinely large — it's likely 3+ sub-PoCs of its own.

### D4. Per-ship-class bridge selection

**Goal:** Load the right bridge for the player's ship (Sovereign-class
ships use EBridge.nif, some others use DBridge.nif, factions have
their own bridges).

**Original mechanism:** Mission scripts call
`LoadBridge.Load("SovereignBridge")` (or similar) explicitly. The
hardcoded conditional in
[MissionLib.py:1474-1480](../../../sdk/Build/scripts/MissionLib.py#L1474-L1480)
shows the engine has an internal D/E bridge dispatch by NIF path.

**Bridge inventory shipped with the game:**

| Bridge | Likely class/faction | NIF Path |
|---|---|---|
| DBridge | Federation (D-class — exact ship TBD) | `data/Models/Sets/DBridge/DBridge.nif` |
| EBridge | Federation Sovereign-class (Enterprise-E) | `data/Models/Sets/EBridge/EBridge.nif` |
| Cardassian | Cardassian | `data/Models/Sets/Cardassian/cardbridge.NIF` |
| Romulan | Romulan | `data/Models/Sets/Romulan/romulanbridge.NIF` |
| Klingon BOP | Klingon | `data/Models/Sets/Klingon/BOPbridge.NIF` |
| Ferengi | Ferengi | `data/Models/Sets/Ferengi/ferengibridge.NIF` |
| Kessok | Kessok | `data/Models/Sets/Kessok/kessokbridge.NIF` |

**What needs implementation:**

- A ship-class-to-bridge mapping (lives where? — a config file or a
  Python module). Only `SovereignBridge.py` and `GalaxyBridge.py`
  exist in the SDK's `Bridge/` folder — there's no `DBridge.py`,
  suggesting the per-mission `*BRIDGE_P.py` files (e.g.
  `Maelstrom/Episode2/E2M1/DBridge_P.py`) are scenario-specific
  placement scripts, not class configs.
- The `MissionLib.py:1474-1480` hardcoded conditional gives camera
  poses for both DBridge and EBridge — so for a "swap to EBridge"
  story we already have the camera coords.
- Asset packing: bridge NIFs are large; loading all of them eagerly
  would inflate startup memory significantly. Lazy load on first
  bridge-toggle for the active ship.

### D5. Bridge interior lighting

**Goal:** Replace the flat ambient with proper interior lighting
(panel emissives, console glows, viewscreen back-glow).

**Original mechanism:** `MissionLib.py:1464` creates a single bright
ambient light: `pSet.CreateAmbientLight(1.0, 1.0, 1.0, 19.0,
"ambientlight1")`. This is a per-set light source attached to the
bridge set. Inspection of NIFs likely reveals additional point/spot
lights baked into the geometry's NiLight blocks.

**What needs implementation:**

- Point/spot light support in the renderer (we have ambient +
  directional today — see
  [docs/superpowers/specs/2026-05-10-bc-light-data-design.md](2026-05-10-bc-light-data-design.md)).
- Light extraction from the bridge NIF (similar to how ship NIFs'
  lighting metadata is extracted).
- Material emissive handling for console panels.

### D6. Click-to-station / interactive consoles

**Goal:** Click on a crew member or station to open a context menu
(orders, dialog, status display).

**Original mechanism:** `BridgeHandlers.py:555-620` uses ray-casting
from the cursor through the bridge camera into the bridge set's
geometry. Hit objects are matched to crew or stations, which open
the corresponding `*MenuHandlers.py` menu
(`HelmMenuHandlers`, `TacticalMenuHandlers`, `XOMenuHandlers`,
`ScienceMenuHandlers`, `EngineerMenuHandlers`,
`PicardMenuHandlers`, `SaalekMenuHandlers`, `DataMenuHandlers`).

**What needs implementation:**

- Cursor needs to be unlocked when in bridge mode for clicking — but
  we just locked it for mouse-look. Resolution likely a modifier:
  hold a key (e.g. tab) to unlock cursor temporarily. Original BC
  used a similar tab-to-cursor-mode UI.
- Ray-cast against bridge geometry (we don't have one yet for the
  renderer's instance list; ship-targeting in space uses a different
  path).
- Menu UI (substantial — would re-use the existing UiPanel /
  Collapsible components plus new menu data driven by the
  `*MenuHandlers.py` modules).

### D7. Bridge ambient audio

**Goal:** Loop the bridge ambient hum (engine room thrum, console
beeps) while bridge view is active.

**Original mechanism:** `LoadBridge.py:349-380` loads bridge ambient
sound at startup, plays it continuously while `IsBridgeVisible()`.

**What needs implementation:**

- Audio system (we don't have one yet — Phase 2 deliverable per
  CLAUDE.md: "OpenAL audio").
- Sound asset loading from `game/data/Sounds/` or wherever bridge
  ambient lives.

### D8. Smooth bridge ↔ exterior transition

**Goal:** Animate the camera between exterior and bridge views
(currently a hard cut on space-press).

**Original mechanism:** Not researched in detail. Likely a short
camera-blend animation when entering/exiting tactical mode.

**What needs implementation:**

- Camera-pose interpolation over ~0.5s.
- Brief disable of input while transitioning (so you can't toggle
  back-and-forth mid-blend).
- A renderer concept of "current displayed pose" vs "target pose"
  with easing.

### D9. Mouse-look in exterior mode

**Goal:** Optional mouse-look in third-person exterior view, in
addition to the existing arrow-key orbit.

**Original mechanism:** BC used arrow keys for tactical orbit; mouse
controlled the cursor for clicking on space objects. This is more of a
modernization than a faithfulness item.

**What needs implementation:**

- Reuse `consume_mouse_delta` and route into `_CameraControl.apply()`
  instead of `_BridgeCamera.apply()`.
- Sensitivity tuning differs between first-person (bridge) and
  third-person (orbit) — separate constants.

### D10. Bridge geometry / camera pose verification

**Goal:** Confirm the MissionLib-pinned DBridge camera pose is
correct in our renderer and that the bridge geometry orientation
matches expectations.

The hardcoded values come from
[MissionLib.py:1475-1483](../../../sdk/Build/scripts/MissionLib.py#L1475-L1483)
in the original engine's coordinate system. Since the Phase 1
renderer has been calibrated to match BC's coordinates for ship
poses (row-vector matrices, Y-forward, Z-up — see
[engine/host_loop.py](../../../engine/host_loop.py)'s `_extract_ypr`
docstring), the bridge pose should land approximately right. But the
axis-angle rotation `(-1.55, 0, 0, 1)` parses as "angle -1.55 around
axis (0, 0, 1)" or "axis (-1.55, 0, 0) with magnitude 1" depending
on the convention — the original engine's convention isn't documented
here. The PoC implementation iterates visually; if the camera ends up
upside-down or mis-pitched, swap conventions and re-test.

---

## Provenance of design decisions

For future readers: the design decisions in this spec were driven by
explicit user choices during brainstorming on 2026-05-11:

1. **Two-pass renderer with depth clear** (vs. far-park hack vs.
   per-instance visibility toggle). Chosen because it pays forward to
   the eventual viewscreen RTT.
2. **Eager bridge load at startup** (vs. lazy-on-first-press vs.
   per-mission). Chosen for simplicity and to avoid first-press
   loading hitch.
3. **Mouse-look** (vs. fixed camera vs. arrow-key head-look). Chosen
   for the most BC-faithful interactivity, accepting the cost of
   mouse-delta + cursor-lock binding work.
4. **Skip the viewscreen sub-NIF** (vs. load it as static black
   geometry). Chosen for cleaner scope, accepting the temporary
   visual hole in the front wall.

The two-pass + RTT-forward path was the most consequential decision;
everything else is detail.
