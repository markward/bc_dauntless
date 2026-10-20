#version 410 core

// Hull interior behind a plating cut (SPIKE, damage redesign; plan
// 2026-10-20-layered-damage-hull-interior, Task 3).
//
// HullInteriorPass draws the hull mesh through breach.vert under the stencil
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
// The walk (ih_hash, ih_rand, ih_wall_exists, ih_room_light and the DDA of
// ih_shade) is ported from spike/breach-interior-mapping's breach.frag with
// the constants Mark tuned live on 2026-10-20 (findings:
// docs/engine/breach-interior-mapping-spike-findings.md). What changed: the
// blown-plate test and the torn edge read the plating damage list instead of
// the carve field; the left-the-ship case shows the far wall unless the hull
// is blown through; there is no fresh-hit heat (records carry no age).
//
// Everything is BODY frame, in model units.

in vec3 v_body_pos;
in vec3 v_body_normal;   // breach.vert writes it; unused here

uniform vec3 u_camera_pos_body;

// Original (uncarved) fill, GL_R8 on unit 0. u_fill_ok 0 = no fill volume:
// rooms still draw, with no left-the-ship test.
uniform sampler3D u_fill;
uniform vec3      u_fill_origin;   // body-frame min corner
uniform vec3      u_fill_cell;     // cell size per axis
uniform ivec3     u_fill_dims;     // nx, ny, nz
uniform float     u_fill_backing;  // CarveFieldCache::kBackingIsovalue / 255
uniform int       u_fill_ok;

// The plating damage list (renderer/plating_damage.h).
const int MAX_DMG = 24;
uniform int  u_dmg_count;
uniform vec4 u_dmg_a[MAX_DMG];     // centre.xyz, reach
uniform vec4 u_dmg_b[MAX_DMG];     // normal.xyz, wear
uniform vec4 u_dmg_c[MAX_DMG];     // kind, 0, 0, 0

// Plating params: 17 inner hull brightness, 19 tear noise, 24 deck break wear.
uniform float u_plating[32];
uniform vec3  u_ambient_light;     // lighting.ambient x ambient_scale
uniform float u_time;              // game clock, seconds (flicker / pulse)

out vec4 frag_color;

// Copied from opaque.frag (its plating layer's pressure hull).
const vec3 INNER_HULL = vec3(0.42, 0.41, 0.40);

// Room lattice pitch, MODEL units (1 mu = 1.75 m): beam-wise room width,
// keel-wise room length, deck pitch. Live-tuned 2026-10-20 (first cut
// 9 x 13 x 4 read ~1.5x too big).
const vec3  kRoomSize          = vec3(6.0, 8.67, 2.67);
// Smaller rooms need more crossings for the same reach.
const int   kInteriorMaxSteps  = 24;
// Probability a WALL segment exists (decks always do). Missing walls merge
// cells into longer rooms and corridors.
const float kWallXChance       = 0.55;  // longitudinal walls (planes x = k)
const float kWallYChance       = 0.45;  // transverse bulkheads (planes y = k)
// Distance (model units) over which the interior fades to black.
const float kInteriorFogDist   = 120.0;
const float kTornNoiseFreq     = 0.6;   // cycles per model unit

// Blackbody-ish ramp keyed on heat 0..1. Copied from breach.frag.
vec3 blackbody(float heat) {
    vec3 cold  = vec3(0.0);
    vec3 red   = vec3(0.59, 0.10, 0.02);
    vec3 org   = vec3(1.0,  0.45, 0.08);
    vec3 white = vec3(1.0,  0.92, 0.72);
    vec3 lo  = mix(cold, red,   smoothstep(0.0,  0.35, heat));
    vec3 mid = mix(lo,   org,   smoothstep(0.35, 0.7,  heat));
    return     mix(mid,  white, smoothstep(0.7,  1.0,  heat));
}

// Value noise, [0,1]. Copied from breach.frag.
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

// Does the wall on `axis` at plane index `plane` exist for the segment the
// ray crosses in `cell`? Decks (axis 2) always exist.
bool ih_wall_exists(int axis, int plane, ivec3 cell) {
    if (axis == 2) return true;
    ivec3 key = cell;
    key[axis] = plane;
    return ih_rand(key, uint(axis + 1)) < (axis == 0 ? kWallXChance : kWallYChance);
}

