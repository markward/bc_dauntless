#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform vec3  u_color;
uniform float u_opacity;
uniform float u_border;   // nebula boundary alpha (kind 0 only)
uniform vec3  u_center;   // world position — also the nebula's shape seed
uniform int   u_kind;     // 0 nebula, 1 line, 2 star, 3 bracket, 4 star cloud

// Nebula boundary radius at angle `a`, as a fraction of the billboard's half
// size. Two out-of-phase harmonics make an irregular charted region rather
// than a circle. Seeded from the nebula's own world position, so a given
// nebula always has the same silhouette and no two share one.
float nebula_edge(float a) {
    return 0.72 * (1.0
                   + 0.12 * sin(a * 3.0 + u_center.x)
                   + 0.08 * cos(a * 5.0 + u_center.z));
}

void main() {
    if (u_kind == 1) {
        frag_color = vec4(u_color, u_opacity);
        return;
    }

    vec2  d = v_uv * 2.0 - 1.0;
    float r = length(d);

    if (u_kind == 0) {
        // A CHARTED REGION, not a cloud: flat faint interior, diagonal hatch
        // bands, crisp boundary. That construction — rather than opacity
        // alone — is what keeps nebulae from competing with the stars inside
        // them, because the eye reads the edge and ignores the fill.
        float edge = nebula_edge(atan(d.y, d.x));
        // Antialias against the billboard's own pixel scale.
        float aa = fwidth(r) * 1.5;
        if (r > edge + aa) discard;

        float inside = 1.0 - smoothstep(edge - aa, edge + aa, r);

        // Diagonal hatch, clipped to the interior. Period is in billboard
        // space so the banding holds its spacing as the map zooms.
        float band  = step(0.5, fract((d.x + d.y) * 6.0));
        float alpha = u_opacity + band * u_opacity * 0.35;

        // Boundary stroke: a narrow ring just inside the edge.
        float rim = 1.0 - smoothstep(0.0, max(aa, 0.02) * 2.0, abs(r - edge));
        alpha = mix(alpha, u_border, rim);

        frag_color = vec4(u_color, alpha * inside);
        return;
    }

    if (u_kind == 2) {
        // Star: white pinpoint core inside a tinted halo — white at the
        // centre, u_color by 0.4, transparent at the rim. The white core is
        // what makes a star read as a star rather than a coloured dot.
        float core = 1.0 - smoothstep(0.20, 0.30, r);
        float halo = 1.0 - smoothstep(0.0, 1.0, r);
        halo *= halo;
        vec3  rgb   = mix(u_color, vec3(1.0), core);
        float alpha = max(core, halo) * u_opacity;
        if (alpha <= 0.0) discard;
        frag_color = vec4(rgb, alpha);
        return;
    }

    if (u_kind == 4) {
        // Star cloud: three four-pointed stars. Decoration only — never
        // selectable, and deliberately small, so a dense-star region reads as
        // a symbol rather than as a volume competing with the systems.
        const vec2 CENTRES[3] = vec2[3](vec2( 0.00,  0.32),
                                        vec2(-0.36, -0.02),
                                        vec2( 0.32, -0.06));
        const float RADII[3]  = float[3](0.40, 0.25, 0.27);
        float lit = 0.0;
        for (int i = 0; i < 3; ++i) {
            vec2  p  = d - CENTRES[i];
            float pr = length(p);
            if (pr < 1e-5) { lit = 1.0; continue; }
            // Four-pointed star: the boundary pinches to 0.34 of the radius
            // between the points, matching the POC's 8-vertex alternation.
            float a    = atan(p.y, p.x);
            float lobe = mix(0.34, 1.0, pow(abs(cos(2.0 * a)), 0.6));
            lit = max(lit, 1.0 - smoothstep(RADII[i] * lobe * 0.75,
                                            RADII[i] * lobe, pr));
        }
        if (lit <= 0.0) discard;
        frag_color = vec4(u_color, lit * u_opacity);
        return;
    }

    // Bracket: four corner L-shapes. Keep the legs, discard the middle AND
    // the hollow inside each corner.
    //
    // Leg length and leg thickness are SEPARATE knobs. They were not: `arm`
    // sat beside a hardcoded 0.55, and because 1.0 - 0.45 == 0.55 the ||
    // clause was subsumed by the && pair, collapsing the whole gate to
    // `ad.x > 0.55 && ad.y > 0.55` — four filled squares, with `arm` dead.
    // Keep the two independent, or the knob silently stops working again.
    vec2  ad = abs(d);
    float arm   = 0.45;   // leg LENGTH, as a fraction of the marker half-size
    float thick = 0.30;   // leg THICKNESS, same units
    bool corner = (ad.x > 1.0 - thick || ad.y > 1.0 - thick)
               && ad.x > 1.0 - arm && ad.y > 1.0 - arm;
    if (!corner) discard;
    frag_color = vec4(u_color, u_opacity);
}
