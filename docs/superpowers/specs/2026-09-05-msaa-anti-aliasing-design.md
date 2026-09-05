# MSAA anti-aliasing — design

**Date:** 2026-09-05
**Status:** approved, not implemented

## Problem

SMAA 1x is the only anti-aliasing we have, and on a live look Mark found it
underwhelming: hull edges against black stay jaggy. That is the genuine
ceiling of *spatial* post-AA on this content. SMAA infers edges from colour
discontinuities in an already-aliased image; it has no extra samples to work
with. Where a hull silhouette is a few pixels wide — a distant ship, a nacelle
pylon — the information was never sampled, so no post filter can recover it,
and the edge crawls frame to frame as the ship moves sub-pixel distances.

Two fixes exist: take more samples (MSAA/SSAA) or reuse samples across frames
(TAA). TAA needs motion vectors we do not have and would fight the grain and
chromatic aberration in `filmic.frag`. This design takes the first.

**MSAA rather than SSAA**, for two reasons specific to this engine:

1. **We are a forward renderer.** `opaque.frag` does its lighting inline, which
   is the case MSAA was built for — it shades once per pixel and multi-samples
   only coverage. Hull-against-black is *purely geometric* aliasing, so MSAA
   addresses the actual artifact at a fraction of SSAA's shading cost.
2. **GPU pixels are our cheap resource.** `docs/engine/frame-profiler.md`
   records the combat frame as `sim` ~70 ms against `r.frame` ~15-24 ms. The
   bottleneck is Python and CPU-side throughout, so spending GPU bandwidth on
   coverage samples is close to free in wall-clock terms.

SSAA remains the better answer for sub-pixel *dropout* — geometry thinner than
a pixel, which MSAA improves but does not fix. It is out of scope here and
stays on the shelf as `project_render_scale_followup` describes.

## Scope decision: opaque geometry only

MSAA covers **backdrop, suns, opaque hulls, breach and shield**. Everything
from dust onward — nebulae, beams, torpedoes, particles, godrays, cloak —
renders after the resolve, single-sampled, exactly as today.

This is deliberate, on two grounds:

- **It targets the artifact.** Beams, torpedoes, particles and shield bubbles
  are soft additive gradients, effectively self-antialiased. Multisampling
  them buys close to nothing.
- **It leaves the fragile passes alone.** `nebula_godray_pass` and `cloak_pass`
  both sample `target.color_texture()` *while rendering into that same target*
  (`u_scene` in each). That is a GL feedback loop — undefined by the spec,
  functional on this driver. Multisampling through them would force us to
  change their semantics, and a failure there would surface inside a
  refraction and a volumetric light shaft, where "MSAA is broken" and "the
  effect is broken" are indistinguishable by eye.

A whole-pass MSAA variant was considered and rejected: it needs three extra
full-screen resolves per frame (a depth resolve for the nebula march, and a
colour resolve each for godray and cloak) to buy AA on content that does not
need it.

## Render architecture

### The target

A new `HdrMsaaTarget` alongside `HdrTarget`, not a sample-count parameter on
it. This follows the convention already used for shadows, specular and normal
maps: the OFF path stays byte-identical rather than merely equivalent.

Both attachments are **renderbuffers, not textures** —
`glRenderbufferStorageMultisample` with `GL_RGBA16F` colour and
`GL_DEPTH_COMPONENT24` depth. Nothing samples the multisample surfaces; we only
blit out of them. This avoids `sampler2DMS` and per-sample fetch entirely.

Sample counts are clamped at startup against `GL_MAX_SAMPLES` (queried in
`gl_caps`). Counts the driver will not give us are not offered in the UI.
Framebuffer completeness is checked at runtime and falls back rather than
trusting the spec — Apple's GL is already where our `GL_TIMESTAMP` counters
silently returned zeros.

### Frame flow, MSAA active

1. Bind the MSAA FBO. Render backdrop → suns → opaque → breach → shield.
2. One `glBlitFramebuffer` into `g_hdr_target` with
   `GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT` and `GL_NEAREST` (required when
   the blit includes depth). **This is the resolve.**
3. Bind `g_hdr_target` — single-sample, unchanged — and render dust → nebula →
   godray → lens flare → weapons → hull discharge → shockwave → particles →
   cloak, exactly as today.
4. Post chain (bloom → resolve → SMAA → motion blur → filmic) entirely
   unchanged.

The shape is chosen so that **after step 2 every downstream pass receives
precisely the two textures it already expects**. `nebula_volumetric` gets a
populated single-sample depth texture for its march terminator;
`nebula_godray` and `cloak_pass` get a sampleable `color_texture()`. No code
downstream of the resolve changes, and the existing feedback-loop behaviour is
preserved rather than re-reasoned.

### Frame flow, MSAA off

`render_space` binds `g_hdr_target` directly, as today. The MSAA FBO is
allocated lazily on first use, so an Off/SMAA session never creates it and
never blits.

### The refactor this requires

