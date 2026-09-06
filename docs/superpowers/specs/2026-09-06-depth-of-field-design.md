# Targeted Depth of Field — Design

**Date:** 2026-09-06
**Status:** approved, not yet implemented
**Branch:** `feat/depth-of-field`

## Goal

Give the exterior space view a real camera lens: a **deep focus by default**,
which racks onto a subject when one is selected and releases when it is gone.
DOF here is a *directorial signal*, not a blanket filter.

Mark's framing, which drove every decision below:

> We could use deep focus by default and then enable a focus on targets when
> they're selected. Torpedo camera would really benefit from this too. We don't
> want to get over blurred though!

That framing is load-bearing. An always-on defocus would fight the game's
readability; an effect that exists *only* when something has been deliberately
focused on sidesteps the over-blur risk by construction. **Do not "simplify"
this into an always-on DOF.**

## Decisions taken

Four decisions were made explicitly and are not open for re-litigation without
a new conversation:

| Decision | Choice | Why |
|---|---|---|
| Focus subject in chase cam | **True rack focus** — the target is sharp and the player's own hull softens as a foreground element | The most cinematic reading, and closest to the VFX reference frames that started this work. The alternative (clamping near-blur onset so the player ship never softens) was considered and rejected. |
| Pipeline slot | **HDR, before the tonemap** | In space the frame is bright point highlights against black. Post-tonemap those are already clipped, so defocusing them yields dull grey smudges; in HDR they stay bright and spread into real bokeh discs, then bloom. Also the physically correct order — lens defocus happens before the sensor. |
| Far field | **Ceiling on far blur; starfield exempt** | With rack focus everything past the subject defocuses, and in torpedo cam the focus sits ~4 GU out, making the *entire* world far-field. A ceiling keeps distant ships readable; the sky is a painted backdrop and mushing it costs readability for nothing. |
| Tuning | **Every look-affecting number lives in Python, plus live dev keybindings** | Mark's explicit requirement. See [Tuning ergonomics](#tuning-ergonomics). |

## Architecture

### Pipeline placement

DOF becomes an HDR pass in the one gap in the frame where the full-precision
image and the depth buffer are both still alive — after every scene pass, before
bloom:

```
space.geometry ─┐
space.vfx       ├─► g_hdr_target ─► [ DOF ] ─► g_dof_target ─► bloom ─► resolve/tonemap
hologram        │                      ▲                                     │
bridge          │            reads colour + depth                            ▼
nfprobe        ─┘                                            SMAA ─► mblur ─► filmic
                                                                              │
                                                             letterbox ─► CEF composite
```

Insertion point is `native/src/host/host_bindings.cc`, between the non-finite
probe block (ends ~:1250) and the bloom block (`DAUNTLESS_FRAME_SCOPE("bloom")`,
:1293-1296). Deliberately **after** the non-finite probe, so that probe keeps
sampling the raw scene exactly as it does today.

When the pass runs, `bloom` and `resolve` source `g_dof_target->color_texture()`
instead of `g_hdr_target->color_texture()`. When it does not, they read
`g_hdr_target` exactly as today — **a byte-identical off-path**, the same
discipline MSAA and the directional ambient gradient follow.

### Why depth is already available

- `HdrTarget::depth_texture()` is a real sampleable `GL_TEXTURE_2D` with
  internal format `GL_DEPTH_COMPONENT24` (`hdr_target.cc:33-34`), already
  sampled by `nebula_volumetric_pass.cc` with `u_near`/`u_far` taken straight
  off the camera (`:161-162`).
- With MSAA on, `HdrMsaaTarget::resolve_to()` blits
  `GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT` (`hdr_msaa_target.cc:66-69`), so
  `g_hdr_target`'s depth is populated and single-sampled either way. **DOF needs
  no MSAA-specific path.**

