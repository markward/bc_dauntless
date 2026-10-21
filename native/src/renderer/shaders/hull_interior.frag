#version 410 core

// Hull interior behind a plating cut (SPIKE, damage redesign; plan
// 2026-10-20-layered-damage-hull-interior, Task 3).
//
// HullInteriorPass draws the hull mesh through hull_interior.vert under the stencil
// value FrameSubmitter::submit_plating_interior stamped where THIS hull's
// plating is cut, so every fragment here sits on a cut front face. The view
// ray continues from it into the hull and walks a body-frame lattice of decks
// (planes z = k), longitudinal walls (x = k) and transverse bulkheads (y = k),
// plane to plane. At each crossing:
//   (a) outside the original fill (or its box): the ray has LEFT the ship.
//       Blown through there (interior wear past deck break) -> discard; else
//       the far wall: the inside of the pressure hull, lit by the room.
//   (b) a plate the interior wear has broken -> keep walking;
//   (c) otherwise shade that floor, ceiling or wall, lit by its room's state.
//
// The walk (ih_hash, ih_rand, the wall chance, ih_room_light and the DDA of
// ih_shade) is ported from spike/breach-interior-mapping's breach.frag with
// the constants Mark tuned live on 2026-10-20 (findings:
// docs/engine/breach-interior-mapping-spike-findings.md). What changed: the
// blown-plate test and the torn edge read the plating damage list instead of
// the carve field (the char band is the last wear unit short of deck break,
// on the same noised wear as the blown test, so it follows the ragged tear);
// the left-the-ship case shows the far wall unless the hull is blown through;
// fresh-tear heat comes from the breach events (u_rim_*), not the records.
//
// Look pass 2026-10-21 (Mark: rooms "too uniform", "too many illuminated
// rooms ... we need rooms to look destroyed"): walls come from ZONES
// (cabins, corridors, machinery, open bays) instead of one global chance,
// rooms hold a block of contents, a room loses its power with the damage
// around it, surfaces soot with wear, and room-by-room variety fades out
// where a room is only a few pixels across.
//
// Rock mode (phase 3, Task 2; u_interior_rock != 0): a rock has no rooms.
// The ray marches the damage field from the cut to the crater wall (where
// the wear falls back under breach, the rule opaque.frag's rock cut uses),
// which is shaded with the rock's own base texture, as breach.frag's old
// rock crater was, under the scene's ambient and directional lights.
//
// Everything is the REST frame of the drawn mesh's node, in model units: the
// body frame the model has at rest. The records and the fill are rest-frame
// data; hull_interior.vert puts v_body_pos there and main() the camera
// (layered damage phase 4 §2.1). For an unarticulated hull it IS the body
// frame.

in vec3 v_body_pos;
in vec3 v_body_normal;   // hull_interior.vert writes it; unused here

uniform vec3 u_camera_pos_body;   // POSED body frame (one per draw)
// This mesh's node: posed body -> rest body (set per mesh, identity when not
// articulated; the same uniform hull_interior.vert reads). Rigid.
uniform mat4 u_node_rest_fix;

// Original fill (HullFillCache), GL_R8 on unit 0. u_fill_ok 0 = no fill volume:
// rooms still draw, with no left-the-ship test.
uniform sampler3D u_fill;
uniform vec3      u_fill_origin;   // body-frame min corner
uniform vec3      u_fill_cell;     // cell size per axis
uniform ivec3     u_fill_dims;     // nx, ny, nz
uniform float     u_fill_backing;  // HullFillCache::kBackingIsovalue / 255
uniform int       u_fill_ok;

// The plating damage list (renderer/plating_damage.h).
const int MAX_DMG = 64;
uniform int  u_dmg_count;
uniform vec4 u_dmg_a[MAX_DMG];     // centre.xyz, reach
uniform vec4 u_dmg_b[MAX_DMG];     // normal.xyz, wear
uniform vec4 u_dmg_c[MAX_DMG];     // kind, 0, 0, 0
// The deck-break subset (plating::deck_break_subset): indices into u_dmg_*,
// ascending, of the only records that can break a plate. The blown tests
// read deck_break_wear; shading reads interior_wear (every record).
uniform int  u_db_count;
uniform int  u_db_idx[MAX_DMG];

