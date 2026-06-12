#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float     u_alpha;
uniform vec4      u_tint;
uniform vec2      u_atlas_grid;   // (cols, rows); (1,1) or unset => whole texture
uniform vec2      u_atlas_cell;   // (frame_col, variant_row) within the grid

void main() {
    // Remap the unit-quad UV into the active sprite-sheet cell. With an unset
    // (zero) or 1x1 grid this is identity (uv == v_uv), so non-atlas emitters
    // (hit VFX, plumes) are unaffected.
    vec2 grid = max(u_atlas_grid, vec2(1.0));
    vec2 uv   = (u_atlas_cell + v_uv) / grid;
    vec4 t = texture(u_texture, uv);
    frag_color = t * u_tint * vec4(1.0, 1.0, 1.0, u_alpha);
}