### New files

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/dof.h` | Pure CoC math, no GL. Header-only, gtest-covered — the `lighting.h` pattern. |
| `native/src/renderer/include/renderer/dof_pass.h` | `DofPass` class declaration. Mirrors `filmic_pass.h`. |
| `native/src/renderer/dof_pass.cc` | Fullscreen-triangle pass. Reuses `resolve.vert`, as `FilmicPass` does. |
| `native/src/renderer/shaders/dof.frag` | The gather. Holds **no look-affecting constants** — every one is a uniform. |
| `native/tests/renderer/dof_test.cc` | gtest over `dof.h` + a `FrameTest` over the pass. |
| `engine/cameras/dof.py` | Tuning constants **and** `FocusSolver`. One file to open when tuning. |
| `tests/unit/test_dof_focus.py` | pytest over the solver. |

Modified: `host_bindings.cc` (pass wiring + bindings), `engine/host_loop.py`
(one push next to `r.set_camera`), `engine/appc/camera_modes.py` (a
`focus_subject()` hook), `engine/settings_store.py` and
`engine/ui/configuration_panel.py` (settings), `engine/dev_keybindings.py`
(live tuning), `engine/host_io.py` (façade), `native/CMakeLists.txt`.

## The lens model

### Linearizing depth

Standard OpenGL perspective, `glDepthRange` left at its default so
`gl_FragCoord.z` and the sampled texel are both in `[0,1]`:

```glsl
float ndc = 2.0 * d - 1.0;
float z   = (2.0 * u_near * u_far) / (u_far + u_near - ndc * (u_far - u_near));
```

The main exterior camera is `near = 1.0`, `far = 5000.0`
(`host_loop.py:8796-8798`). `z` is therefore a view distance in **game units**;
per the project convention it is named `z_gu` in any Python mirror and never
`z_m`.

### Circle of confusion

A real thin lens, expressed with one division:

```glsl
float dd  = 1.0 - u_focus_gu / z;      // 0 at focus, →-∞ toward camera, →+1 at infinity
float coc = (dd < 0.0) ? max(dd * u_near_strength, -1.0)
                       : min(dd * u_far_strength,  u_far_ceiling);
```

This single form is what makes the effect self-scaling, and it is the reason the
design carries no near/far *range* constants to keep in sync:

- Focus on a 4 GU torpedo gives a shallow band; focus on a ship 200 GU out gives
  a deep one. Both fall out of the same expression.
- The near field grows without bound and clamps hard at `-1` — which is exactly
  what makes a rack focus read.
- The far field saturates naturally at `u_far_strength` as `z → ∞`, and
  `u_far_ceiling` caps it below that.

`coc` is signed only so the two sides can be tuned independently; the blur
radius uses `abs(coc)`.

### Starfield exemption

`backdrop_pass.cc` draws the sky with `glDepthMask(GL_FALSE)` (`:98`, `:210`),
so **sky pixels never write depth** and hold the clear value.

Exempt them on the *linearized* distance, not on the raw depth value:

```glsl
if (z >= u_far * 0.98) coc = 0.0;
```

Nothing calls `glClearDepth` anywhere in the tree, so the clear value is GL's
default `1.0` — but testing `z` rather than `d >= 0.999999` keeps the exemption
correct even if someone changes that default later. At `far = 5000` the
threshold is 4900 GU (857 km); no scene geometry is ever that distant.

## Focus control

Pure Python, unit-testable without a GL context, pushed in one call next to the
existing `r.set_camera` at `host_loop.py:8796`.

### Subject selection

Priority order, first match wins:

1. **The active camera mode names its own subject.** A new `focus_subject()`
   hook on `CameraMode` (`engine/appc/camera_modes.py:70`) returning `None` by
   default, overridden by `TorpCameraMode` (`:767`) to return the torpedo it is
   currently riding. `TorpCameraMode` already latches one torpedo and already
   tracks it for placement, so this hook returns state it holds anyway.
2. **The player's selected target** — `player.GetTarget()`.
3. **Nothing** → no subject.

The hook exists so cutscene and cinematic modes can adopt it later without
another special case. `TorpCameraMode` is the only override in V1.

### Deep focus is free, not a large number

With no subject the `blend` scalar is 0, and **the host skips the DOF pass
entirely** — `bloom` and `resolve` read `g_hdr_target` directly. Deep focus by
default costs nothing and is byte-identical to today's frame. This is why "deep
focus" is not implemented as a very large `focus_gu`.

### The rack is eased in dioptres

Smooth `1 / focus_gu`, not `focus_gu`, with a time constant of
`RACK_TAU_S = 0.35`:

```python
inv = _ease(inv_current, 1.0 / focus_target_gu, dt, RACK_TAU_S)
focus_gu = 1.0 / inv
```

This is how a real focus pull behaves — the lens barrel moves in dioptres — and
it stops the pull from crawling when the subject is far away. Easing linear
distance would make a rack from 20 GU to 400 GU take visibly longer than the
reverse.

`blend` ramps `0 → 1` over `BLEND_TAU_S` when a subject appears and `1 → 0` when
it is lost, so losing a target releases focus rather than snapping to sharp.

## The blur kernel

Single-pass, full resolution, 24-tap golden-angle spiral at radius
`abs(coc) * u_max_radius_px`.

Full-res rather than the customary half-res prepass because **the frame is
CPU-bound** — `sim` runs ~70 ms against `r.frame` ~15-24 ms, so GPU bandwidth is
the cheap resource. This is the same argument that justified MSAA, and it also
avoids half-res upsampling artifacts on an effect whose whole point is subtlety.
If a live pass shows it is too slow, adding a half-res path is a contained
follow-up.

### Scatter-as-gather weighting

The one detail that separates a good DOF from a bad one. A tap contributes only
if **its own** CoC reaches this pixel:

```glsl
float w = clamp(tap_radius_px - dist_to_tap_px + 1.0, 0.0, 1.0);
```

Without it, sharp foreground objects bleed onto in-focus background, and
in-focus objects have their edges eaten by blurred neighbours. Both are the
classic "cheap DOF" tells. **This weighting is not an optimisation and must not
be removed as one.**

## Tuning ergonomics

Mark's explicit requirement:

> We are probably going to want to tweak the strength up and down during live
> testing to get the right balance, so ensure that value is easy to tweak in
> code.

Three rules, in priority order:

**1. Every look-affecting number lives in `engine/cameras/dof.py`, at module
level.** Editing them needs **no rebuild** — Python only, relaunch and look.
This is a deliberate departure from the directional gradient, whose
`kTunedDefault` sits in `frame.cc` and cost a full C++ rebuild per tuning round.

```python
# Lens shape — pushed to the shader as uniforms.
NEAR_STRENGTH    = 1.0    # foreground defocus gain
FAR_STRENGTH     = 1.0    # background defocus gain (before the ceiling)
FAR_CEILING      = 0.4    # hard cap on far-field CoC — the anti-mush knob
MAX_RADIUS_FRAC  = 0.008  # max blur radius as a fraction of screen height

