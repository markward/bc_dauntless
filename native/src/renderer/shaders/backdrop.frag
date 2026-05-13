#version 330 core

in vec3 v_pos_local;
in vec2 v_uv;

uniform sampler2D u_texture;
uniform vec2  u_tile;
uniform vec2  u_span;
uniform int   u_use_alpha;   // 0 = opaque (Star), 1 = blended (Backdrop)

out vec4 frag_color;

void main() {
    // The textured patch is centred on the sphere mesh vertex
    // (cos_t*cos_p, cos_t*sin_p, sin_t) at UV = (0.25, 0.5), which lives
    // at local position (0, 1, 0). u_world_rotation columns are
    // (right, forward, up) from AlignToVectors, so a_pos.y = 1 carries
    // that point onto kForward — the texture centre ends up where the
    // script asked the backdrop to point. Anchoring at (0, 0) instead
    // (the old behaviour) put the patch at v = south pole, where every
    // mesh vertex collapses to a single point and the texture got
    // smeared into a triangular fan-out — visible on E1M1 as wedge
    // artefacts in the treknebula.
    // BC's H/VSpan semantics aren't pinned to instrumented data yet — see
    // project_backdrop_span_semantics memory. Treating span as a *radius*
    // in UV space (rather than the full diameter) gives an ~54° patch on
    // E1M1 instead of ~109°, which matches "compact nebula in the sky"
    // expectation. Half-extent in each axis = u_span.{x,y} * 0.5, so the
    // discard threshold is `abs(offset) > span * 0.25` and the UV remap
    // doubles the offset.
    vec2 offset = v_uv - vec2(0.25, 0.5);
    if (abs(offset.x) > u_span.x * 0.25 || abs(offset.y) > u_span.y * 0.25) {
        if (u_use_alpha == 1) discard;
    }
    // Flip U: from inside the sphere looking at kForward, increasing
    // mesh longitude rotates toward -kRight, so we invert it to get the
    // texture's +U pointing to the viewer's right.
    vec2 uv = vec2(0.5 - 2.0 * offset.x / u_span.x,
                   0.5 + 2.0 * offset.y / u_span.y) * u_tile;
    vec4 tex = texture(u_texture, uv);
    if (u_use_alpha == 1) {
        frag_color = vec4(tex.rgb, tex.a);
    } else {
        frag_color = vec4(tex.rgb, 1.0);
    }
}