// Molten rims on fresh tears (renderer::plating::RimList, the same upload as
// opaque.frag's u_rim_*): REST frame of the drawn meshes, model units.
//   a = centre.xyz, radius      b = age (s), life (kRimLife), 0, 0
const int MAX_RIMS = 4;
uniform int  u_rim_count;
uniform vec4 u_rim_a[MAX_RIMS];
uniform vec4 u_rim_b[MAX_RIMS];

// Plating params: 17 inner hull brightness, 19 tear noise, 24 deck break wear.
uniform float u_plating[32];
uniform vec3  u_ambient_light;     // lighting.ambient x ambient_scale
uniform float u_time;              // game clock, seconds (flicker / pulse)

// Rock mode: 0 ship (rooms), 1 rock with its base texture u_rock_tex (unit
// 1, always bound, 0 when unused), 2 rock with no texture (flat colour).
uniform int       u_interior_rock;
uniform sampler2D u_rock_tex;
// Scene lighting for the crater wall (HullInteriorPass uploads it).
// u_ship_world is used only to put the wall normal in the lights' frame.
const int MAX_DIR_LIGHTS = 4;
uniform mat4  u_ship_world;        // instance body -> world
uniform vec3  u_ambient_dir_ws;
uniform float u_ambient_gradient;
uniform int   u_dir_light_count;
uniform vec3  u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // toward the light
uniform vec3  u_dir_light_color[MAX_DIR_LIGHTS];

out vec4 frag_color;

// Copied from opaque.frag (its plating layer's pressure hull).
const vec3 INNER_HULL = vec3(0.42, 0.41, 0.40);

// Room lattice pitch, MODEL units (1 mu = 1.75 m): beam-wise room width,
// keel-wise room length, deck pitch. Live-tuned 2026-10-20 (first cut
// 9 x 13 x 4 read ~1.5x too big).
const vec3  kRoomSize          = vec3(6.0, 8.67, 2.67);
// Smaller rooms need more crossings for the same reach.
const int   kInteriorMaxSteps  = 24;
// Rooms come in ZONES (blocks of rooms, beam x keel x decks) that share a
// layout: cramped cabins, fore-aft corridors, machinery spaces, open bays
// two or three decks tall. Live look feedback 2026-10-21: one uniform grid
// "doesn't give the impression of a starship".
const vec3  kZoneRooms         = vec3(3.0, 4.0, 3.0);
// Distance (model units) over which the interior fades to black.
const float kInteriorFogDist   = 90.0;
const float kTornNoiseFreq     = 0.6;   // cycles per model unit
// Unlit (vented, power gone) room: a faint spill so shapes still read.
const vec3  kDarkRoom          = vec3(0.030, 0.032, 0.036);

// 0..1: how much room-by-room detail this pixel can resolve. Far away a room
// is a few pixels, and per-room light reads as a mosaic of lit windows; the
// variety fades to the dark average there (set once in main).
float g_detail = 1.0;
// Screen derivatives of the cut point, taken in main in uniform control flow:
// the crater's texture fetches (inside the march's non-uniform flow) pass
// them as explicit gradients.
vec3 g_dpdx = vec3(0.0), g_dpdy = vec3(0.0);

// Blackbody-ish ramp keyed on heat 0..1. Copied from the old breach.frag.
vec3 blackbody(float heat) {
    vec3 cold  = vec3(0.0);
    vec3 red   = vec3(0.59, 0.10, 0.02);
    vec3 org   = vec3(1.0,  0.45, 0.08);
    vec3 white = vec3(1.0,  0.92, 0.72);
    vec3 lo  = mix(cold, red,   smoothstep(0.0,  0.35, heat));
    vec3 mid = mix(lo,   org,   smoothstep(0.35, 0.7,  heat));
    return     mix(mid,  white, smoothstep(0.7,  1.0,  heat));
}

