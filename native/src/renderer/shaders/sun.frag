#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform int       u_corona;   // 0 = body draw, 1 = corona draw

out vec4 frag_color;

// Stars render into the HDR buffer well above LDR-white so they dominate over
// incidental hull brights (windows, running lights). This gives bloom and the
// image-based lens flare real headroom; the resolve tonemap's soft shoulder
// rolls the on-screen disc back toward white, so the sun still reads white, not
// blown out. Eye-calibrated (locked in after live tuning) — rebuild to change.
const float SUN_HDR_BOOST = 5.0;

void main() {
    vec4 tex = texture(u_texture, v_uv);
    if (u_corona == 0) {
        frag_color = vec4(tex.rgb * SUN_HDR_BOOST, 1.0);
    } else {
        // v_uv.y in [0,1]: poles at 0 and 1, equator near 0.5.
        // sin maps to 0 at poles and 1 at equator for atmospheric taper.
        float fade = sin(v_uv.y * 3.14159265);
        frag_color = vec4(tex.rgb * SUN_HDR_BOOST, tex.a * fade * 0.54);
    }
}
