# Debug Volume Overlay (`DebugVolumePass`)

A small, self-contained developer tool for drawing **bright wireframe cylinders
in world space** over the scene — for *visualising 3D volumes* that are
otherwise invisible (subsystem radii, effect containment shapes, trigger zones,
collision proxies, etc.).

It was built to sanity-check the impulse-engine glow **boost volume** (the
region the shader tests against when brightening aft engine faces). Seeing the
actual radius/axis in-scene turned a guessing game ("is it catching the window
lights?") into a direct read. It is kept in the tree as a reusable diagnostic
for similar "where is this volume, really?" questions.

- Pass: [`native/src/renderer/debug_volume_pass.{h,cc}`](../../native/src/renderer/debug_volume_pass.cc)
- Built into the `renderer` lib (listed in `native/src/renderer/CMakeLists.txt`).
- **Not wired into the frame by default** — instantiate + call it where you need
  it (see *Wiring it in* below). Zero cost when unused (no GL resources are
  created until the first `render()` with a non-empty list).

## What it does

- Owns its own shader (inline GLSL 330) and a unit-cylinder mesh (radius 1,
  along local +Z, 0..1). No asset files, no embedded-shader/CMake codegen.
- `render(cylinders, camera)` draws each `DebugCylinder` as a green (or custom
  colour) **wireframe** via `glPolygonMode(GL_LINE)`.
- **Depth test OFF** — cages always draw over the hull so you can see volumes
  that are inside/behind geometry. (Flip to depth-on if you want them occluded
  naturally; see *Tuning*.)

## API

```cpp
struct renderer::DebugCylinder {
    glm::vec3 center;   // world-space base-cap centre
    glm::vec3 axis;     // world-space unit direction the tube extends along
    float     radius;   // world units
    float     length;   // extent along axis from center
    glm::vec3 color;    // wireframe colour (default bright green)
};

renderer::DebugVolumePass pass;                 // construct once (GL context live)
pass.render(std::vector<DebugCylinder>{...},    // rebuild the list each frame
            camera);
```

Everything is **world space** — the caller is responsible for transforming from
whatever local/model frame the source data lives in.

## Wiring it in (host_bindings.cc)

The pass is intentionally dormant. To turn it on, add ~5 lines to the frame path
in `native/src/host/host_bindings.cc` (mirrors `g_subsystem_pin_pass`):

```cpp
#include <renderer/debug_volume_pass.h>                       // near the other renderer includes

std::unique_ptr<renderer::DebugVolumePass> g_debug_volume_pass;   // with the other g_* pass globals

// in the renderer-init block (where g_subsystem_pin_pass is created):
g_debug_volume_pass = std::make_unique<renderer::DebugVolumePass>();

// in the teardown/reset block (while the GL context is still alive):
g_debug_volume_pass.reset();

// in the frame draw, after render_space(), alongside the pin-pass block:
if (g_debug_volume_pass && dauntless::is_developer_mode() &&
    !viewer_mode && !bridge_active) {
    std::vector<renderer::DebugCylinder> cyl = build_debug_cylinders();  // see below
    g_debug_volume_pass->render(cyl, g_camera);
}
```

Gate it on `dauntless::is_developer_mode()` so production is byte-identical.

## Example: cylinders from per-instance `GlowRegion` data

This is how the impulse-volume overlay was built. Each ship `Instance` carries
`glow_regions` (`native/src/scenegraph/include/scenegraph/instance.h`) whose
`center/axis/radius/aft/fore` are in the **model frame** (game units already
divided by the instance scale — see `add_cylinder_region` in host_bindings).
Multiply by `inst.world` to get world space:

```cpp
std::vector<renderer::DebugCylinder> build_debug_cylinders() {
    std::vector<renderer::DebugCylinder> out;
    g_world.for_each_visible([&](const scenegraph::Instance& inst) {
        for (const auto& r : inst.glow_regions) {
            if (!r.active) continue;
            if (glm::dot(r.axis, r.axis) < 1e-6f) continue;         // skip spheres
            if (glm::dot(r.gain_axis, r.gain_axis) < 1e-6f) continue; // impulse cylinders only
            // model-frame cylinder -> world space through inst.world
            const glm::vec3 base = glm::vec3(inst.world * glm::vec4(r.center + glm::normalize(r.axis) * r.aft, 1.0f));
            const glm::vec3 tip  = glm::vec3(inst.world * glm::vec4(r.center + glm::normalize(r.axis) * r.fore, 1.0f));
            const float scale = glm::length(glm::vec3(inst.world[0]));   // uniform model scale
            out.push_back({ base, glm::normalize(tip - base), r.radius * scale,
                            glm::length(tip - base), glm::vec3(0, 1, 0) });
        }
    });
    return out;
}
```

Adapt the filter/loop for whatever you want to see next: iterate a different
per-instance list, feed hardpoint positions, trigger volumes, etc. The only
contract is "hand `render()` world-space cylinders."

## Tuning

- **Occlusion**: `render()` disables `GL_DEPTH_TEST`. For natural occlusion by
  the hull, keep depth test enabled (remove the `glDisable(GL_DEPTH_TEST)` /
  restore pair).
- **Colour**: per-`DebugCylinder` `color`.
- **Resolution / line width**: `kSegments` and `glLineWidth` in the `.cc`.
- **Other shapes**: the mesh is a unit cylinder. For spheres/boxes, add another
  mesh + a `DebugSphere`/`DebugBox` overload following the same pattern.

## History

Added during the impulse-engine glow work (see the `feat/impulse-glow-*`
branch). The impulse-specific wiring was removed after the volume was validated;
this pass is the extracted, generic remainder.