// Value noise, [0,1]. Copied from the old breach.frag.
float vh3(vec3 p){ return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453123); }
float vnoise3(vec3 p){
    vec3 i = floor(p), f = fract(p);
    vec3 u = f*f*(3.0-2.0*f);
    float n000=vh3(i), n100=vh3(i+vec3(1,0,0)), n010=vh3(i+vec3(0,1,0)), n110=vh3(i+vec3(1,1,0));
    float n001=vh3(i+vec3(0,0,1)), n101=vh3(i+vec3(1,0,1)), n011=vh3(i+vec3(0,1,1)), n111=vh3(i+vec3(1,1,1));
    float nx00=mix(n000,n100,u.x), nx10=mix(n010,n110,u.x), nx01=mix(n001,n101,u.x), nx11=mix(n011,n111,u.x);
    return mix(mix(nx00,nx10,u.y), mix(nx01,nx11,u.y), u.z);
}

uint ih_hash(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return v.x ^ v.y ^ v.z;
}
float ih_rand(ivec3 c, uint salt) {
    return float(ih_hash(uvec3(c) + uvec3(salt, salt * 7u, salt * 13u)) & 0xFFFFFFu)
           / 16777215.0;
}

// Zone of a lattice key: 0 cabins, 1 corridors, 2 machinery, 3 open bay.
int ih_zone(ivec3 key) {
    float r = ih_rand(ivec3(floor(vec3(key) / kZoneRooms)), 11u);
    if (r < 0.40) return 0;
    if (r < 0.65) return 1;
    if (r < 0.85) return 2;
    return 3;
}

// Does the plane on `axis` at index `plane` exist for the segment the ray
// crosses in `cell`? Keyed by the plane itself (key[axis] = plane), so a wall
// looks the same from both sides, zone boundaries included.
bool ih_plane_exists(int axis, int plane, ivec3 cell) {
    ivec3 key = cell;
    key[axis] = plane;
    int zone = ih_zone(key);
    if (axis == 2) {                         // decks
        if (zone == 3) return ((plane % 3) + 3) % 3 == 0;   // bay: 3 decks tall
        return true;
    }
    float chance = zone == 0 ? (axis == 0 ? 0.80 : 0.75)   // cabins: small rooms
                 : zone == 1 ? (axis == 0 ? 0.95 : 0.12)   // long fore-aft corridors
                 : zone == 2 ? (axis == 0 ? 0.45 : 0.40)   // machinery spaces
                 :              0.06;                      // open bay
    return ih_rand(key, uint(axis + 1)) < chance;
}

// Interior wear at p: every listed record, no facing weight (inside the
// ship every record counts).
float interior_wear(vec3 p) {
    float w = 0.0;
    for (int i = 0; i < u_dmg_count; ++i) {
        float R = u_dmg_a[i].w;
        if (R <= 0.0) continue;
        float r = length(p - u_dmg_a[i].xyz) / R;
        if (r >= 1.0) continue;
        float f = 1.0 - r * r;
        w += u_dmg_b[i].w * f * f;
    }
    return w;
}

// interior_wear over the deck-break subset only. Wherever the point could be
// blown it equals interior_wear bit for bit (the same records, summed in the
// same order); elsewhere both stay below the blown threshold.
float deck_break_wear(vec3 p) {
    float w = 0.0;
    for (int k = 0; k < u_db_count; ++k) {
        int i = u_db_idx[k];
        float R = u_dmg_a[i].w;
        if (R <= 0.0) continue;
        float r = length(p - u_dmg_a[i].xyz) / R;
        if (r >= 1.0) continue;
        float f = 1.0 - r * r;
        w += u_dmg_b[i].w * f * f;
    }
    return w;
}