# Focus behaviour — consumed by FocusSolver, never reaches the shader.
RACK_TAU_S       = 0.35   # focus-pull time constant
BLEND_TAU_S      = 0.25   # engage/release ramp
```

The two groups differ in where they are consumed, and the split matters: the
first four are lens *shape* and cross into GLSL; the last two are focus
*behaviour* and live entirely in the solver.

**2. The C++ and GLSL sides hold no look-affecting constants at all.** The four
lens values, plus the two the solver computes, arrive through one binding pushed
each frame:

```python
r.set_dof_params(focus_gu, blend,
                 near_strength, far_strength, far_ceiling, max_radius_frac)
```

(The pybind binding itself is `dof_set_params`; `engine/renderer.py` wraps it as
`set_dof_params`, matching how `msaa_set_samples` is exposed as
`set_msaa_samples`.)

`max_radius_frac` is converted to pixels **host-side** (`frac * fh`) so the
shader never needs the framebuffer size. `blend` scales the final blur radius,
and the host **skips the pass entirely when `blend <= 0.0`** — which is what
makes deep focus free rather than merely cheap.

There is no C++ default that can drift out of step with the Python one, and
therefore no second place to look when a number seems wrong. The only C++
constant is `kTapCount = 24`, which is kernel structure, not look.

**3. Under `--developer`, two key *pairs* nudge the live lens** and print all
four lens values to stderr on every press:

| Keys | Knob | Step | Range |
|---|---|---|---|
| `,` / `.` | `max_radius_frac` — overall blur magnitude | 0.002 | `[0.0, 0.04]` |
| `;` / `'` | `far_ceiling` — how much the background may mush | 0.05 | `[0.0, 1.0]` |

**Not the strengths, and that is the point.** The far field is *ceiling*-bound,
not strength-bound: with `FAR_CEILING = 0.4`, a background object at 10× the
focus distance has `dd = 0.9`, so `far_strength` must fall below **0.44** before
the ceiling stops clipping it — six presses of a 0.1 strength nudge with *zero
visible change*, and no upward press could ever affect the distant background at
all. On the near side anything at `z ≤ focus/2` is already clamped at the hard
`-1`, so raising `near_strength` above 1.0 only widens a narrow band. Strength
keys would have looked broken. `nudge_strength()` still exists for a console,
but no key is bound to it.

Step sizes are chosen to be *visible per press*: at 1080p the default
`max_radius_frac = 0.008` is an 8.6 px radius, so a 0.002 step is ~2.2 px — a
25% change, with four presses doubling it or taking it to zero.

**All four values print on every press**, so one stderr line carries the whole
state to paste back into `dof.py`; printing only the knob that moved would make
the developer reconstruct the rest from memory across a session of presses.

The module-level names above are **defaults**, not the live values. `FocusSolver`
seeds mutable instance state from them at construction, and the dev keys nudge
that instance state — so a nudge is per-session and never writes back to the
module. A mission swap resets the *rack* (focus distance and blend) but
deliberately **keeps** the nudged lens values: they are session tuning, not
mission state.

