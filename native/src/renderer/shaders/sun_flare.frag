#version 330 core

// BC SunEffect particle: samples one cell from the SunFlares*.tga
// sprite atlas (8x8 grid of distinct plasma puffs) and additively
// blends it onto the sun's surface with an alpha envelope so each
// particle fades in then out over its lifetime.

in vec2 v_uv;

uniform sampler2D u_texture;
uniform int       u_frame;       // which cell of the sprite sheet (0..N-1)
uniform int       u_grid_size;   // sprite sheet is u_grid_size × u_grid_size cells
uniform float     u_alpha;       // 0..1 lifetime envelope; multiplied into alpha

out vec4 frag_color;

void main() {
    int total = u_grid_size * u_grid_size;
    int frame = u_frame;
    if (frame < 0)      frame = 0;
    if (frame >= total) frame = total - 1;

    int   col  = frame % u_grid_size;
    int   row  = frame / u_grid_size;
    float cell = 1.0 / float(u_grid_size);
    vec2  uv   = (vec2(float(col), float(row)) + v_uv) * cell;

    vec4  tex = texture(u_texture, uv);
    float a   = tex.a * u_alpha;
    // RGB pre-multiplied for additive blend.
    frag_color = vec4(tex.rgb * a, a);
}
