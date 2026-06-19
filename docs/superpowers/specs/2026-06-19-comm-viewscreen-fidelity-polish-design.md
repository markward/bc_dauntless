# Comm-viewscreen fidelity polish — static overlay + ViewOn/Off transition

**Date:** 2026-06-19
**Status:** Design — approved (user accepted in advance), proceeding to plan + execution

## 1. Goal

Finish the deferred fidelity items from the comm-set viewscreen feature
(`docs/superpowers/specs/2026-06-18-comm-set-viewscreen-rendering-design.md`,
"Out of scope"). Hails should render with the authentic analog static/"snow"
overlay scaled by the SDK's `fMinStatic`/`fMaxStatic`, and a short ViewOn/ViewOff
brightness-fade transition — **driven entirely by the SDK's
`MissionLib.ViewscreenOn`/`ViewscreenOff`**.

### Guiding principle

SDK scripts drive everything (memory `feedback_sdk_drives_everything`). The
per-mission varying behaviour (static on/off, min, max; when the feed switches)
flows from the SDK calls. The engine only realizes what those calls request.

## 2. Scope decision (keep / cut / defer)

Investigated all three deferred groups against actual SDK usage:

- **KEEP — Static/"snow" overlay.** Real and widely used.
  `MissionLib.ViewscreenOn(pAction, pcLookAtSet, pcName, fMinStatic, fMaxStatic,
  bDropAndLook, idActionToComplete)` (MissionLib.py:1213) calls, only when
  `fMaxStatic > 0` (MissionLib.py:1274–1278):
  ```python
  pViewScreen.SetStaticTextureIconGroup("View Screen Static")
  pViewScreen.SetStaticIsOn(1)
  pViewScreen.SetStaticVariation(fMinStatic, fMaxStatic)
  ```
  `ViewscreenOff` (MissionLib.py:1318) clears it: `if pViewScreen.IsStaticOn():
  pViewScreen.SetStaticIsOn(0)` (MissionLib.py:1344–1345). Campaign usage
  (file:line → set/char → min,max): E1M2:3998 MiscEng/Soams **0.8,1**;
  E2M0:2203 EBridgeSet/Soto 0.3,0.6; E2M0:2524 0.7,1; E2M6:1525 FedOutpostSet/
  Picard 0.7,1; E2M6:2613 0.2,0.5; E4M6:2878/2882 C/Kessok bridges 0.5,0.75;
  E5M4:1915 DataSet/Data **5,5** (clamps to full); E6M2:2698 0.5,1; E6M5:1853
  0.2,0.5; E6M5:2561 0,0.3; E7M6:2093 0.25,0.5. Most ordinary hails omit static
  (0,0). Currently `SetStatic*`/`IsStaticOn` no-op via `_LoudStub.__getattr__`
  on `ViewScreenObject` (engine/appc/bridge_set.py).

