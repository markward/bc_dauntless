#version 330 core

in vec3 v_pos_local;
in vec2 v_uv;

uniform sampler2D u_texture;
uniform vec2  u_tile;
uniform vec2  u_span;
uniform int   u_use_alpha;   // 0 = opaque (Star), 1 = blended (Backdrop)

out vec4 frag_color;

void main() {
    if (v_uv.x > u_span.x || v_uv.y > u_span.y) {
        if (u_use_alpha == 1) discard;
    }
    vec2 uv = vec2(v_uv.x * u_tile.x, v_uv.y * u_tile.y);
    vec4 tex = texture(u_texture, uv);
    if (u_use_alpha == 1) {
        frag_color = vec4(tex.rgb, tex.a);
    } else {
        frag_color = vec4(tex.rgb, 1.0);
    }
}
