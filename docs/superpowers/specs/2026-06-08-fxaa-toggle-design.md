# FXAA Toggle — Design

**Date:** 2026-06-08
**Status:** Approved
**Branch:** `feat/damage-decals-phase1` (current working branch)

## Summary

Add a post-process FXAA (Fast Approximate Anti-Aliasing) pass to the renderer,
exposed as a single on/off control in the Graphics configuration panel,
**default on**. The control mirrors the existing HDR / rim / decals toggles
end-to-end.

### Scope note

The original request asked for an `Off / 1x / 2x / 4x` slider. FXAA is a single
screen-space filter with no native sample multiplier, so those steps would have
to map onto quality presets or supersampling — a materially larger change. The
user revised the scope to a plain **on/off** toggle. This spec implements that.
"Default 1x" therefore means **default on**.

## Where FXAA runs in the frame

Today the resolve pass tonemaps the HDR target straight to the default
framebuffer (FBO 0) — see
[host_bindings.cc:326-329](../../../native/src/host/host_bindings.cc#L326-L329).
FXAA needs the final LDR image available as a texture to detect edges, so one
pass is inserted **after** resolve:

- **FXAA off** (and the untouched default path): resolve → FBO 0. Zero added
  cost; byte-identical to today.
- **FXAA on:** resolve → new LDR intermediate FBO, then `FxaaPass` samples that
  texture → FBO 0.

`ResolvePass` itself is **not** modified. The host frame code chooses which
framebuffer is bound before `g_resolve_pass->draw()`:

```text
if (fxaa enabled) { g_ldr_target->resize(fw, fh); g_ldr_target->bind(); }
else              { glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,fw,fh); }
g_resolve_pass->set_hdr_enabled(...);
g_resolve_pass->draw(hdr_color, bloom_tex);
if (fxaa enabled) {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, fw, fh);
    g_fxaa_pass->draw(g_ldr_target->color_texture(), fw, fh);
}
```

## Components

### New C++ pieces

1. **`LdrTarget`** (`native/src/renderer/ldr_target.{h,cc}`, header under
   `include/renderer/`) — a color-only RGBA8 FBO that resizes with the window.
   A trimmed copy of `HdrTarget` with no depth attachment. Allocated lazily; it
   is only `resize()`d/`bind()`d when FXAA is enabled, so the off-path never
   touches it.

2. **`FxaaPass`** (`native/src/renderer/fxaa_pass.{h,cc}`, header under
   `include/renderer/`) + **`shaders/fxaa.vert`** / **`shaders/fxaa.frag`** —
   a fullscreen-triangle pass running standard FXAA 3.11. Luma is computed
   in-shader from RGB (`dot(rgb, vec3(0.299, 0.587, 0.114))`); the pass takes a
   `u_inv_resolution` uniform (`1/fw, 1/fh`). It saves and restores the same GL
   state the resolve pass does (cull / depth-test / blend) so the next frame's
   3D passes see unchanged config. Two `embed_shader(...)` lines are added to
   `native/src/renderer/CMakeLists.txt`.

3. **`dauntless_fxaa`** config namespace (default `true`) +
   `m.def("fxaa_set_enabled", ...)` binding in
   `native/src/host/host_bindings.cc`, both mirroring `dauntless_hdr`. Global
   `g_ldr_target` and `g_fxaa_pass` instances are created in the renderer-init
   block and reset in the teardown block alongside the existing passes.

### Python / UI plumbing (mirrors the HDR toggle exactly)

4. **`engine/renderer.py`** — add `set_fxaa_enabled(enabled: bool)` calling
   `_h.fxaa_set_enabled(enabled)`.

5. **`engine/host_loop.py`** — add `fxaa_on=True` to the `SettingsSnapshot(...)`
   and `set_fxaa=r.set_fxaa_enabled` to the `ConfigurationPanel(...)` call
   (around lines 2058–2076).

6. **`engine/ui/configuration_panel.py`** — add the `fxaa_on` field to
   `SettingsSnapshot`, the `set_fxaa` constructor callback, the `toggle:fxaa`
   branch in `dispatch_event`, and `fxaa_on` in the `render_payload` settings
   dict (and the focusables/ctrl list).

7. **`native/assets/ui-cef/js/configuration_panel.js`** — render an "FXAA"
   toggle row in `_cpRenderGraphicsBody` (mirroring the HDR row, firing
   `configuration/toggle:fxaa`) and add `{kind: 'ctrl', target: 'fxaa'}` to the
   focusables list.

## Defaults & persistence

There is no settings persistence anywhere today — every default is hardcoded in
the `SettingsSnapshot` constructed in `host_loop.py`. "Default on" is therefore
expressed by `fxaa_on=True` there, and by the `dauntless_fxaa` namespace
defaulting its flag to `true` on the C++ side (so the renderer is correct even
before any Python call).

## Testing

- **Python:** mirror the existing configuration-panel tests — assert that
  `toggle:fxaa` flips state and invokes the `set_fxaa` callback, that `fxaa_on`
  defaults to `True`, and that it appears in `render_payload`. (Use a focused
  pytest subset — the full suite OOMs the host.)
- **C++ / GL:** there is no unit harness for the GL passes; the pass is verified
  visually at runtime. The off-path is unchanged, so the regression surface is
  limited to the on-path.

## Out of scope

- Multi-step / supersampling quality levels.
- Settings persistence to a config file (no such mechanism exists yet for any
  graphics toggle).
- Applying FXAA inside bridge mode differently — it runs on the final composited
  LDR backbuffer regardless of mode, same as resolve.
