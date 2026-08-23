# Bridge Lighting Design

> **Status:** design only, not yet implemented.
> **Authored:** 2026-06-20. **Substantially revised:** 2026-08-23.
> **Scope:** replaces BC's baked-lightmap bridge interior rendering with an
> emissive-driven pipeline — surfaces are the light sources, a spherical-harmonic
> irradiance probe carries what is off-screen, LTC area lights carry the two big
> emitters, and screen-space GI is an optional near-field refinement.
>
> **The 2026-08-23 revision changed the architecture, not the goal.** The original
> design answered "where are the lights?" with an authored JSON light list — 16
> point/tube/bezier primitives per bridge, anchored to NIF block indices, placed
> with a bespoke dev-mode editor. This version answers it with "the emissive
> surfaces already in the geometry." Most of the placement machinery collapses;
> the texture-authoring machinery is promoted from a supporting role to the
> primary one. §17 records exactly what was dropped and why.

## 1. Motivation

*(Unchanged from 2026-06-20 — the revision did not weaken any of this.)*

The current bridge pass renders interior geometry via:

1. NIF-baked vertex colors,
2. Per-material `emissive` (light fixtures set to (1,1,1) so they stay
   bright under any ambient),
3. UV1 lightmap textures from BC's `_lm.tga` / `-lm.tga` / `_LM.tga`
   convention, multiplied over the base.

That works but locks us out of every visual upgrade we actually care
about:

| Limitation | Consequence |
|---|---|
| Lightmaps are tiny (BC authored them at low resolution) | Mucky, grainy quality across all bridge surfaces. |
| Static baked geometry | No bridge-character interaction with lighting; characters don't shadow surfaces, surfaces don't pick up bounced light from characters. |
| No reflection capture | Glossy LCARS panels and chair-arm specular highlights are impossible. |
| Pre-baked indirect | Damage VFX (sparks, electrical arcing, console fires) can't tint nearby surfaces. |
| Single ambient term | Alert-state color washes (red panels casting red bounce on the captain's chair) impossible. |

A fully baked replacement (high-res lightmaps via Blender/Cycles) was
considered and rejected because every limitation above survives the
upgrade — bake-it-once optimises for "static museum diorama," but our
bridge is a *living scene* (crew motion, combat damage, alert states,
glossy materials).

Note that three of those five rows — character bounce, VFX tinting, and
alert-state colour wash — are **indirect lighting** wants. The original
design deferred indirect entirely (old §15) and hoped direct lights would
approximate it. This revision addresses them directly.

## 2. Where we are starting from

The bridge fragment shader is 54 lines and its entire lighting model is:

```glsl
vec3 light = max(u_ambient, u_emissive);
vec3 col = base.rgb * lm * light * u_viewscreen_brightness;
```

No directional light, no point light, no specular, no per-pixel lighting of any
kind. `bridge.vert` declares `a_normal` at location 1 and **never uses it** — no
normal reaches the fragment stage at all. The bridge is base texture × BC's baked
lightmap × a constant.

This matters for sequencing (§13): the lightmap is currently the *only* source of
spatial variation. Remove it before something replaces it and the bridge becomes
`base × constant` — a flat texture-viewer, strictly worse than what ships today.

## 3. The constraint that shapes everything: GL 4.1

`window.cc` requests **4.1 core**, and every shader is `#version 330 core`. That
is not conservatism — macOS is permanently frozen at 4.1.

| Feature | Requires | Available to us |
|---|---|---|
| `glDrawBuffers` MRT | GL 2.0 | yes |
| Image load/store | GL 4.2 | **no** |
| Compute shaders | GL 4.3 | **no** |
| SSBO | GL 4.3 | **no** |

Every technique in this document is therefore specified as **fragment shaders and
CPU-side work only**. In particular, screen-space GI (§11) is a full-screen
fragment pass with ping-pong FBOs, not a compute dispatch, and the SH projection
(§8) runs on the CPU rather than as a GPU convolution.

There is also no MRT anywhere in the renderer today — `glDrawBuffers` and
`GL_COLOR_ATTACHMENT1` appear in zero files. A G-buffer is new construction. The
bridge is nonetheless the cheapest place in the codebase to build one: 54 + 19
lines of shader with no material complexity, against `opaque.frag`'s 740 lines of
decals, carve fields, glow regions and heat-glow.

## 4. Architecture

Four tiers, each doing what it is good at. The first two are the pipeline; the
last two are refinements with their own off-ramps.

| Tier | Mechanism | Supplies | Status |
|---|---|---|---|
| **1. Emissive surfaces** | Per-material emissive × per-texel `_emit.tga` mask | The light sources themselves | Required |
| **2. SH irradiance probe** | 9 RGB coefficients baked at the camera anchor | All indirect light, including off-screen | Required |
| **3. LTC area lights** | Analytic rectangles | Ceiling dome + viewscreen | Strongly wanted |
| **4. SSGI** | Screen-space fragment pass + temporal filter | Near-field contact detail | Optional |

The ordering is deliberate: **the probe is the robust component and SSGI is the
garnish.** Every awkward case in this design — hard cuts, camera translation,
emitters leaving frame, the 640×360 viewscreen path — is one the probe handles
and SSGI does not. If SSGI proves unaffordable when we finally have a profiler
(§12), tiers 1–3 still constitute a complete, shippable bridge lighting model.

### 4.1 Why emissive-first

BC bridges are lit by *visible fixtures*: ceiling panels, LCARS screens, cove
strips, console glow. The light sources are already in the geometry, already
positioned, already shaped, and already carry an artist's intent. Deriving light
from them means:

- **No placement authoring.** No JSON light list, no NIF block anchors, no
  bespoke editor. The geometry is the placement.
- **Nothing to keep in sync.** The old design's §16 q6 worried that *"if BC
  modders ever re-export the bridge NIFs, the indices shuffle and the JSON config
  breaks,"* and proposed a three-tier `anchor_block` / `anchor_name` /
  `anchor_path` fallback to mitigate it. An emit mask travels with the *texture*,
  which is stable across re-export. The problem stops existing rather than being
  mitigated.
- **Consistency by construction.** A fixture that looks bright *is* bright. There
  is no way for the visible glow and the cast light to disagree.

### 4.2 What emissive-first cannot do

It removes the artist's ability to place a light that is not a visible surface.
Every real lighting setup uses fill and cheat lights with no source — a talking
officer usually needs a fill that isn't coming off a wall panel.

So we do not reach zero authored lights. Expect **a handful of invisible point
lights per bridge**, hard-coded or in a short config. A handful — not seventeen
with a schema, an anchor-resolution system and an editor.

## 5. Textures: what already exists

Most of the authoring pipeline this design needs is **already shipped**, just not
consumed by the bridge path.

| Convention | Routes to | Mechanism | Consumed by |
|---|---|---|---|
| `<base>_specular.tga` | `StageSlot::Gloss` | sibling probe on disk | `opaque.frag` |
| `<base>_normal.tga` | `StageSlot::Bump` | sibling probe on disk | `opaque.frag` |
| `<base>_glow.tga` | `StageSlot::Base` **and** `Glow` | filename routing | `opaque.frag`, `cloak_pass` |
| `<base>_emit.tga` | `StageSlot::Emit` | **new** sibling probe (§6) | bridge |

`Material::StageSlot` is already `Base, Dark, Detail, Gloss, Glow, Bump,
Decal0-2`. `model_build.cc` already probes for `_specular` and `_normal` siblings
and registers them against the diffuse's link id; `material_build.cc` already
binds them. An artist drops the file next to the diffuse and it is picked up next
build — no JSON, no NIF edit, no engine change.

**The tangent problem is already solved.** `opaque.frag` notes that *"BC NIFs
carry no tangents and none are added, so the frame is rebuilt"* and reconstructs
a cotangent frame from screen-space derivatives in `perturb_normal()`, with
guards for zero-area UV triangles, malformed maps and NaN. Authoring normal maps
for the bridge needs **no tangent generation pass** — the usual reason "just
author normal maps" is expensive does not apply here.

So §14's phases for normal and specular support are mostly *porting* `opaque.frag`'s
shading into `bridge.frag`, not new systems.

### 5.1 Correction: `_glow` is not what we need

The 2026-06-20 text asserted that `_emit.tga` would use the *"same machinery as
the existing `_glow` and `_specular` sibling discovery."* That is wrong in two
ways, and both matter:

1. **There is no `_glow` sibling probe.** Only `sibling_specular_for_image` and
   `sibling_normal_for_image` exist. `_glow` is a *routing rule* applied to a
   texture the NIF already references (`filename_is_glow()`), not a probe for a
   file the NIF does not mention.
2. **`_glow` carries its mask in the diffuse's alpha channel.** It dual-binds the
   same texture to Base *and* Glow precisely because RGB is hull colour and alpha
   is the self-illumination mask. That is BC's AddLOD convention.

Bridge alpha is already spoken for by LCARS alpha-test (`u_alpha_test_threshold`,
and `floorlight.tga` already abuses alpha as a brightness mask — the collision
old §7.1 complains about). So `_glow` is the wrong primitive here regardless of
the machinery. `_emit.tga` must be a genuinely new sibling probe modelled on
`sibling_normal_filename`.

It is also worth knowing that the existing conventions are, in content terms,
entirely a ship feature:

| | Ships | Bases | SharedTextures | Misc | **Models/Sets** (bridges) |
|---|---|---|---|---|---|
| `_glow` textures | 162 | 30 | 84 | 21 | **0** |

Zero `_specular` and zero `_normal` under `Models/Sets` too. Every bridge texture
authored for this design is net-new content.

## 6. Emit-mask textures (`_emit.tga`)

*(Promoted from a supporting role in 2026-06-20 to the primary authoring surface.)*

### 6.1 Why

BC's bridge artists had three blunt instruments for "where does this surface emit
light":

1. Alpha channel of certain diffuse textures (`floorlight.tga` etc.) — couples
   emit mask to texture alpha, can't use alpha for actual transparency.
2. Per-material `emissive = (1,1,1)` — whole-mesh, no per-texel control.
3. `Red/Off GlowAlpha` NiNode grouping — whole-subtree toggle.

None of these handle "this DBridge panel has 3 inset bulbs and a black bezel."
Under this design that is not a refinement but the core requirement: the mask is
what separates a light source from unlit trim, and therefore what the entire
lighting solution is derived from.

### 6.2 Convention

For any diffuse texture `walllight.tga`, if a sibling file `walllight_emit.tga`
exists, it is auto-attached as a per-texel emissive mask. Greyscale 8-bit, same
resolution as the diffuse. Sample value multiplies the emit contribution per
fragment.

New `StageSlot::Emit`. New `sibling_emit_for_image` map in `TextureLoadResult`,
modelled on `sibling_normal_for_image`. New `sibling_emit_filename()` modelled on
`sibling_normal_filename()`, excluded from probing on derived maps so we don't
hunt for `<name>_normal_emit.tga`.

When no sibling exists, sentinel-bind a 1×1 white fallback so the shader sample
returns 1.0 unconditionally (same trick as `u_dark_map`). Byte-identical to a
no-mask render.

### 6.3 File format

**TGA, 8-bit greyscale.** `decode_tga` returns `channels = 1`, mapping to
`Image::Format::R8` — zero decoder work. Matches BC's `_glow` / `_specular`
naming pattern. ~25% the VRAM of RGBA. Exports cleanly from GIMP / Photoshop /
Paint.NET.

### 6.4 No config binding for masks

The `_emit.tga` association is **purely convention-based**. Sibling discovery
happens once per *texture*, not per *mesh*, and propagates automatically to every
material referencing that diffuse. An author drops `walllight_emit.tga` next to
`walllight.tga` and every mesh in every bridge using that diffuse picks it up
next build.

⚠️ **Masks leak by texture, not by mesh.** Any bridge diffuse also used on a ship
hull carries its mask across. This is the same papercut `_glow` and `_specular`
already live with; the escape hatch is to fork the texture. **Audit shared
textures before authoring starts** — it is much cheaper to find the overlap up
front than to debug a glowing hull plate later.

## 7. Emission composition

```
emit_color     = material.emissive          (from NIF NiMaterialProperty)
emit_per_texel = sample(sibling _emit.tga)  if found else 1.0
emit_per_group = profile[group](t)          if the surface has a profile else 1.0
final_emit     = emit_color × emit_per_texel × emit_per_group × diffuse.rgb
```

All three layers default to pass-through, so each case authors only what it needs.

| Need | What to author |
|---|---|
| Surface never emits | Nothing. (NIF emissive=0, no mask, no profile.) |
| Fixture, always glowing | Nothing. (NIF emissive=(1,1,1) suffices.) |
| Panel with inset bulbs only | `_emit.tga` sibling. |
| Fixture that dims or pulses at alert | Assign it an animation group (§9). |
| Both | `_emit.tga` + group assignment. |

The 2026-06-20 design split this into two mutually-exclusive regimes — a
`surface_emissive` entry for intensity-only changes, and an `emitter_mesh` link to
a dynamic light when the surface needed to *change colour*. With the lights gone,
the distinction dissolves: a profile supplies colour and intensity and timing
directly to the surface, and there is nothing to be mutually exclusive with.

`final_emit` feeds two consumers: the shaded surface itself, and the probe bake
(§8), which is what turns a glowing panel into light on the rest of the room.

## 8. The SH irradiance probe

### 8.1 Why a probe is needed at all

Screen-space GI alone has a fatal failure mode on this scene. The bridge camera
is a **mouse-look camera anchored at the captain's-chair pose** — fixed eye
position, yaw and pitch only, pitch clamped. If the only path from an emissive
surface to the room's lighting were screen-space gathering, then *turning your
head would brighten and dim the room* as ceiling panels swung in and out of
frame. On a translating camera that reads as GI imprecision; on a pure rotation it
reads as a bug, because the viewer knows the room did not change.

The probe supplies everything off-screen, so the total stays constant and only the
*sharpness* of the light changes as you pan. That is both correct and
perceptually almost invisible.

### 8.2 Capture

`CubemapTarget` already exists — 6-face RGBA16F, mip-mapped, shared depth
renderbuffer, with `allocate` / `bind_face(i)` / `generate_mips()`.
`BackdropPass::bake()` is the template: save FBO and viewport, enable
`GL_TEXTURE_CUBE_MAP_SEAMLESS`, a 90° aspect-1.0 projection, the canonical
`kFaces[6]` direction/up table, six bind-clear-lookAt-draw iterations, then
`generate_mips` and restore.

Three differences for the bridge:

1. **Keep the translation.** The sky bake uses `glm::mat4(glm::mat3(view))` to
   strip it, correct for a backdrop at infinity and wrong for a room at finite
   distance. Use the full `lookAt(anchor_eye, anchor_eye + face.dir, face.up)`.
2. **Draw emission only** — the light *sources*, not the lit room. A stripped
   variant of `bridge.frag` writing `final_emit` (§7) and black everywhere else.
   No lightmap, no ambient, no diffuse term. This is why the capture is cheap:
   there is no lighting to evaluate.
3. **Face size ~64–128, not `kSkyFaceSize`'s 1024.** Irradiance is a
   cosine-convolved signal carrying about as much information as nine numbers.
   Capture at 128² so a small bright LCARS panel lands on several texels instead
   of aliasing in and out as it animates, then let the mip chain box-filter down.

### 8.3 Projection: order-2 spherical harmonics

Project the radiance cube onto **9 RGB coefficients**. Ramamoorthi & Hanrahan
showed 9 coefficients reconstruct diffuse irradiance to ~1% error for any
lighting environment; diffuse irradiance is inherently low-frequency and there is
nothing to lose.

For each face texel: reconstruct its world direction, compute its solid angle,
evaluate the 9 SH basis functions, accumulate `radiance × basis × solidAngle`.
Fold in the Lambertian convolution constants (1, 2/3, 1/4 per band) once at the
end. Roughly 60 lines.

**Run it on the CPU.** Read back six 32² faces via `glGetTexImage` — about 48 KB
total — and project in C++. Reasons, in order of weight:

1. **It is testable where the team works.** `_PIXEL_TESTS_RELIABLE = sys.platform
   != "darwin"` means GPU pixel tests skip on macOS. A GPU-side convolution would
   be unverified on the primary development platform. A pure CPU projection drops
   straight into the 58-file `native/tests/renderer` suite and runs everywhere.
2. No GL version constraint, no shader, no sampler.
3. The readback is a sync point, but it happens at load and on discrete events —
   never per frame.

Evaluation in `bridge.frag` is ~20 ALU against a per-fragment budget that
comfortably absorbed 400 in the original design's estimate.

### 8.4 Per-group SH basis: why animation is free

The important property is that **irradiance is linear in source radiance, and SH
projection is linear.** So bake one 9-coefficient set *per animation group* (§9),
once, at load. Per frame:

```
SH_total(t) = Σ_g  w_g(t) × SH_g
```

That is `groups × 27` multiply-adds on the CPU. Arbitrary periods, arbitrary
phases, arbitrary waveforms — **no re-baking at any frame rate.** Cost scales
with the number of groups (expect 3–6 per bridge: general fixtures, alert strips,
consoles, cove, viewscreen), not the number of surfaces.

This is also the decisive argument for SH over a cosine-convolved cubemap: a
cubemap would need N textures blended per frame, or a re-bake per tick. SH needs
a weighted sum of 27 floats.

### 8.5 When to re-bake

- **Bridge load** — once, all groups.
- **Alert state** — never. Alert transitions are a change in `w_g(t)`, not in the
  bases.
- **Damage VFX** — console fires and sparks alter the emissive set. Cheapest
  answer is to leave them to SSGI's near-field, since they are local and usually
  on-screen when they matter. If they need to reach the fallback, re-baking six
  128² emissive-only faces is cheap enough to run at a few Hz and lerp between
  successive coefficient sets — again because SH interpolates linearly.
- **Camera translation** — see §11.2.

### 8.6 The honest limit

It is a **single-point** approximation: every surface in the room receives the
same off-screen irradiance for a given normal. Across a bridge a few metres wide
with the eye near the centre this is fine for walls, floor and consoles, and
wrong for a surface sitting directly under a cove strip, which should be much
brighter than the room average. SSGI's near-field covers most such cases, because
you are generally looking at a surface when its local lighting matters. Beyond
that we are adding probes, and the old design's placement objection returns — but
only for the few we add deliberately, not as a general system.

**Keep the radiance cube and its mip chain** alongside the SH coefficients.
Roughness-indexed mips are a serviceable stand-in for a proper GGX prefilter and
buy the glossy LCARS and chair-arm highlights from §1 that SH alone cannot do.

## 9. Animation: groups, profiles, and a shared clock

Placement collapses; **timing does not.** The 2026-06-20 design put animation on
the light (`animation_profile`) and let a surface inherit it by pairing with that
light. With no lights, profiles must become first-class and bind directly to
surfaces.

### 9.1 What must be authored

A **group tag** — which emissive surfaces animate together — plus a profile per
group giving colour and intensity per alert state, and an optional waveform. This
is the one piece of per-bridge configuration that survives, and it is a *tag*,
not a placement: far lighter than a per-light geometry schema plus an anchor
resolution system, but not nothing.

Groups are also the unit of the SH basis (§8.4), which bounds their count for
free: a bridge wants a handful of groups, not one per fixture.

### 9.2 Shared clock, per-group phase

The old `animation` block let every light specify its own `period_s`, `duty` and
`phase_s` independently. That is maximally expressive and it means N independent
blinkers rather than one heartbeat — not what red alert looks like on a real
bridge, and not what BC does.

**Constrain `period_s` to a bridge-wide clock and keep `phase_s` as the per-group
knob.** Coherence with variation — a travelling wave around the cove instead of
chaos — for the cost of one field's semantics.

This is also the house pattern, twice over: `subsystem_glow` uses a module-level
`PULSE_FREQ_HZ = 0.4` with per-ship amplitude, and `light_emitters` describes its
flicker as *"deterministic in game time … with a per-emitter phase so neighbours
desync."* Freeform `period_s` was the outlier.

⚠️ **Decide this before content is authored.** Profiles written against
independent periods cannot be retrofitted onto a shared clock without re-timing
every one of them by hand.

## 10. LTC area lights

Two, and they earn their place for the same reason: a large, soft, *nearby*
emitter is the case where an analytic area light beats probe-plus-SSGI outright.

### 10.1 Ceiling dome

As in the original design — one LTC rectangle for the big ceiling panel. Colour
and intensity come from its group's profile.

### 10.2 The viewscreen

The viewscreen is the brightest and most dynamic emitter in the room, and it must
**not** be left to SSGI: looking away from it would kill the light, which is the
§8.1 failure at its most visible. A torpedo detonation should throw light across
the bridge whether or not it is in frame.

It is an ideal analytic candidate — a known, fixed, planar quad at a known
position in bridge space — and its colour is nearly free:

> `g_viewscreen_hdr` is already an `HdrTarget` (RGBA16F). Call `glGenerateMipmap`
> on it and **the 1×1 mip is the average radiance of the space scene**, one texel,
> per frame. Feed that as the light's colour.

The composition properties are excellent. The space scene renders into the RTT at
640×360, by which point every light in it — the 64-per-frame dynamic budget, the
4 directionals, torpedo flashes, phaser beams, the sun — has already been
resolved into pixels. **An arbitrary number of forward lights collapses into one
emitter at fixed cost.** Sixty-four lights and four cost the bridge the same.

Ordering already works: the RTT is rendered before the bridge, in the same frame,
no latency and no reprojection. And bloom is computed from `g_hdr_target` *after*
the bridge renders, so a detonation on the viewscreen blooms off it and into the
room without any special-casing.

The behaviour falls out for free in the edge cases: comm channels put another
bridge on the screen and the light simply takes that colour; `viewscreen_on ==
false` binds texture 0 and the emitter goes dark.

### 10.3 Four things the viewscreen light forces us to decide

1. **Double counting.** If the viewscreen is an analytic light *and* SSGI gathers
   from its on-screen pixels, it is counted twice. Fix with a material bit in the
   G-buffer — "already accounted analytically" — and have SSGI skip rays
   terminating on it. We will want that bit for other emitters eventually.
2. **Unbounded HDR.** The bridge samples `g_viewscreen_hdr->color_texture()` raw
   and untonemapped. Physically correct, but a sun in frame or a warp flash can
   put arbitrarily large values into that 1×1 mip, and those now drive the whole
   room. **An explicit clamp / soft-knee / exposure-coupling policy is required**,
   decided deliberately rather than discovered when someone flies past a star.
3. **It reverses an existing decision.** `host_bindings.cc` confines the warp
   flash to the viewscreen feed — *"the surrounding interior must not flash"* —
   and suppresses the main resolve-pass flash while the bridge is active. With the
   viewscreen as a light, the interior *would* flash. Physically right, probably
   desirable, but it must be reversed on purpose. The same question applies to the
   red-alert dim, which scales interior ambient while deliberately leaving the
   comm feed unscaled: a bright battle outside will partially undo it.
4. **Exposure paths differ.** `filmic_on = dauntless_filmic::enabled() &&
   exterior` — the filmic pass is off in bridge view, so the bridge tonemaps only
   through `resolve_pass`. Once the viewscreen drives bridge exposure, the two
   views respond to bright content differently.

### 10.4 Viewscreen fidelity: drop dynamic lights on the RTT path

`render_space` already takes `for_viewscreen` and already uses it to gate the dust
pass. Extend that to the dynamic light list:

```cpp
ambient_scale, for_viewscreen ? nullptr : &g_dynamic_lights);
```

`select_instance_dynamic_lights` early-returns on `!lights` *before*
`model_bounding_radius` and before the O(64) scan, so this skips the per-instance
CPU selection — the resolution-independent cost the 640×360 downscale does *not*
save — as well as the shader's light loop and its per-draw uniform uploads.

What is lost is small: the dramatic brightness on the viewscreen comes from
separate passes (torpedo sprites, hit VFX, shockwaves, particles, phaser beams,
lens flare), and ship nacelle/window brightness is `u_glow_map` + `u_emissive`,
not the emitters. Only *reflected* light on nearby hull disappears — a subtle
gradient on a handful of pixels of a ship ~100px across. The bridge area light is
entirely unaffected.

⚠️ Ships now render differently in exterior view and on the viewscreen. Deliberate,
but it breaks any test asserting the two match, and will look like a bug to anyone
comparing screenshots. Comment it at the call site.

## 11. SSGI: where it applies and where it does not

### 11.1 Why the bridge is the good case (and space is not)

The same technique was evaluated for the exterior space renderer and rejected.
The bridge inverts every objection:

| | Space | Bridge |
|---|---|---|
| Scene occupancy | Ships isolated against a void — most of the neighbourhood is off-screen | Enclosed; frame is filled with geometry at a few metres |
| Camera | Flies and orbits; constant disocclusion | Fixed eye, rotation only — reprojection is an exact homography |
| Screen-edge fade | Silhouetted against black, reads as a bug | Lands on a bulkhead, invisible |
| Emitters vs receivers | Emitters far from what they'd light | Panels and receivers metres apart in a closed box |

### 11.2 Composition rule

SSGI supplies what is on screen; the probe supplies what is not, and they must not
overlap. Every ray terminates in a hit or a miss (leaves frame, exceeds march
length, fails the thickness test). Track the hit fraction as confidence:

```glsl
vec3 indirect = ssgi_result + (1.0 - ssgi_confidence) * sh_irradiance(N);
```

Implementation shape, all at GLSL 330: hierarchical-Z stepping off a depth mip
chain, per-pixel blue-noise jitter, a thickness heuristic; spatial denoise via an
edge-aware à-trous blur guided by G-buffer normal and depth; temporal denoise by
reprojection with neighbourhood clamping.

**There is no velocity buffer to reuse.** `motion_blur_pass` is *camera* motion
blur — a depthless fixed-distance reprojection against `u_prev_viewproj`, which
carries no per-object motion. But the fixed camera makes that mostly moot: with a
rotation-only eye, reprojecting **static** geometry is an exact homography needing
no velocity at all. Only genuinely moving content — crew, damage VFX — needs
per-object velocity, so if a velocity target is wanted it can be scoped to the
skinned and VFX draws rather than the whole scene.

**Cutscenes translate the camera.** `bridge_cutscene._update_camera` samples an
animated translation+rotation track and calls `set_anim_pose` — walk-on, sit,
stand. That breaks the fixed-anchor premise twice: the probe is baked where the
camera no longer is, and translation reintroduces genuine parallax disocclusion.

The fix falls out of §8.4's linearity: a camera track can have a **probe track**.
Bake at the clip's keyframe positions and lerp coefficients by the same `t` the
existing `sample_translation` / `sample_rotation` already compute. Tracks are known
ahead of time, each bake is six tiny emissive-only faces, and interpolating 27
floats is free. SSGI degrades during the translation, but the probe carries the
amount and only sharpness is lost.

### 11.3 Comm sets: SSGI off

`set_viewscreen_comm_source` renders another set through `BridgePass` with
`Pass::Comm`, so comm sets inherit whatever the bridge pass gains unless gated.
**Gate SSGI off for them.**

The decisive reason is cuts. Temporal denoising needs several frames to converge,
and a hard cut invalidates *every* pixel's history at once — there is no
reprojection across a cut. Comm content is nothing but cuts: a hail opens, a face
appears, it closes. Every channel-open would show noise resolving over half a
second on **a face filling a 640×360 frame** — the most scrutinised surface in the
game.

The main bridge's probe does not transfer either: a comm set is a different set,
elsewhere, with its own lighting, and its camera is supplied per call from Python.
But that is also the fix — `set_viewscreen_comm_source` is a discrete event with a
known camera, so **bake a probe at that eye position when the channel opens.**

Comm sets then get direct + SH + emissive with no screen-space gather and no
temporal filter: stable by construction, cheap, and barely a loss, since near-field
contact GI on a head-and-shoulders shot at 640×360 is below the perceptual
threshold. It also keeps the comm RTT on a light forward path, which matters —
see §12.

### 11.4 Summary

| Path | Emissive + direct | SH probe | SSGI |
|---|---|---|---|
| Main bridge, normal play | yes | fixed anchor, exact | yes — near-ideal |
| Main bridge, cutscene | yes | probe track, lerped | degraded, non-critical |
| Comm set on viewscreen | yes | baked on channel open | **no** — cuts kill the denoiser |
| Space on viewscreen | n/a | n/a | n/a |

## 12. Cost, and the profiling gate that must come first

**There is no GPU timing instrumentation in this codebase.** `GL_TIME_ELAPSED`,
`glQueryCounter` and `glBeginQuery` return zero hits across `native/`. There is no
frame-time counter in `host_loop.py` either.

So the cost of everything in this document is currently unmeasurable, and so is
the cost of what it replaces. **Build the measurement first.** It is cheap and it
is valuable whichever way the verdict goes:

- A `ScopedGpuTimer` over `GL_TIME_ELAPSED` query objects, double- or
  triple-buffered so results are read N frames late and `glFinish` is never
  called. Wrap each pass — there are ~35. Expose the per-pass table through a
  pybind binding so the Python harness can assert on it.
- CPU-side timing separately, on a fixed replay scene, or the numbers are not
  comparable between runs.

### 12.1 What the budget probably looks like

Bridge view is already the cheap mode. The main-target space render is **skipped**
while the bridge is active; space renders once, into the RTT:

| | Space render resolution | Pixels |
|---|---|---|
| Exterior view | full framebuffer | 2.07M @1080p, 3.69M @1440p |
| Bridge view | 640×360 | **0.23M** |

A 9–16× cut in fragment work, and `for_viewscreen` only skips the dust pass. That
surplus is what this design spends — we are not adding a render, we are
re-spending one already downscaled.

⚠️ **The saving is fragment-only.** Scene traversal, culling, per-instance light
selection, animation update, bone palettes and draw submission cost the same at
640×360 as at 1440p, and the sun shadow map is computed once per frame before any
`render_space` and shared. Given only 3 `glDraw*` call sites in `frame.cc` and
essentially no instancing outside the dust pass, the space scene may well be
CPU- or draw-call-bound — in which case the surplus is much smaller than the pixel
ratio implies and this work must be funded elsewhere. **This is exactly what the
timer answers.**

### 12.2 The one genuinely doubled cost

Comm sets render a bridge into the RTT *and* the main bridge in the same frame.
§11.3 keeps SSGI off the comm path, which contains it — but the G-buffer and probe
evaluation would still run twice unless the comm path stays on a cheap forward
variant. Decide early; it is far easier to keep two paths separate from the start
than to split them later.

## 13. Sequencing hazard

The pieces have a forced order, because the lightmap is currently the only source
of spatial variation (§2):

1. **Emissive + emit masks** — the only part that works standalone, since emissive
   is a self-lit floor needing no light source.
2. **Probe + area lights** — nothing below this line does anything without a
   lighting term to modulate.
3. **Normal + specular maps** — need (2) to be visible at all. With only an
   ambient constant, `perturb_normal` returns a normal nothing uses and the
   specular term has no `L`.
4. **SSGI.**

⚠️ You cannot drop the lightmaps and then land the rest incrementally. The bridge
is visibly broken between step 1 and step 2, so **§15's removals must not land
until phase 3 is green.**

## 14. Phased build order

Each phase has its own off-ramp — if an earlier phase already meets the bar, later
ones can be deferred or dropped.

| # | Phase | Goal | Authored how | Effort |
|---|---|---|---|---|
| 0 | **GPU timer** | Per-pass ms on a fixed scene. Nothing here is affordable-or-not until this exists. | None. | ~0.5 session |
| 1 | **`_emit.tga` sibling probe** | `StageSlot::Emit`, sibling discovery, 1×1 white fallback, bridge shader samples it. | Two or three hand-painted masks. | ~0.5 session |
| 2 | **Emissive capture + SH probe** | Emissive-only cubemap bake at the anchor, CPU SH projection, `bridge.frag` evaluates it. **Go/no-go gate.** | None beyond phase 1. | ~1.5 sessions |
| 3 | **Normals into the bridge pass** | MRT G-buffer, port `perturb_normal` + specular from `opaque.frag`. Lightmap removable from here. | `_normal` / `_specular` siblings. | ~1 session |
| 4 | **Groups + profiles + shared clock** | Alert-state colour/intensity, per-group SH bases, linear blend. | Short per-bridge config. | ~1 session |
| 5 | **LTC ceiling + viewscreen area lights** | Analytic rectangles; 1×1 mip drives the viewscreen colour. | Two entries. | ~1.5 sessions |
| 6 | **SSGI** | Screen-space near-field with confidence fallback to the probe. Gated off for comm sets. | None (auto). | ~2.5 sessions |
| 7 | **Cheat lights** | A handful of invisible point lights for fill. | Short config. | ~0.5 session |

**Phase 2 is the go/no-go.** The question is *"does emissive + a single SH probe
beat BC's lightmap?"* — cheaper to build than the original design's phase 1
(hard-coded Phong), and it tests the assumption the whole revision rests on. If it
does not clear the bar, very little has been spent finding out.

## 15. Removals from the existing codebase

Once phase 3 ships, remove:

- `assets::Material::lightmap_pass` and its setting in
  `material_build.cc::build_material` (the `filename_is_lightmap` block).
- The `walk_bridge_meshes` second pass with `want_lightmap_pass=true` in
  `bridge_pass.cc::render`.
- The UV1 lightmap sampling in `bridge.frag` (`u_dark_map`, `v_uv1`).
- `lightmap.frag` / `lightmap.vert` and their pipeline entries.
- The `lightmap_pass` partition tests in `tests/renderer/bridge_pass_test.cc`.
- BC `_lm.tga` / `-lm.tga` / `_LM.tga` handling in `filename_is_lightmap()`.

Also review, once phase 4 ships:

- The red-alert interior ambient scale in `host_loop.py`. With lighting derived
  from emissive, a global ambient multiplier is the wrong lever — the dim should
  fall out of the profiles, because the fixtures are what dim.

The `_glow` and `_specular` sibling paths **stay**. The original text justified
that with "they're used by ship hulls, not bridges"; under this design bridges use
`_specular` and `_normal` too, so they stay for a stronger reason.

## 16. Testing

The CPU-side pieces are the valuable ones to test, because they are the ones that
run everywhere:

- **SH projection** — pure function, cube faces in, 27 floats out. Analytic cases
  (uniform white environment, single bright texel, two-lobe) have closed-form
  answers. Goes in `native/tests/renderer`.
- **Per-group blend** — `Σ w_g(t) × SH_g` linearity, alert transitions, phase
  offsets against a shared clock.
- **Emit-mask discovery** — sibling found / not found / derived-map exclusion,
  mirroring the existing `ModelBuildNormalDiscovery` tests.

⚠️ `_PIXEL_TESTS_RELIABLE = sys.platform != "darwin"` means GPU pixel tests skip on
macOS. Anything asserted only in pixels is unverified on the primary development
platform — so keep the load-bearing logic on the CPU side of that line.

## 17. What was dropped from the 2026-06-20 design, and why

| Dropped | Original effort | Why |
|---|---|---|
| `tube` / `polyline_tube` / `bezier_tube` primitives | ~1 session | They existed to model cove strips. A cove strip *is* emissive geometry with a mask; the primitive collapses into the mask. |
| `lighting.json` light array + per-light fields | ~0.5 session | Position and geometry come from the mesh. |
| `anchor_block` mesh identity (§6), incl. a new field on `Mesh` and a new map on `Model` | included above | Nothing needs to name a mesh any more. Takes the re-export fragility with it. |
| Dev-mode light editor | ~1.5 sessions | Authoring moves to a paint program. |
| `emitter_mesh` link + `emissive_blend` + the two-regime mutual exclusion | — | With no lights to pair against, one regime remains (§7). |
| Standalone SSAO pass | ~0.5 session | Subsumed by SSGI's occlusion term. Retained as an off-ramp if SSGI is cut. |

**Retained and promoted:** `_emit.tga` (§6) from refinement to primary; the LTC
area light, which becomes *more* important, not less.

**Retained unchanged:** shadow maps for key lights. SSGI gives screen-space
occlusion and SSAO gives contact darkening, but neither is a cast shadow — a
character shadowing the floor under the ceiling panel works only because both are
on screen. Partial collapse at best; still worth its own phase later.

**Retained unchanged:** a transient damage-light slot populated per frame from the
damage system (old §16 q3). A console fire behind you should light the room and
will not be in the static probe.

**Inverted:** old §14 rejected realtime GI for v1 while noting *"if we ever want
global illumination later … that is the right next step."* Old §15 deferred light
probes while naming the exact trigger: *"if we later … want bounced indirect light
from emissive surfaces back onto the room (a glowing LCARS panel lighting up the
chair next to it), probes become the natural addition."* This design is that
addition — arriving as one exactly-placed probe rather than a placement system,
because the camera does not move.

## 18. Open questions for the implementation session

1. **Group granularity** — how many animation groups does a real bridge need? The
   SH cost is per group, so this is a budget question as well as an authoring one.
2. **Emit-mask colour** — greyscale mask × material emissive gives one colour per
   material. Is that enough, or does a panel need per-texel *colour* (RGB mask)?
   Greyscale is the cheaper start and can be widened later.
3. **Viewscreen HDR policy** — clamp, soft knee, or exposure coupling (§10.3 q2).
   Needs a decision before the area light lands, not after.
4. **Probe-track granularity** for cutscenes — bake per keyframe, or at fixed time
   intervals along the clip?
5. **Comm-set probe lifetime** — bake per channel-open, or cache per set id?
   Caching is obvious if comm cameras are reused; needs checking against how
   `set_viewscreen_comm_source` is actually driven.
6. **Non-bridge interiors** (Engineering, Sickbay). The asset layout is generic;
   does the group/profile model generalise, or is alert state bridge-specific?
7. **Shared-texture audit** — which bridge diffuses are also used on ships, before
   any `_emit.tga` authoring begins (§6.4).

## 19. Asset layout

```
native/assets/sets/
├── EBridge/
│   ├── lighting.json              ← groups + animation profiles only
│   ├── walllight_emit.tga         ← per-texture emit masks
│   ├── walllight_normal.tga
│   ├── walllight_specular.tga
│   ├── floorlight_emit.tga
│   └── ...
└── DBridge/
    └── ...
```

- **`sets/`** not `bridges/` — matches BC's own `Models/Sets/` convention. Cargo
  bays, briefing rooms and any future interior set inherit the layout.
- **Per-bridge dir name** = NIF directory name (`EBridge`, `DBridge`), not the SDK
  class name (`SovereignBridge`). Avoids the `Sovereign`/`SovereignBridge`
  papercut.
- The BC install (`game/data/Models/Sets/EBridge/High/`) is **never modified**.
  `PathResolver` adds `native/assets/sets` as a higher-priority search path and
  falls back to the install.
- `lighting.json` is now small — groups and profiles, no geometry.

## 20. References

- Ramamoorthi & Hanrahan, *An Efficient Representation for Irradiance Environment
  Maps* (SIGGRAPH 2001) — the 9-coefficient result §8.3 relies on.
- Heitz et al., *Real-Time Polygonal-Light Shading with Linearly Transformed
  Cosines* (SIGGRAPH 2016) — LTC area lights, §10.
- Karis, *Real Shading in Unreal Engine 4* — representative-point approximation,
  retained for any tube-shaped cheat lights (§4.2).
- `BackdropPass::bake()` — the working cubemap bake this design clones (§8.2).
- `opaque.frag::perturb_normal()` — the no-tangent cotangent frame reused for
  bridge normal mapping (§5).