All four keys are free: they appear in `engine/input_map.py` only as
display-name table entries and are bound to no action in `ACTIONS`. Registered
through `dev_mode.register_dev_keybinding(key, handler, description)`
(`engine/dev_mode.py:104`), so they also appear in the pause menu's developer
section, and they are inert without `--developer`.

⚠️ Every one of the four must also be **exported by `_dauntless_host.keys`**
(`host_bindings.cc`). `register_for_frame()` reads them unguarded, every tick,
inside a `try` with no `except` — an unexported constant terminates the process
on the first developer-mode tick. `KEY_COMMA` and `KEY_PERIOD` shipped exactly
that way; `tests/unit/test_host_key_manifest.py` now guards the whole submodule.

This is the point of the whole section: Mark tunes in-flight in one session,
reads the number he liked off stderr, and it becomes the Python default — rather
than three rebuild-and-relaunch rounds.

Defaults above are deliberately **conservative**. Expect to calibrate up and
then back down, the way the ambient gradient went 0.6 → 1.0 → 0.8.

## Settings integration

Add `dof` as a **fifth applier under the existing `camera_realism` master**,
which already owns HDR, the filmic grade, motion blur and modern lens flares
(`settings_store.py:269-277`, `configuration_panel.py:73-74`). DOF is squarely
that family.

Consequences, all of them intended:
- **No new player-facing row.** The master already reads "Camera Realism".
- **No schema migration.** `SCHEMA_VERSION` stays at 2. The master's persisted
  key is unchanged; only its fan-out grows.
- Default on, with the master.

## Scoping

DOF runs **only on the exterior space view**, gated on the existing `exterior`
flag (`host_bindings.cc:1304`, `!viewer_mode && !bridge_active`) — the same gate
filmic and motion blur use. It is therefore inert on:

- the bridge interior and the comm viewscreen render-to-texture
- the hologram / Ship Property Viewer path
- the star map

DOF is a **post-process over the resolved scene**, not a hull-shading term.
The rule that any new hull-shading uniform must be pushed from *both* `frame.cc`
and `cloak_pass.cc` does **not** apply here, and no change to either file is
needed. Noted explicitly so a reviewer does not flag its absence.

## Known limitations

Accepted for V1, stated so they are not later mistaken for bugs:

1. **Additive transparents inherit the background's CoC.** Beams, torpedo
   glows and dust do not write depth, so a phaser crossing from your hull to a
   distant target is blurred by whatever is behind it, not by its own distance.
   This is the standard post-DOF compromise; fixing it needs a separate
   transparent-depth pass.
2. **Camera-anchored dust stays sharp**, for the same reason — its pixels carry
   the sky's depth. Arguably correct for a camera-anchored effect.
3. **No bokeh shape control.** The kernel is a uniform disc; no aperture blades,
   no cat's-eye vignetting at frame edges.
4. **No focus breathing.** Real lenses shift FOV slightly during a rack. Out of
   scope.

## Testing

Three layers, matching how the renderer is tested elsewhere:

1. **gtest over `dof.h`** — `coc_from_depth()` as a pure function. Pins the
   curve at focus (`coc == 0`), the near clamp (`-1`), far saturation against
   `far_ceiling`, and the sky exemption. The `lighting_test.cc` pattern: pinned
   values document a deliberate choice, so changing the curve means changing the
   test in the same commit.
2. **pytest over `FocusSolver`** — subject priority (torpedo cam beats target
   beats nothing), dioptre easing, and the `blend` ramp down on target loss. No
   GL context needed.
3. **`FrameTest` over `DofPass`** — that the off-path is byte-identical (bloom
   reads `g_hdr_target` when no subject is focused), and that a synthetic depth
   ramp produces the expected CoC field.

Gate with `scripts/check_tests.sh`, which builds C++ and runs both suites
against `tests/known_failures.txt`. Shader edits need `cmake -B build -S .`
before the build, and shader compile errors are **runtime**, not build-time — a
clean build proves nothing about `dof.frag`.

## Non-goals

- Applying DOF to the bridge interior or the viewscreen.
- A physical f-stop / focal-length lens model. The artistic parameterisation
  above is deliberate: real focal lengths against game units (1 GU = 175 m)
  produce numbers nobody can reason about.
- Autofocus on whatever is at screen centre. Focus follows the *named subject*,
  which is what makes it a directorial signal.
- Half-res or tile-based optimisation, unless a live pass shows it is needed.
