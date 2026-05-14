#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform vec4      u_tint;
uniform float     u_alpha;                // per-layer alpha multiplier

void main() {
    vec4 t = texture(u_texture, v_uv);
    frag_color = t * u_tint;
    frag_color.a *= u_alpha;
}