// The room's light: colour x intensity, animated. `fire` (0..1) lets the
// caller bias the light toward the floor. A room open to space has lost its
// power: the nearer the damage (room-centre wear / deck break), the fewer
// lit rooms, and the fires sit in the band short of the destroyed core.
// Live look feedback 2026-10-21: "too many illuminated rooms ... we need
// rooms to look destroyed".
vec3 ih_room_light(ivec3 cell, out float fire) {
    fire = 0.0;
    float cw    = interior_wear((vec3(cell) + 0.5) * kRoomSize) / max(u_plating[24], 1e-3);
    float vent  = smoothstep(0.10, 0.45, cw);
    float r     = ih_rand(cell, 3u);
    float phase = ih_rand(cell, 4u) * 6.2831853;
    // A few rooms keep their power even at the hole (Mark 2026-10-21: "2-3%
    // of rooms lit").
    float p_lit   = mix(0.10, 0.025, vent);
    float p_fail  = p_lit  + mix(0.10, 0.04, vent);
    float p_emerg = p_fail + mix(0.10, 0.06, vent);
    float p_fire  = p_emerg + 0.12 * smoothstep(0.25, 0.6, cw) * (1.0 - smoothstep(0.85, 1.0, cw));
    vec3 col;
    if (r < p_lit) {
        // Still powered. So rare it never reads as a mosaic, so it stays
        // visible from range, like a fire: a lit window in the wreck.
        return vec3(0.80, 0.88, 1.00) * mix(0.6, 1.0, g_detail);
    } else if (r < p_fail) {
        // Failing: mostly off, stuttering on.
        ivec3 tk = ivec3(cell.xy, int(floor(u_time * 9.0 + phase)));
        col = vec3(0.80, 0.88, 1.00) * 0.9 * step(0.75, ih_rand(tk, 6u));
    } else if (r < p_emerg) {
        float pulse = 0.55 + 0.45 * sin(u_time * 2.4 + phase);
        col = vec3(1.0, 0.10, 0.06) * 0.8 * pulse;         // emergency red
    } else if (r < p_fire) {
        fire = 1.0;                                        // burning
        float fl = 0.75 + 0.25 * sin(u_time * 13.0 + phase * 7.0)
                               * sin(u_time * 7.3 + phase * 3.0);
        return blackbody(0.62) * 2.0 * fl * mix(0.5, 1.0, g_detail);
    } else {
        return kDarkRoom * (1.0 - 0.5 * vent);
    }
    return mix(kDarkRoom, col, g_detail);
}

// Soot over a surface, from the interior wear there (0 undamaged).
float ih_soot(vec3 p, float iw) {
    return smoothstep(0.15, 0.85, iw / max(u_plating[24], 1e-3))
         * (0.55 + 0.45 * vnoise3(p * 0.35));
}

// Has the ray left the ship at p? Never without a fill volume.
bool left_ship(vec3 p) {
    if (u_fill_ok == 0) return false;
    vec3 tc = (p - u_fill_origin) / (u_fill_cell * vec3(u_fill_dims));
    if (any(lessThan(tc, vec3(0.0))) || any(greaterThan(tc, vec3(1.0)))) return true;
    return texture(u_fill, tc).r < u_fill_backing;
}

// Ray against an axis-aligned box. tn = entry distance, ax = entry axis.
bool ih_ray_box(vec3 ro, vec3 rd, vec3 bmin, vec3 bmax, out float tn, out int ax) {
    vec3 inv = 1.0 / (rd + vec3(equal(rd, vec3(0.0))) * 1e-6);
    vec3 t0 = (bmin - ro) * inv, t1 = (bmax - ro) * inv;
    vec3 lo = min(t0, t1), hi = max(t0, t1);
    tn = max(max(lo.x, lo.y), lo.z);
    float tf = min(min(hi.x, hi.y), hi.z);
    ax = (tn == lo.x) ? 0 : (tn == lo.y ? 1 : 2);
    return tf >= max(tn, 0.0);
}

