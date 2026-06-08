#version 330 core
in vec2 v_uv;
uniform sampler2D u_glyph;     // black ink on transparent alpha
out vec4 frag;

// Fraction of the pin disc the glyph occupies (the rest is white margin).
// Smaller = the low-res 16x16 glyph texture is magnified less per on-screen
// pixel, so it reads sharper. Tune to taste.
const float GLYPH_SCALE = 0.6;

void main() {
    vec2 c = v_uv - vec2(0.5);
    if (length(c) > 0.5) discard;            // circular pin
    // Sample the glyph over the inner GLYPH_SCALE box; outside it = white.
    vec2 g = c / GLYPH_SCALE + vec2(0.5);
    float ink = 0.0;
    if (all(greaterThanEqual(g, vec2(0.0))) && all(lessThanEqual(g, vec2(1.0))))
        ink = texture(u_glyph, g).a;         // glyph coverage
    vec3 col = mix(vec3(1.0), vec3(0.0), ink);  // white disc, black glyph
    frag = vec4(col, 1.0);
}