// The room's light: colour x intensity, animated. `fire` (0..1) lets the
// caller bias the light toward the floor.
vec3 ih_room_light(ivec3 cell, out float fire) {
    fire = 0.0;
    float r     = ih_rand(cell, 3u);
    float phase = ih_rand(cell, 4u) * 6.2831853;
    // Mix (live-tuned 2026-10-20): 35% lit, 35% dark, 20% emergency, 10% fire.
    if (r < 0.35) {
        // Lit: cool white strips; a quarter of them failing and flickering.
        vec3 col = vec3(0.80, 0.88, 1.00) * 1.8;
        if (ih_rand(cell, 5u) < 0.25) {
            ivec3 tk = ivec3(cell.xy, int(floor(u_time * 9.0 + phase)));
            col *= step(0.35, ih_rand(tk, 6u));
        }
        return col;
    }
    // Dark: power out. A faint spill from neighbouring rooms keeps shape.
    if (r < 0.70) return vec3(0.10, 0.11, 0.13);
    if (r < 0.90) {                                        // emergency red
        float pulse = 0.55 + 0.45 * sin(u_time * 2.4 + phase);
        return vec3(1.0, 0.10, 0.06) * 1.3 * pulse;
    }
    fire = 1.0;                                            // burning
    float fl = 0.75 + 0.25 * sin(u_time * 13.0 + phase * 7.0)
                           * sin(u_time * 7.3 + phase * 3.0);
    return blackbody(0.62) * 2.4 * fl;
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

// Has the ray left the ship at p? Never without a fill volume.
bool left_ship(vec3 p) {
    if (u_fill_ok == 0) return false;
    vec3 tc = (p - u_fill_origin) / (u_fill_cell * vec3(u_fill_dims));
    if (any(lessThan(tc, vec3(0.0))) || any(greaterThan(tc, vec3(1.0)))) return true;
    return texture(u_fill, tc).r < u_fill_backing;
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

    for (int i = 0; i < kInteriorMaxSteps; ++i) {
        int axis = (tmax.x < tmax.y) ? (tmax.x < tmax.z ? 0 : 2)
                                     : (tmax.y < tmax.z ? 1 : 2);
        float t  = tmax[axis];
        vec3  p  = ro + rd * t;
        float iw = interior_wear(p);

        // (a) Left the ship (checked on every crossing, wall or not, so a
        // ray through a missing wall cannot wander into a nacelle).
        if (left_ship(p)) {
            if (iw > deck_break) return false;     // far wall gone too: blown through
            // The far wall: the inside of the pressure hull, lit by this room.
            float fire;
            vec3 room = ih_room_light(cell, fire);
            float grain = vnoise3(p * 0.13);
            vec3 albedo = INNER_HULL * u_plating[17] * (0.45 + 0.25 * grain);
            c = albedo * (room + u_ambient_light);
            c *= exp(-t / kInteriorFogDist);
            return true;
        }

        int plane = cell[axis] + (stp[axis] > 0 ? 1 : 0);
        if (ih_wall_exists(axis, plane, cell)) {
            // (b) Blown plate: keep walking.
            bool blown = iw + (vnoise3(p * kTornNoiseFreq) - 0.5) * u_plating[19] > deck_break;
            if (!blown) {
                // (c) Shade this plate, as seen from inside `cell`.
                vec3 q   = (p - vec3(cell) * kRoomSize) / kRoomSize;   // 0..1 in room
                float fire;
                vec3 room = ih_room_light(cell, fire);

                vec3  albedo;
                vec3  emit = vec3(0.0);
                float lit;   // share of the room light reaching this point
                if (axis == 2 && stp.z < 0) {
                    // FLOOR (looking down): deck plating, panel seams.
                    vec2 g  = fract(q.xy * vec2(4.0, 6.0));
                    float seam = min(min(g.x, 1.0 - g.x), min(g.y, 1.0 - g.y));
                    albedo = vec3(0.36, 0.36, 0.38) * mix(0.55, 1.0, smoothstep(0.02, 0.06, seam));
                    lit    = mix(0.55, 1.0, fire);
                } else if (axis == 2) {
                    // CEILING (looking up): the room's light strip along the keel.
                    albedo = vec3(0.40, 0.41, 0.43);
                    float strip = 1.0 - smoothstep(0.04, 0.07, abs(q.x - 0.5));
                    emit   = room * strip * 1.5;
                    lit    = mix(0.25, 0.4, fire);
                } else {
                    // WALL: panels, a dark waist band, and a doorway on bulkheads.
                    float u  = (axis == 0) ? q.y : q.x;
                    float gu = fract(u * 5.0);
                    float seam = min(gu, 1.0 - gu);
                    albedo = vec3(0.50, 0.51, 0.55) * mix(0.6, 1.0, smoothstep(0.015, 0.05, seam));
                    float band = step(0.42, q.z) * step(q.z, 0.50);
                    albedo = mix(albedo, vec3(0.10, 0.10, 0.12), band);
                    if (axis == 1 && abs(u - 0.5) < 0.12 && q.z < 0.72) {
                        albedo *= 0.25;   // doorway: dark recess
                    }
                    // Lit from the ceiling: brighter high, fire flips it.
                    lit = mix(mix(0.35, 1.0, q.z), mix(1.0, 0.45, q.z), fire);
                }

                // Room light + a little of the scene ambient.
                c = albedo * (room * lit + u_ambient_light) + emit;

                // Torn plate edge: charred, with a dull glow.
                float edge = 1.0 - smoothstep(deck_break - 1.0, deck_break, iw);
                c *= mix(1.0, 0.35, edge);
                c += blackbody(0.5) * edge * 0.6;

                // Depth fog toward black.
                c *= exp(-t / kInteriorFogDist);
                return true;
            }
        }
        cell[axis] += stp[axis];
        tmax[axis] += tdel[axis];
    }
    // Ran out of crossings still inside the ship: deep interior, near-black.
    c = vec3(0.004, 0.004, 0.005);
    return true;
}

void main() {
    vec3 ro = v_body_pos;
    vec3 rd = v_body_pos - u_camera_pos_body;
    float rd_len = length(rd);
    if (rd_len < 1e-6) discard;   // camera on the hull surface: no ray
    rd /= rd_len;
    vec3 c;
    if (!ih_shade(ro, rd, c)) discard;
    frag_color = vec4(c, 1.0);
}