// Room contents: one block standing on the room's deck, by zone. Cabins get
// a console or bunk against a wall, machinery a tall block, bays a crate;
// corridors stay clear. Returns the hit in [t0, t1) of the walk.
bool ih_contents(ivec3 cell, vec3 ro, vec3 rd, float t0, float t1,
                 out float th, out int ax, out int zone) {
    zone = ih_zone(cell);
    if (zone == 1) return false;
    if (ih_rand(cell, 21u) > 0.7) return false;
    if (!ih_plane_exists(2, cell.z, cell)) return false;      // nothing to stand on
    vec3 a = vec3(ih_rand(cell, 22u), ih_rand(cell, 23u), ih_rand(cell, 24u));
    vec3 size = zone == 0 ? vec3(0.30, 0.25, 0.30) + a * vec3(0.20, 0.25, 0.12)
              : zone == 2 ? vec3(0.25, 0.25, 0.60) + a * vec3(0.20, 0.20, 0.35)
              :             vec3(0.20, 0.20, 0.15) + a * vec3(0.15, 0.15, 0.15);
    vec2 at = vec2(ih_rand(cell, 25u), ih_rand(cell, 26u)) * (1.0 - size.xy - 0.1) + 0.05;
    if (zone == 0) at.x = ih_rand(cell, 27u) < 0.5 ? 0.04 : 0.96 - size.x;   // against a wall
    vec3 lo = (vec3(cell) + vec3(at, 0.0)) * kRoomSize;
    vec3 hi = lo + size * kRoomSize;
    if (!ih_ray_box(ro, rd, lo, hi, th, ax)) return false;
    return th >= t0 && th < t1;
}

// TWIN of opaque.frag's plating_rim_heat (same body): 0..1, (1 - age / life)
// x (1 - smoothstep(r, 3r, distance)), the hottest event's; 0 with no rims.
// Change both together.
float rim_heat(vec3 p) {
    float h = 0.0;
    for (int i = 0; i < u_rim_count; ++i) {
        float r = u_rim_a[i].w;
        float fresh = clamp(1.0 - u_rim_b[i].x / max(u_rim_b[i].y, 1e-3), 0.0, 1.0);
        h = max(h, fresh * (1.0 - smoothstep(r, 3.0 * r, length(p - u_rim_a[i].xyz))));
    }
    return h;
}

