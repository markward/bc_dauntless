#version 410 core
// Screen-space ambient occlusion for the bridge (BridgeAoPass), from a normal
// + depth pre-pass of the room. Output: occlusion factor in .r, 1 = open,
// applied by bridge.frag to RECEIVED light only.
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
uniform int       u_samples;    // kernel samples, clamped to 4..64

vec3 view_pos(vec2 uv) {
    float win = texture(u_depth, uv).r;
    vec4 clip = vec4(uv * 2.0 - 1.0, (win - 0.5) * 2.0, 1.0);
    vec4 v = u_inv_proj * clip;
    return v.xyz / v.w;
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
    // depth units per pixel and would otherwise occlude itself.
    float bias = u_bias + 0.01 * abs(P.z);
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
        float len = mix(0.1, 1.0, u * u);
        vec3 k = vec3(cos(phi) * rxy, sin(phi) * rxy, z) * len;
        vec3 S = P + TBN * (k * u_radius);
        vec4 clip = u_proj * vec4(S, 1.0);
        vec2 suv = (clip.xy / clip.w) * 0.5 + 0.5;
        if (suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) continue;
        float scene_z = view_pos(suv).z;
        // Scene surface closer to the camera than the sample = sample is inside
        // geometry. Only occluders within about the radius count: one far in
        // front of us (an officer seen against the floor behind) is not
        // occluding this point, and a wider falloff draws a dark halo round
        // every silhouette.
        float range = 1.0 - smoothstep(0.5 * u_radius, 1.5 * u_radius, abs(P.z - scene_z));
        occl += (scene_z >= S.z + bias ? 1.0 : 0.0) * range;
    }
    float ao = 1.0 - u_strength * (occl / float(n));
    FragColor = vec4(ao, ao, ao, 1.0);
}
