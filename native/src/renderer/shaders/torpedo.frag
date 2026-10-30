#version 410 core
in  vec2 v_uv;
flat in vec4  v_tint;
flat in float v_alpha;                    // per-layer alpha multiplier
out vec4 frag_color;

uniform sampler2D u_texture;

void main() {
    vec4 t = texture(u_texture, v_uv);
    frag_color = t * v_tint;
    frag_color.a *= v_alpha;
}
