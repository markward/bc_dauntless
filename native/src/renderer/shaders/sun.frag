#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform int       u_corona;   // 0 = body draw, 1 = corona draw

out vec4 frag_color;

void main() {
    vec4 tex = texture(u_texture, v_uv);
    if (u_corona == 0) {
        frag_color = vec4(tex.rgb, 1.0);
    } else {
        // v_uv.y in [0,1]: poles at 0 and 1, equator near 0.5.
        // sin maps to 0 at poles and 1 at equator for atmospheric taper.
        float fade = sin(v_uv.y * 3.14159265);
        frag_color = vec4(tex.rgb, tex.a * fade * 0.54);
    }
}
