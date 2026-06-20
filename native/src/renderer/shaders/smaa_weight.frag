uniform sampler2D u_edges_tex;
uniform sampler2D u_area_tex;
uniform sampler2D u_search_tex;
in vec2 v_uv;
in vec2 v_pixcoord;
in vec4 v_offset[3];
out vec4 frag;
void main() {
    frag = SMAABlendingWeightCalculationPS(
        v_uv, v_pixcoord, v_offset,
        u_edges_tex, u_area_tex, u_search_tex, vec4(0.0));
}