- **KEEP (lightweight) — ViewOn/ViewOff transition.** `ViewscreenOn`/`Off`
  create `App.TGSoundAction_Create("ViewOn")`/`("ViewOff")` (MissionLib.py:1290,
  1355); the sounds already fire (real-duration completion landed in the
  action-timing work). Note `ViewscreenOff` keeps `SetIsOn(1)` and switches the
  remote cam back to the forward view — this is a feed tune-in/out, not a literal
  power-off. We add a **brightness fade** (user's chosen look) accompanying both.

- **CUT — Hail-face variations.** No SDK surface exists. `SetStaticVariation`
  (static intensity) is the *only* "variation" mechanism; there is no
  per-character face/angle/framing system anywhere in the 1228 SDK files.
  Nothing to build.

- **DEFER — Viewscreen menus.** Real surface exists
  (`pViewscreen.SetMenu`/`MenuUp`/`MenuDown`/`IsMenuUp`; used by E4M4:143 for the
  XO menu and EngineerCharacterHandlers.py:1286 for the engineer desk), but it is
  a separate menu-rendered-onto-the-viewscreen-mesh subsystem, orthogonal to hail
  fidelity and not exercised by the hail path. Its own future project. These
  methods keep falling through `_LoudStub` (no crash).

## 3. Current state (from investigation)

- `engine/appc/bridge_set.py` — `ViewScreenObject(_LoudStub)` holds real
  `_remote_cam`/`_is_on`; `SetStaticTextureIconGroup`/`SetStaticIsOn`/
  `SetStaticVariation`/`IsStaticOn` currently no-op via `_LoudStub.__getattr__`.
  `BridgeSet.GetViewScreen()` returns the object.
- `engine/host_loop.py` ~3614–3646 (Step 5c) — drives the viewscreen RTT:
  `_viewscreen_feed_on(vs)`; `_active_comm_feed(controller)` →
  `set_viewscreen_comm_source(set_id, eye, target, up, fov, near, far)` or
  `clear_viewscreen_comm_source()`.
- `engine/renderer.py` ~346–368 — thin wrappers: `set_viewscreen_enabled`,
  `set_viewscreen_comm_source`, `clear_viewscreen_comm_source`,
  `set_viewscreen_model`.
- `native/src/host/host_bindings.cc` — `frame()` viewscreen-RTT block
  (~435–460): renders comm set (`Pass::Comm`) or forward space into
  `g_viewscreen_hdr` (640×360), then `g_bridge_pass->set_viewscreen_texture(...)`.
  Bindings ~960–982. `struct CommSource g_comm_source`.
- `native/src/renderer/bridge_pass.cc` — `draw_mesh` binds the RTT as a
  base-color override (`base_override`) for the viewscreen model handle and sets
  `u_emissive=(1,1,1)`; `u_flip_v` handles the FBO bottom-left vs NIF top-down
  UVs. NiFlipController animation via `assets::compute_flip_frame_index`
  (bridge_pass.cc ~115; `assets::TextureAnimation` in model.h).
- Shaders: `native/src/renderer/shaders/bridge.{vert,frag}` (the `u_flip_v`,
  `u_emissive` viewscreen-override path).
- Tests: `native/tests/renderer/comm_pass_test.cc` (offscreen-readback pattern),
  `bloom_pass_test.cc::readback_texture`.

## 4. Design

### 4.1 Python — `ViewScreenObject` records real static state

Add explicit methods (replacing the `_LoudStub` no-ops for these four only):

```python
self._static_icon_group = None
self._static_on = 0
self._static_min = 0.0
self._static_max = 0.0

def SetStaticTextureIconGroup(self, name): self._static_icon_group = name
def SetStaticIsOn(self, on):               self._static_on = on
def IsStaticOn(self):                       return self._static_on
def SetStaticVariation(self, fmin, fmax):
    self._static_min = float(fmin); self._static_max = float(fmax)
```

Menu methods (`SetMenu`, etc.) remain `_LoudStub` fall-through (deferred).

### 4.2 Python — icon-group → texture paths (the one documented constant)

Our icon-manager (`g_kIconManager`) isn't built, so the SDK's
`"View Screen Static"` → `EffectTextures.LoadStatic` →
`data/Textures/Effects/Noise{1,2,3}.tga` mapping is resolved by a small Python
helper keyed on the icon-group name the SDK passes, with a comment citing
`sdk/Build/scripts/Tactical/EffectTextures.py:262`. Unknown group → empty list
(static stays off). This keeps native asset-path-agnostic (paths flow
Python→native, like the rest of the pipeline); only this fixed asset list is a
constant, and it lives in Python next to its SDK citation so it can be upgraded
if the icon manager is ever built.

### 4.3 Python — host_loop Step 5c plumbing

In the existing Step 5c block, after the comm/forward feed decision, read the
viewscreen object's static state:

- If `_static_on` and `_static_max > 0`: per frame compute
  `intensity = clamp(uniform_random(min, max), 0, 1)` and call
  `r.set_viewscreen_static_source(paths)` (when the group/paths change) +
  `r.set_viewscreen_static(True, intensity)`.
- Else `r.set_viewscreen_static(False, 0.0)`.

Putting the random in Python keeps native deterministic and makes the
min/max→intensity mapping unit-testable.

**Brightness-fade transition.** host_loop tracks a "feed signature" — one of
`off`, `forward`, `comm:<set_id>`. On any change of the signature, reset a ramp
timer; each frame compute `brightness = clamp(elapsed / DURATION, 0, 1)` (≈0.3s)
and call `r.set_viewscreen_brightness(brightness)`. This fade-in fires on both
`ViewscreenOn` (→ comm) and `ViewscreenOff` (→ forward), accompanying both
sounds. Timing is `frame_dt`-driven and fully testable in Python.

### 4.4 Native — static composite pass

After the feed renders into `g_viewscreen_hdr`, if static is on, draw one
fullscreen quad over that HDR target:

- Fragment samples the current noise texture; outputs `vec4(noise.rgb,
  intensity)`. GL blend `SRC_ALPHA / ONE_MINUS_SRC_ALPHA` →
  `out = mix(feed, noise, intensity)`. No shader read of the feed (framebuffer
  blend does the mix). At `intensity→1` (E5M4 5,5 clamps here) the picture is
  pure snow; at 0.2 light flicker.
- Noise frame: native cycles the 3 cached noise textures by wall time (reuse the
  existing flip-frame helper).
- **V-flip is a non-issue**: noise is isotropic random, so orientation doesn't
  matter, and the existing single bridge-mesh-sample `u_flip_v` still corrects
  the underlying feed. No double-flip.

New bindings (mirror `set_viewscreen_comm_source`):
- `set_viewscreen_static_source(paths: list[str])` — load + cache noise textures
  (idempotent by path; rare call).
- `set_viewscreen_static(on: bool, intensity: float)` — per-frame state.
- `set_viewscreen_brightness(b: float)` — per-frame viewscreen content multiplier.

New shader files for the composite pass: `native/src/renderer/shaders/
viewscreen_static.{vert,frag}` (fullscreen quad + noise sample).

### 4.5 Native — brightness multiplier

`bridge.frag` gains `uniform float u_viewscreen_brightness` applied **only on the
viewscreen-override path** (`base_override != 0`): multiply the final viewscreen
sample by it. Default 1.0 so the non-viewscreen bridge geometry is byte-identical.
`bridge_pass` exposes a setter the host calls each frame.

### 4.6 Build / rebuild rules

- `bridge.frag` edit + new `viewscreen_static.{vert,frag}` → cmake **reconfigure**
  (`cmake -B build -S .`) before `cmake --build build -j` (memory
  `feedback_shader_rebuild`).
- `host_bindings.cc` edits → full `dauntless` rebuild (memory
  `feedback_host_bindings_build_target`).
- One build tree: `build/dauntless`. Never build from inside `native/`.

## 5. Components & boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `ViewScreenObject` static state | record icon group / on / min / max | — |
| static icon-group→paths helper | resolve `"View Screen Static"` → 3 tga paths (cites SDK) | — |
| host_loop static plumbing | per-frame intensity (random in [min,max]) → renderer | ViewScreenObject, renderer |
| host_loop brightness ramp | feed-signature change → 0→1 fade | feed state, frame_dt |
| renderer.py wrappers | `set_viewscreen_static_source` / `set_viewscreen_static` / `set_viewscreen_brightness` | `_h` host module |
| native static composite pass | blend noise over the viewscreen HDR at intensity | g_viewscreen_hdr, noise tex |
| native brightness uniform | scale viewscreen sample in bridge.frag | bridge_pass |

## 6. Testing

**Python (TDD, `scripts/run_tests.sh`):**
- `ViewScreenObject` records icon group / on / min / max; menu methods still
  no-op.
- icon-group helper returns the 3 noise paths for `"View Screen Static"`, empty
  for unknown.
- `min/max → intensity ∈ [min,max]` and clamped to [0,1] (incl. 5,5 → 1.0).
- brightness ramp: 0→1 over duration; resets to 0 on feed-signature change;
  stays 1 once settled.
- host_loop Step 5c calls the right renderer methods for static-on / static-off /
  feed-change (with a fake renderer).

**Native (renderer_tests, gtest — offscreen readback, mirror `comm_pass_test`):**
- static composite at fixed `intensity` (min==max) over a known feed colour →
  assert blended pixel ≈ `mix(feed, noise, intensity)`.
- `intensity = 0` (or static off) → feed byte-identical (no composite).
- `u_viewscreen_brightness` scales the viewscreen sample; default 1.0 leaves
  non-viewscreen geometry unchanged.

**Visual (user drives the GUI):**
- E1M2: Soams hail with (0.8,1) heavy snow vs the (0,0) clean hail.
- E1M1: Liu clean baseline + ViewOn/Off brightness fades.
- Compare to BC reference footage. Dev-gated logging + steps provided; no
  synthetic desktop interaction.

## 7. Risks

- **Read+write same FBO.** The composite must draw *into* `g_viewscreen_hdr`
  using framebuffer blending (no in-shader sample of the attachment being
  written). Mitigated by the alpha-blend `mix` design (§4.4).
- **Double V-flip.** Avoided because noise is orientation-agnostic; do **not**
  add a second flip.
- **Shader rebuild gotcha.** New/edited shaders need a cmake reconfigure (§4.6).
- **Production path identical when static off / brightness 1.0.** Verified by the
  byte-identical native test and the Python static-off path.