// Walk the room lattice. Returns false = discard (blown through). On true,
// `c` is the shaded colour. ro/rd body frame, rd unit length.
bool ih_shade(vec3 ro, vec3 rd, out vec3 c) {
    c = vec3(0.0);
    float deck_break = u_plating[24];
    ivec3 stp  = ivec3(rd.x >= 0.0 ? 1 : -1, rd.y >= 0.0 ? 1 : -1, rd.z >= 0.0 ? 1 : -1);
    vec3 ard   = max(abs(rd), vec3(1e-6));   // axis-parallel ray: never divide by 0
    ivec3 cell = ivec3(floor(ro / kRoomSize));
    vec3 next  = (vec3(cell) + max(vec3(stp), vec3(0.0))) * kRoomSize;
    vec3 tmax  = abs(next - ro) / ard;
    vec3 tdel  = kRoomSize / ard;
    float t_in = 0.0;                        // where the ray entered `cell`

    for (int i = 0; i < kInteriorMaxSteps; ++i) {
        int axis = (tmax.x < tmax.y) ? (tmax.x < tmax.z ? 0 : 2)
                                     : (tmax.y < tmax.z ? 1 : 2);
        float t  = tmax[axis];

        // Contents of this room, before the ray reaches its far plane.
        // Skipped where a room is only a few pixels (no detail to show).
        float tb; int bax, zone;
        if (g_detail > 0.3 && ih_contents(cell, ro, rd, t_in, t, tb, bax, zone)) {
            vec3 pb = ro + rd * tb;
            if (deck_break_wear(pb) <= deck_break) {
                float iwb = interior_wear(pb);
                float fire;
                vec3 room = ih_room_light(cell, fire);
                vec3 albedo = zone == 2 ? vec3(0.22, 0.23, 0.25)     // machinery
                            : zone == 0 ? vec3(0.30, 0.31, 0.34)     // console / bunk
                            :             vec3(0.33, 0.31, 0.27);    // crate
                float lit = bax == 2 ? 0.8 : 0.5;                    // tops catch the light
                albedo *= 1.0 - 0.8 * ih_soot(pb, iwb);
                c = albedo * (room * lit + u_ambient_light);
                c *= exp(-tb / kInteriorFogDist);
                return true;
            }
        }

        vec3  p   = ro + rd * t;
        // The blown tests' wear (deck-break subset); shading below re-reads
        // the whole list.
        float iwd = deck_break_wear(p);

        // (a) Left the ship (checked on every crossing, wall or not, so a
        // ray through a missing wall cannot wander into a nacelle).
        if (left_ship(p)) {
            if (iwd > deck_break) return false;    // far wall gone too: blown through
            float iw = interior_wear(p);
            // The far wall: the inside of the pressure hull, lit by this room.
            float fire;
            vec3 room = ih_room_light(cell, fire);
            float grain = vnoise3(p * 0.13);
            vec3 albedo = INNER_HULL * u_plating[17] * (0.45 + 0.25 * grain);
            albedo *= 1.0 - 0.8 * ih_soot(p, iw);
            c = albedo * (room + u_ambient_light);
            c *= exp(-t / kInteriorFogDist);
            return true;
        }

        int plane = cell[axis] + (stp[axis] > 0 ? 1 : 0);
        if (ih_plane_exists(axis, plane, cell)) {
            // (b) Blown plate: keep walking. The test is the noised wear (two
            // octaves, so decks tear raggedly rather than room by room) over
            // the deck-break subset; the char band below reads the same noise
            // over the whole list (`s`), equal wherever a plate can break.
            float n1 = (vnoise3(p * kTornNoiseFreq) - 0.5) * u_plating[19];
            float n2 = (vnoise3(p * 0.17) - 0.5) * u_plating[19] * 1.5;
            if (iwd + n1 + n2 <= deck_break) {
                float iw = interior_wear(p);
                float s  = iw + n1 + n2;
                // (c) Shade this plate, as seen from inside `cell`.
                vec3 q   = (p - vec3(cell) * kRoomSize) / kRoomSize;   // 0..1 in room
                float fire;
                vec3 room = ih_room_light(cell, fire);
                int zone = ih_zone(cell);

                vec3  albedo;
                vec3  emit = vec3(0.0);
                float lit;   // share of the room light reaching this point
                if (axis == 2 && stp.z < 0) {
                    // FLOOR (looking down): deck plating, panel seams; bays
                    // and machinery spaces have grating.
                    vec2 g  = fract(q.xy * (zone >= 2 ? vec2(10.0, 14.0) : vec2(4.0, 6.0)));
                    float seam = min(min(g.x, 1.0 - g.x), min(g.y, 1.0 - g.y));
                    albedo = vec3(0.34, 0.34, 0.36) * mix(0.55, 1.0, smoothstep(0.02, 0.06, seam));
                    lit    = mix(0.55, 1.0, fire);
                } else if (axis == 2) {
                    // CEILING (looking up): conduits along the keel, and the
                    // room's light strip (dead in an unpowered room).
                    float pipe = step(0.75, fract(q.x * 3.0 + 0.1 * float(zone)));
                    albedo = vec3(0.38, 0.39, 0.41) * mix(1.0, 0.45, pipe);
                    float strip = 1.0 - smoothstep(0.04, 0.07, abs(q.x - 0.5));
                    emit   = room * strip * 1.2 * g_detail;
                    lit    = mix(0.25, 0.4, fire);
                } else {
                    // WALL: panels, a dark waist band, a doorway on bulkheads;
                    // machinery spaces show ribbed bulkheads instead.
                    float u  = (axis == 0) ? q.y : q.x;
                    float gu = fract(u * (zone == 2 ? 12.0 : 5.0));
                    float seam = min(gu, 1.0 - gu);
                    albedo = vec3(0.46, 0.47, 0.51) * mix(0.6, 1.0, smoothstep(0.015, 0.05, seam));
                    float band = step(0.42, q.z) * step(q.z, 0.50);
                    albedo = mix(albedo, vec3(0.10, 0.10, 0.12), band);
                    if (axis == 1 && zone != 2 && abs(u - 0.5) < 0.12 && q.z < 0.72) {
                        albedo *= 0.25;   // doorway: dark recess
                    }
                    // Lit from the ceiling: brighter high, fire flips it.
                    lit = mix(mix(0.35, 1.0, q.z), mix(1.0, 0.45, q.z), fire);
                }

                // Wrecked: soot where the damage reached.
                albedo *= 1.0 - 0.8 * ih_soot(p, iw);
                // Room light + a little of the scene ambient.
                c = albedo * (room * lit + u_ambient_light) + emit;

                // Torn plate edge: the last wear unit short of breaking is
                // charred, with a dull glow. Undamaged plates stay clean.
                float edge = smoothstep(deck_break - 1.0, deck_break, s);
                c *= mix(1.0, 0.3, edge);
                c += blackbody(0.45) * edge * 0.25;
                // At a fresh tear the char edge is molten (the rim's heat).
                float rh = rim_heat(p);
                c += blackbody(0.55 + 0.35 * rh) * rh * 1.5 * edge;

                // Depth fog toward black.
                c *= exp(-t / kInteriorFogDist);
                return true;
            }
        }
        cell[axis] += stp[axis];
        tmax[axis] += tdel[axis];
        t_in = t;
    }
    // Ran out of crossings still inside the ship: deep interior, near-black.
    c = vec3(0.004, 0.004, 0.005);
    return true;
}

