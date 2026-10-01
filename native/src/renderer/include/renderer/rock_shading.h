// native/src/renderer/include/renderer/rock_shading.h
// The per-frame uniform block every rock program linked with opaque.frag
// shares (minor rocks, far-tier impostors): camera, ambient, directional
// lights, every ship-only feature off, the sun shadow on unit 5, the NaN
// debug flag, rim, and identity u_model / u_ship_world_inv. Lifted verbatim
// out of MinorPass::render (minor-rocks spec §2; far-tier spec §3), so a rock
// drawn by either pass is lit exactly as draw_model lights a major.
#pragma once

namespace scenegraph { struct Camera; }

namespace renderer {

class Shader;
struct Lighting;

// Leaves `s` in use and texture unit 0 active. `white` / `black` are 1x1
// textures owned by the caller (`black` is bound to unit 3, the damage decal).
// `rim_strength` is the FINAL u_rim_strength (see MinorPass::render).
void configure_rock_program(Shader& s, const scenegraph::Camera& cam, const Lighting& lighting,
                            float ambient_scale, float rim_strength, unsigned white,
                            unsigned black);

}  // namespace renderer
