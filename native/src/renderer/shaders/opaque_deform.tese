#version 410 core
layout(triangles, equal_spacing, ccw) in;  // At tess level 1 the single emitted triangle preserves the patch v0->v1->v2 order (matches the opaque GL_TRIANGLES path, which renders correctly under glFrontFace(GL_CW)). The ccw vs cw qualifier only changes sub-triangle winding at level>1; that is validated with a front-facing test when adaptive tessellation lands.

in  vec3  tcp_pos[];
in  vec3  tcp_normal[];
in  vec2  tcp_uv[];
in  float tcp_crush[];   // displacement weight; consumed here (Task 5)

uniform mat4 u_model;          // instance_world * node_world (local -> world)
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_ship_world;     // instance_world (body -> world)
uniform mat4 u_ship_world_inv; // inverse(instance_world) (world -> body)

const int MAX_CRATERS = 24;  // must match scenegraph::HullCraterField::kMaxCraters (C++)
uniform int  u_crater_count;
uniform vec4 u_crater_a[MAX_CRATERS];  // point_body.xyz, depth
uniform vec4 u_crater_b[MAX_CRATERS];  // impact_dir_body.xyz (unit length), radius

out vec3  v_normal_ws;
out vec2  v_uv;
out vec3  v_position_ws;
out float v_deform_depth;   // |displacement| at this vertex (model units); FS thresholds dent vs gouge

vec3 bary3(vec3 a, vec3 b, vec3 c) {
    return gl_TessCoord.x * a + gl_TessCoord.y * b + gl_TessCoord.z * c;
}

// Body-frame displacement at a body-space point, weighted by per-vertex
// crushability. Each crater pushes along its impact direction; contribution
// falls off smoothly to zero at the crater radius.
vec3 crater_displacement(vec3 p_body, float crush) {
    vec3 disp = vec3(0.0);
    for (int i = 0; i < u_crater_count; ++i) {
        vec3  c_pt   = u_crater_a[i].xyz;
        float depth  = u_crater_a[i].w;
        vec3  dir    = u_crater_b[i].xyz;
        float radius = u_crater_b[i].w;
        if (radius <= 0.0) continue;
        float r = length(p_body - c_pt) / radius;   // 0 center, 1 edge
        if (r >= 1.0) continue;
        float fall = 1.0 - r * r;
        fall *= fall;                                // smooth radial falloff (1 - r^2)^2
        disp += depth * fall * crush * dir;
    }
    return disp;
}

// Displaced body-frame position for a given barycentric coord. Re-evaluates
// the patch interpolation + crater displacement at an arbitrary (u,v,w).
vec3 displaced_body_at(vec3 bc) {
    vec3 lp = bc.x * tcp_pos[0] + bc.y * tcp_pos[1] + bc.z * tcp_pos[2];
    float cr = bc.x * tcp_crush[0] + bc.y * tcp_crush[1] + bc.z * tcp_crush[2];
    vec3 wp = (u_model * vec4(lp, 1.0)).xyz;
    vec3 bp = (u_ship_world_inv * vec4(wp, 1.0)).xyz;
    return bp + crater_displacement(bp, cr);
}

void main() {
    vec3 bc = gl_TessCoord;
    vec2 uv = bc.x * tcp_uv[0] + bc.y * tcp_uv[1] + bc.z * tcp_uv[2];

    vec3 db = displaced_body_at(bc);

    // Original (undisplaced) surface normal in body frame. Used for the
    // sign-fix below, and as the fallback when the finite-difference cross
    // degenerates at a patch corner.
    vec3 orig_local_n = normalize(bc.x * tcp_normal[0] + bc.y * tcp_normal[1]
                                  + bc.z * tcp_normal[2]);
    vec3 orig_n_body = normalize(mat3(u_ship_world_inv) * (mat3(u_model) * orig_local_n));

    // Finite-difference the displaced surface for the post-dent normal. The two
    // offsets trade eps between barycentric coords so they stay inside the patch:
    //   bc_u moves along the 0->1 edge (x up, y down)
    //   bc_v moves along the 0->2 edge (x up, z down)
    const float eps = 0.01;  // ~1/10 of a tess-level-8 step: small vs patch, large vs float precision
    vec3 bc_u = clamp(bc + vec3( eps, -eps, 0.0), 0.0, 1.0);
    vec3 bc_v = clamp(bc + vec3( eps, 0.0, -eps), 0.0, 1.0);
    vec3 du = displaced_body_at(bc_u) - db;
    vec3 dv = displaced_body_at(bc_v) - db;

    // At a patch corner the clamped offsets collapse (du/dv ~ 0); fall back to
    // the undisplaced normal instead of normalize(vec3(0)) -> NaN.
    vec3 cx = cross(du, dv);
    vec3 n_body;
    if (dot(cx, cx) < 1e-12) {
        n_body = orig_n_body;
    } else {
        n_body = normalize(cx);
        if (dot(n_body, orig_n_body) < 0.0) n_body = -n_body;  // resolve cross sign
    }

    vec3 displaced_world = (u_ship_world * vec4(db, 1.0)).xyz;
    vec3 world_n = normalize(mat3(u_ship_world) * n_body);

    // Undisplaced body position for the displacement magnitude the FS uses to
    // pick dent vs gouge (db is the displaced body position).
    vec3 lp0 = bc.x * tcp_pos[0] + bc.y * tcp_pos[1] + bc.z * tcp_pos[2];
    vec3 wp0 = (u_model * vec4(lp0, 1.0)).xyz;
    vec3 bp0 = (u_ship_world_inv * vec4(wp0, 1.0)).xyz;
    v_deform_depth = length(db - bp0);

    v_position_ws = displaced_world;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(displaced_world, 1.0);
}
