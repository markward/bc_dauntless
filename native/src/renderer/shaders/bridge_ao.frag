#version 410 core
// Screen-space ambient occlusion for the bridge (BridgeAoPass), from a normal
// + depth pre-pass of the room. Output: occlusion factor in .r, 1 = open,
// applied by bridge.frag to RECEIVED light; the detail kernel's own factor
// in .g and the main kernel's in .b (see the end of main()).
in vec2 v_uv;
out vec4 FragColor;

uniform sampler2D u_depth;      // window depth of the bridge, [0.5,1] (glm ZO through GL)
uniform sampler2D u_normal;     // world-space shading normal from the normal pre-pass
uniform mat4      u_view;
uniform mat4      u_proj;
uniform mat4      u_inv_proj;
uniform vec2      u_viewport;   // pixels
uniform float     u_radius;     // view-space units
uniform float     u_strength;
uniform float     u_bias;       // view-space units
uniform float     u_bias_dist;  // bias per view-space unit of distance
uniform float     u_bias_facing;// 0 = distance bias in full, 1 = scaled by (1 - N.V)
uniform float     u_min_len;    // shortest main-kernel sample, fraction of the radius
uniform int       u_samples;    // kernel samples, clamped to 4..64
// Small-scale detail kernel for shallow steps (0 samples = off).
uniform int       u_detail_samples;
uniform float     u_detail_radius;
uniform float     u_detail_strength;
uniform float     u_detail_bias;

vec3 view_pos(vec2 uv) {
    float win = texture(u_depth, uv).r;
    vec4 clip = vec4(uv * 2.0 - 1.0, (win - 0.5) * 2.0, 1.0);
    vec4 v = u_inv_proj * clip;
    return v.xyz / v.w;
}

// One kernel sample `k` (tangent space, unit radius): 1 if the scene covers
// it, weighted by how near the occluder is in depth.
float occluded(vec3 P, mat3 TBN, vec3 k, float radius, float bias) {
    vec3 S = P + TBN * (k * radius);
    vec4 clip = u_proj * vec4(S, 1.0);
    vec2 suv = (clip.xy / clip.w) * 0.5 + 0.5;
    if (suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) return 0.0;
    float scene_z = view_pos(suv).z;
    // Scene surface closer to the camera than the sample = sample is inside
    // geometry. Only occluders within about the radius count: one far in
    // front of us (an officer seen against the floor behind) is not
    // occluding this point, and a wider falloff draws a dark halo round
    // every silhouette.
    float range = 1.0 - smoothstep(0.5 * radius, 1.5 * radius, abs(P.z - scene_z));
    return (scene_z >= S.z + bias ? 1.0 : 0.0) * range;
}

void main() {
    float win = texture(u_depth, v_uv).r;
    if (win >= 1.0) { FragColor = vec4(1.0); return; }   // nothing drawn here
    vec3 P = view_pos(v_uv);
    // The lighting's own smooth normal (world space) into view space. A
    // derivative normal here is flat per triangle and shades every facet of a
    // low-poly face differently, which reads as polygons however smooth the
    // lighting normal is.
    vec3 N = mat3(u_view) * texture(u_normal, v_uv).xyz;
    if (dot(N, N) < 1e-6) N = cross(dFdx(P), dFdy(P));   // fallback: nothing written
    N = normalize(N);
    if (dot(N, -P) < 0.0) N = -N;

    // Per-pixel rotation of the kernel about N, from a 4x4 TILE of 16 evenly
    // spaced angles (Bayer order). bridge.frag box-filters 4x4 when it reads
    // us, and any 4x4 window holds each angle exactly once, so the filter
    // cancels the pattern completely.
    const float BAYER4[16] = float[](0.0, 8.0, 2.0, 10.0, 12.0, 4.0, 14.0, 6.0,
                                     3.0, 11.0, 1.0, 9.0, 15.0, 7.0, 13.0, 5.0);
    ivec2 cell = ivec2(gl_FragCoord.xy) & 3;
    float ang = 6.2831853 * (BAYER4[cell.y * 4 + cell.x] + 0.5) / 16.0;
    vec3 r = vec3(cos(ang), sin(ang), 0.0);
    vec3 T = normalize(r - N * dot(r, N));
    vec3 B = cross(N, T);
    mat3 TBN = mat3(T, B, N);

    // Bias grows with distance: a grazing floor far from the eye spans many
    // depth units per pixel and would otherwise occlude itself. A surface
    // seen head-on has no such spread, so u_bias_facing can scale the
    // distance term by how grazing the view is.
    float grazing = 1.0 - clamp(dot(N, normalize(-P)), 0.0, 1.0);
    float dist_bias = u_bias_dist * abs(P.z);
    float bias = u_bias + dist_bias * mix(1.0, grazing, u_bias_facing);
    float occl = 0.0;
    int n = clamp(u_samples, 4, 64);
    for (int i = 0; i < n; ++i) {
        // Golden-angle spiral over a cosine-weighted hemisphere, lengths
        // biased towards the centre (near occluders matter most), z kept off
        // the tangent plane so flat floor never occludes itself.
        float u = (float(i) + 0.5) / float(n);
        float phi = float(i) * 2.39996323;
        float z = max(sqrt(1.0 - u), 0.2);
        float rxy = sqrt(max(0.0, 1.0 - z * z));
        float len = mix(u_min_len, 1.0, u * u);
        vec3 k = vec3(cos(phi) * rxy, sin(phi) * rxy, z) * len;
        occl += occluded(P, TBN, k, u_radius, bias);
    }
    float ao = 1.0 - u_strength * (occl / float(n));
    float ao_main = ao;

    // Detail kernel. The main kernel ties length to elevation (its short
    // samples point nearly straight up), so its lowest sample sits
    // ~0.077 x radius off the surface and a step shallower than that can
    // never occlude. Here length runs on its own sequence, so short samples
    // also lean sideways towards a nearby step.
    int nd = clamp(u_detail_samples, 0, 32);
    float dao = 1.0;
    if (nd > 0) {
        float dbias = u_detail_bias + dist_bias * grazing;
        float docc = 0.0;
        for (int i = 0; i < nd; ++i) {
            float u = (float(i) + 0.5) / float(nd);
            float phi = float(i) * 2.39996323 + 1.0;
            float z = max(sqrt(1.0 - u), 0.2);
            float rxy = sqrt(max(0.0, 1.0 - z * z));
            float len = mix(0.15, 1.0, fract(0.5 + float(i) * 0.61803399));
            vec3 k = vec3(cos(phi) * rxy, sin(phi) * rxy, z) * len;
            docc += occluded(P, TBN, k, u_detail_radius, dbias);
        }
        // Clamped: strengths above 1 drive a factor negative, and two
        // negatives would multiply back to light.
        dao = max(1.0 - u_detail_strength * (docc / float(nd)), 0.0);
        ao = max(ao, 0.0) * dao;
    }
    // .r = the whole AO (received light); .g = the detail factor alone and
    // .b = the main kernel alone, so bridge.frag can move the detail factor
    // onto direct light (u_ao_direct) or past the diffuse ceiling (u_ao_final).
    FragColor = vec4(ao, dao, ao_main, 1.0);
}