// ---- Rock crater (u_interior_rock != 0) ----------------------------------
// The old breach.frag rock constants (kRockInteriorDarken, kRockFlatColour).
const float kRockInteriorDarken = 0.55;
const vec3  kRockFlatColour     = vec3(0.30, 0.28, 0.25);
const int   kCraterSteps        = 20;     // march steps of max(reach_max, 1) / 10
const int   kCraterRefine       = 4;      // bisection steps at the wall
const float kCraterGradH        = 0.5;    // central-difference step, model units
const float kRockTexScale       = 0.02;   // triplanar UV per model unit
const float kCraterFadeDist     = 40.0;   // depth fade exp(-t / 40)

// opaque.frag's dhash / vnoise / plating_lumps / plating_breach_at, copied
// (renamed rk_*) so the crater wall sits on the rule the rock's cut uses.
// Rocks take the cell vec2(0): one rock-wide toughness, no panels.
float rk_dhash(vec2 v) { return fract(sin(dot(v, vec2(127.1, 311.7))) * 43758.5453); }
float rk_vnoise(vec2 v) {
    vec2 i = floor(v), f = fract(v);
    float a = rk_dhash(i), b = rk_dhash(i + vec2(1,0));
    float c = rk_dhash(i + vec2(0,1)), d = rk_dhash(i + vec2(1,1));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float rk_lumps(vec3 p) {
    float f = 1.0 / max(2.5 * u_plating[2], 1.0);
    return rk_vnoise(p.xy * f + p.z * 0.61 * f + 13.7) * 0.65
         + rk_vnoise(p.yz * f * 1.9 + p.x * f * 0.7 + 21.1) * 0.35;
}
float rk_breach_at(vec3 p) {
    return u_plating[16] * (1.0 + u_plating[22] * (rk_dhash(vec2(0.0) * 0.029 + 31.0) - 0.4))
         + (rk_lumps(p) - 0.5) * 2.0 * u_plating[23];
}
// opaque.frag's plating_rock_hole tear lift, copied: the same noise at the
// same frequency, so the wall meets the cut's ragged edge.
float rk_tear_lift(vec3 p) {
    float f = 1.0 / max(u_plating[1] * 0.6, 0.1);
    float n = rk_vnoise(p.xy * f + p.z * 0.6 * f + 2.7) * 0.7
            + rk_vnoise(p.yz * f * 2.1 + p.x * f * 0.8 + 5.3) * 0.3;
    return (n - 0.5) * u_plating[19] * 1.5;
}
// Rock still standing at p (the crater wall and beyond).
bool rk_solid(vec3 p) {
    return interior_wear(p) + rk_tear_lift(p) < rk_breach_at(p);
}

// March from the cut (ro) along rd to the crater wall. Returns false =
// discard (left the fill first: blown through). On true, `c` is the wall.
bool rock_shade(vec3 ro, vec3 rd, out vec3 c) {
    c = vec3(0.0);
    float reach_max = 0.0;
    for (int i = 0; i < u_dmg_count; ++i) reach_max = max(reach_max, u_dmg_a[i].w);
    float dt = max(reach_max, 1.0) / 10.0;
    float t0 = 0.0, t1 = float(kCraterSteps) * dt;
    for (int i = 1; i <= kCraterSteps; ++i) {
        float t = float(i) * dt;
        vec3 p = ro + rd * t;
        if (left_ship(p)) return false;          // blown through
        if (rk_solid(p)) { t1 = t; break; }
        t0 = t;
    }
    // Ran out of steps still in the crater: shade the last point as the wall
    // (never space where rock should be). Otherwise refine to the wall.
    if (t0 < t1) {
        for (int k = 0; k < kCraterRefine; ++k) {
            float tm = 0.5 * (t0 + t1);
            if (rk_solid(ro + rd * tm)) t1 = tm; else t0 = tm;
        }
    }
    float t = t1;
    vec3 p = ro + rd * t;

    // Wall normal: the negative wear gradient (central differences),
    // turned toward the viewer (the side of the wall the ray sees).
    vec3 hx = vec3(kCraterGradH, 0.0, 0.0), hy = hx.yxz, hz = hx.zyx;
    vec3 g = vec3(interior_wear(p + hx) - interior_wear(p - hx),
                  interior_wear(p + hy) - interior_wear(p - hy),
                  interior_wear(p + hz) - interior_wear(p - hz));
    vec3 n = dot(g, g) > 1e-12 ? -normalize(g) : -rd;
    n = faceforward(n, rd, n);

    // Triplanar rock texture, weights |n|^4.
    vec3 w = pow(abs(n), vec3(4.0));
    w /= max(w.x + w.y + w.z, 1e-6);
    vec3 uvw = p * kRockTexScale;
    vec3 ddx = g_dpdx * kRockTexScale, ddy = g_dpdy * kRockTexScale;
    vec3 tex;
    if (u_interior_rock == 1) {
        tex = textureGrad(u_rock_tex, uvw.yz, ddx.yz, ddy.yz).rgb * w.x
            + textureGrad(u_rock_tex, uvw.zx, ddx.zx, ddy.zx).rgb * w.y
            + textureGrad(u_rock_tex, uvw.xy, ddx.xy, ddy.xy).rgb * w.z;
    } else {
        tex = kRockFlatColour;
    }
    tex *= kRockInteriorDarken * exp(-t / kCraterFadeDist);

    // Ambient (opaque.frag's directional-ambient formula) + directional
    // lights. No rooms, no room light, no fire.
    // n is rest frame: back to the posed body (C^T, C rigid), then world.
    vec3 n_ws = normalize(mat3(u_ship_world) * (transpose(mat3(u_node_rest_fix)) * n));
    vec3 light = u_ambient_light;
    if (u_ambient_gradient > 0.0) {
        float amb_d = clamp(dot(n_ws, u_ambient_dir_ws), -1.0, 1.0);
        light = u_ambient_light * (1.0 + u_ambient_gradient * amb_d);
    }
    int dir_count = min(u_dir_light_count, MAX_DIR_LIGHTS);
    for (int i = 0; i < dir_count; ++i)
        light += max(dot(n_ws, normalize(u_dir_light_dir_ws[i])), 0.0) * u_dir_light_color[i];

    // Scorched at the wall: the nearer breach, the darker.
    float breach = rk_breach_at(p);
    float scorch = smoothstep(breach - 1.0, breach + 1.0, interior_wear(p));
    c = tex * light * (1.0 - 0.5 * scorch);
    return true;
}

void main() {
    // Footprint first, in uniform control flow (derivatives).
    float fp = max(length(fwidth(v_body_pos)), 1e-4);
    g_detail = smoothstep(1.5, 6.0, kRoomSize.z / fp);   // deck pitch in pixels
    g_dpdx = dFdx(v_body_pos);
    g_dpdy = dFdy(v_body_pos);
    vec3 ro = v_body_pos;
    vec3 rd = v_body_pos - (u_node_rest_fix * vec4(u_camera_pos_body, 1.0)).xyz;
    float rd_len = length(rd);
    if (rd_len < 1e-6) discard;   // camera on the hull surface: no ray
    rd /= rd_len;
    vec3 c;
    bool kept = u_interior_rock != 0 ? rock_shade(ro, rd, c) : ih_shade(ro, rd, c);
    if (!kept) discard;
    frag_color = vec4(c, 1.0);
}
