uniform sampler2D u_color_tex;
uniform sampler2D u_blend_tex;
in vec2 v_uv;
in vec4 v_offset;
out vec4 frag;
void main() {
    frag = SMAANeighborhoodBlendingPS(v_uv, v_offset, u_color_tex, u_blend_tex);
}