`render_space` in `host_bindings.cc` is currently one ~130-line lambda that
both renders geometry and reads `target.color_texture()` for the VFX passes.
It splits in two at the point after `shield_pass->submit` — a geometry phase
and a VFX phase — so the two can take different targets. Mechanical, but it is
the substantive work in this half.

### Viewscreen RTT: excluded

`render_space` is shared with the bridge viewscreen render-to-texture. That is
a small in-world surface where edge quality barely reads, so it passes the
plain `HdrTarget` to both phases and never allocates an MSAA buffer.

### Memory cost

At a retina backing store (~2560×1440), 4× costs roughly 120 MB of colour plus
45 MB of depth; 8× doubles that to ~330 MB, on top of CEF's 302 MB. 8× is
retained deliberately — it is of real use on gaming rigs — but is offered only
where `GL_MAX_SAMPLES` allows.

## Settings and UI

### One "Anti-aliasing" selector

SMAA and MSAA become mutually exclusive members of a single setting rather
than two independent toggles. The player sees one row:

```
Anti-aliasing    [ Off | SMAA | 2× | 4× | 8× ]
```

The short segment labels avoid repeating "MSAA" five segments wide.

### The setting row

Replaces the existing `smaa` row, mirroring `ai_difficulty`'s shape so no new
store machinery is needed:

```python
_MSAA_SAMPLES = (0, 0, 2, 4, 8)   # indexed by aa_mode

Setting("aa_mode", "graphics", "aa_mode", int, AA_SMAA,
        _fan(lambda c, v: c.r.set_smaa_enabled(v == AA_SMAA),
             lambda c, v: c.r.set_msaa_samples(_MSAA_SAMPLES[v])),
        lo=0, hi=4, reset_default=AA_SMAA)
```

Reusing `_fan` keeps `smaa_set_enabled` untouched and adds exactly one new
binding, `msaa_set_samples`. The mutual exclusion lives in the settings table,
alongside the rest of the semantics.

The stored value is an **index, not a sample count**, so the store's `lo`/`hi`
performs its normal contiguous-range check. Driver capability is a separate
concern, handled by clamping at apply time against `GL_MAX_SAMPLES`. A settings
file carrying index 4 on a 4×-max machine therefore applies 4× and applies 8×
again if moved to a machine that supports it — which is the desired behaviour.

**The default stays SMAA** (index 1). The shipped baseline is unchanged and no
player inherits a 160 MB allocation without asking for it.

### Migration

`SCHEMA_VERSION` goes 1 → 2. The store currently writes a version stamp that
nothing reads, so this adds the migration seam: a `_migrate()` called from
`load()` that, when `graphics.smaa_on` is present and `graphics.aa_mode` is
not, sets `aa_mode = 1 if smaa_on else 0`, drops the old key and restamps.

It must respect the store's existing rule that a file stamped *newer* than us
keeps its stamp — migrate up, never down.

### Panel changes

- `SettingsSnapshot.smaa_on: bool` → `aa_mode: int`.
- The SMAA toggle row becomes a 5-segment selector reusing the AI Difficulty
  markup and `cp-*` CSS (`configuration_panel.js:174-182` is the template).
- `_focusables` renames `("ctrl", "smaa")` → `("ctrl", "aa_mode")` and gains
  the same left/right handling as `configuration_panel.py:452`.
- `dispatch_event` gains `aa_mode:<index>` and loses `toggle:smaa`.

## Testing

**pytest** — migration in both polarities, an already-v2 document left
untouched, a newer-stamped document not downgraded; the applier fan across all
five indices; panel dispatch and keyboard navigation; `reset_and_apply_section`
restoring SMAA.

**renderer_tests (ctest)** — `HdrMsaaTarget` framebuffer completeness at each
sample count; the `GL_MAX_SAMPLES` clamp; a `FrameTest` asserting the resolve's
colour *and depth* match a single-sample reference on a trivial scene.

Gate is `scripts/check_tests.sh` (both suites, diffed against
`tests/known_failures.txt`).

**What the tests cannot establish:** whether this looks better than SMAA. That
is a live check, and it must run in the main tree rather than a worktree.

## Risks

1. **Depth-resolve sample selection.** `glBlitFramebuffer` with
   `GL_DEPTH_BUFFER_BIT` off a multisample FBO is widely supported, but which
   sample it selects is implementation-defined, and `nebula_volumetric` depends
   on that depth to terminate its march. **Verify this first, not last.** The
   symptom is nebulae clipping incorrectly against hulls. Escape hatch: resolve
   depth with a small `sampler2DMS` shader taking sample 0.
2. **Memory at 8×** on a retina backing store, as costed above.
3. **Apple GL trust.** Check framebuffer completeness at runtime and fall back;
   do not assume `GL_RGBA16F` multisample works because the spec says so.

## Out of scope

- SSAA / render-scale (`project_render_scale_followup`).
- TAA (needs motion vectors).
- MSAA on the viewscreen RTT.
- Anti-aliasing the VFX layer.
