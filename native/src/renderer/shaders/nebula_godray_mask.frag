#version 410 core
// Half-res SOURCE image for the god-ray march (nebula_godray.frag): the HDR
// colour averaged over this half-res pixel's 2x2 full-res footprint, zeroed
// wherever any of those four texels is nearer than the light -- an occluder,
// e.g. a hull in front of the star. It darkens the shafts behind it but its
// own lit windows and nacelle glows are never smeared along them. Built once
// per light, so the 48-step march reads one small texture and never depth.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;     // full-res HDR colour (resolved, single-sample)
uniform sampler2D u_depth;     // full-res HDR depth
uniform float u_source_depth;  // window depth at/after which a texel is SOURCE;
                               // 1.0 = sky only (a light with no body)

void main() {
    // A half-res pixel centre sits on the corner shared by its four full-res
    // texels: one bilinear fetch is their mean, one gather their depths. The
    // whole footprint must be source, or a 1-px rim of hull glow leaks in.
    vec3 c = texture(u_scene, v_uv).rgb;
    vec4 d4 = textureGather(u_depth, v_uv);
    float src = step(u_source_depth, min(min(d4.x, d4.y), min(d4.z, d4.w)));
    frag = vec4(c * src, 1.0);
}
