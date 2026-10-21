#version 410 core
// Depth-only shadow caster, PART-MASK variant (see shadow_parts.vert). A
// fragment on a part the colour draw hides is discarded, by the SAME rule as
// opaque.frag's PLATING main: bit i of u_part_hidden_mask hides part i (a
// parent's lost parts); a non-zero u_part_show_mask (a chunk) hides every
// fragment whose part's bit is not set. With no parts loaded
// (u_part_count == 0) nothing is hidden, as in opaque.frag.
// One discard, no early return (the opaque.frag rule on this driver).
in vec3 v_p_rest;

const int  MAX_PARTS    = 12;
uniform int  u_part_count;
uniform int  u_part_hidden_mask;
uniform int  u_part_show_mask;
uniform vec4 u_part_a[MAX_PARTS];        // centre.xyz, kind (0 box, 1 disc, 2 cylinder)
uniform vec4 u_part_b[MAX_PARTS];        // axis0.xyz, half0
uniform vec4 u_part_c[MAX_PARTS];        // axis1.xyz, half1
uniform vec4 u_part_d[MAX_PARTS];        // half2, _, _, _

// TWIN of opaque.frag's plating_part (and its MAX_PARTS): a copy, because the
// shader sources are embedded whole. Change both together --
// ShadowPartsShader.PlatingPartIsTheTwinOfOpaque (renderer_tests) fails the
// moment the two texts differ.
int plating_part(vec3 p) {
    int best = -1;
    float bs = 1e9;
    for (int i = 0; i < MAX_PARTS; ++i) {
        if (i >= u_part_count) break;
        vec3 off = p - u_part_a[i].xyz;
        vec3 A0 = u_part_b[i].xyz, A1 = u_part_c[i].xyz, A2 = cross(A0, A1);
        float h0 = max(u_part_b[i].w, 1e-3), h1 = max(u_part_c[i].w, 1e-3), h2 = max(u_part_d[i].x, 1e-3);
        float k = u_part_a[i].w, sc;
        if (k > 0.5 && k < 1.5) {
            float h = dot(off, A0);
            sc = max(abs(h) / (1.8 * h0), length(off - A0 * h) / max(h1, h2));
        } else if (k > 1.5) {
            float a = dot(off, A0);
            sc = max(abs(a) / h0, length(off - A0 * a) / max(h1, h2));
        } else {
            sc = max(max(abs(dot(off, A0)) / h0, abs(dot(off, A1)) / h1), abs(dot(off, A2)) / h2);
        }
        if (sc < bs) { bs = sc; best = i; }
    }
    return best;
}

void main() {
    int hp = plating_part(v_p_rest);
    bool hidden = (u_part_show_mask != 0 &&
                   (hp < 0 || ((u_part_show_mask >> hp) & 1) == 0)) ||
                  (hp >= 0 && hp < 32 && ((u_part_hidden_mask >> hp) & 1) != 0);
    if (u_part_count > 0 && hidden) discard;
}
