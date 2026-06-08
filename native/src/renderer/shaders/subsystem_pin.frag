#version 330 core
in vec2 v_uv;
uniform sampler2D u_glyph;     // black ink on transparent alpha
out vec4 frag;
void main() {
    vec2 c = v_uv - vec2(0.5);
    if (length(c) > 0.5) discard;            // circular pin
    float ink = texture(u_glyph, v_uv).a;    // glyph coverage
    vec3 col = mix(vec3(1.0), vec3(0.0), ink);  // white disc, black glyph
    frag = vec4(col, 1.0);
}
