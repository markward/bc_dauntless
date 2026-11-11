// first_blocker (beam_block.h): engine/appc/beam_blockers.py's
// first_blocker, statement by statement. Each block quotes the Python line
// it stands for; keep the two in step.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/beam_block.h"

#include <cmath>
#include <cstddef>
#include <string>
#include <utility>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/projectile_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

using detail::world_location;

namespace {

[[noreturn]] void need_python(const std::string& why) {
    throw NeedPython("beam blocker: " + why + " -- answer in Python");
}

const ObjectRow& row(const Mirror& m, int64_t h, const char* who) {
    const ObjectRow* r = h < 0 ? nullptr : m.object(h);
    if (r == nullptr) need_python(std::string(who) + " has no live Object row");
    return *r;
}

// frames.containing_set(obj): `_containing_set`, -1 (None) or a live Set.
int64_t containing_set(const Mirror& m, const ObjectRow& o) {
    const int64_t s = o._containing_set;
    if (s != -1 && (s < 0 || m.set(s) == nullptr))
        need_python("_containing_set unnamed");
    return s;
}

// beam_blockers._dist(a, b): math.sqrt of the summed squares of b - a.
double dist(const Vec3& a, const Vec3& b) {
    const double dx = b[0] - a[0];
    const double dy = b[1] - a[1];
    const double dz = b[2] - a[2];
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

// beam_blockers._in_reach, with `p` = c.GetWorldLocation().
bool in_reach(const Vec3& p, const Vec3& emitter, const Vec3& aim_unit,
              double contact_dist, double bound) {
    const double vx = p[0] - emitter[0];
    const double vy = p[1] - emitter[1];
    const double vz = p[2] - emitter[2];
    const double t = vx * aim_unit[0] + vy * aim_unit[1] + vz * aim_unit[2];
    if (t < -bound || t > contact_dist + bound) return false;
    if ((vx * vx + vy * vy + vz * vz) - t * t > bound * bound) return false;
    return true;
}

// frames.view_offset(set) from the inputs' table: only Python knows a set
// it does not hold.
std::optional<Vec3> view_offset(const BeamBlockInputs& in, int64_t set) {
    const auto it = in.view_offsets.find(set);
    if (it == in.view_offsets.end())
        need_python("no view offset for the candidate's set");
    return it->second;
}

// combat.shields_block(c) for a candidate: beam_feed's feed_shields_block
// rule. No real GetShields: the stub chain answers False. A non-ShipClass
// with a real one has no port.
bool candidate_shields_block(const BeamBlockInputs& in, int64_t c) {
    const ObjectRow& r = row(in.m, c, "candidate");
    if (!r.has_real_get_shields) return false;
    if (!r.is_ship_class)
        need_python("a non-ShipClass candidate with a real GetShields");
    return shields_block(in.m, c, in.npc_shields_off, in.player);
}

// combat._resolve_hit_point(ship_instances, c, emitter, aim_unit, max_dist,
// fallback) for a ship candidate in `cset`, as beam_feed's beam_endpoint
// calls it: the view offset is read only with an instance, and a value that
// is no InstanceId traces nothing (the binding raises inside the try).
ResolvedHit resolve(const BeamBlockInputs& in, int64_t c, int64_t cset,
                    const Vec3& emitter, const Vec3& aim_unit,
                    double max_dist, const Vec3& fallback) {
    static const TraceHooks kNoHost;
    std::optional<InstanceId> iid;
    std::optional<Vec3> off;
    const TraceHooks* hooks = &in.hooks;
    const auto it = in.iids.find(c);
    if (it != in.iids.end()) {
        off = view_offset(in, cset);
        iid = it->second.id;
        if (it->second.bad) hooks = &kNoHost;
    }
    return resolve_hit_point(in.m, *hooks, c, iid, emitter, aim_unit,
                             max_dist, fallback, off);
}

std::optional<BeamBlocker> walk(const BeamBlockInputs& in, int64_t shooter,
                                int64_t target, const Vec3& emitter,
                                const Vec3& aim_unit, double contact_dist) {
    using Kind = BeamBlocker::Kind;
    using Tier = BeamBlocker::Tier;
    const Mirror& m = in.m;
    // shooter_set = frames.containing_set(shooter)
    const int64_t shooter_set = containing_set(m, row(m, shooter, "shooter"));
    // best = contact_dist; found = None
    double best = contact_dist;
    std::optional<BeamBlocker> found;
    // for c in ships:
    for (const int64_t c : in.ships) {
        // if c is shooter or c is target: continue
        if (c == shooter || c == target) continue;
        const ObjectRow& r = row(m, c, "candidate");
        // if hasattr(c, "IsDead") and c.IsDead(): continue
        // (a stub IsDead records telemetry: Python's)
        if (!r.has_real_is_dead) need_python("a candidate with no real IsDead");
        if (r._dead) continue;
        // if c.IsHidden(): continue
        if (r._hidden) continue;
        // if frames.containing_set(c) is not shooter_set: continue
        if (containing_set(m, r) != shooter_set) continue;
        // bound = combat.bubble_bound_radius(c)
        const double bound = bubble_bound_radius(m, c);
        // if not _in_reach(c, emitter, aim_unit, contact_dist, bound): continue
        if (!in_reach(world_location(m, r), emitter, aim_unit, contact_dist,
                      bound))
            continue;
        // b = None
        // if combat.shields_block(c):
        //     b = combat.shield_bubble_entry(c, emitter, aim_unit, contact_dist)
        std::optional<Vec3> b;
        if (candidate_shields_block(in, c))
            b = shield_bubble_entry(m, c, emitter, aim_unit, contact_dist);
        // if b is not None:
        if (b) {
            // d = _dist(emitter, b)
            const double d = dist(emitter, *b);
            if (d < best) {
                // point, normal = combat._resolve_hit_point(ship_instances, c,
                //     emitter, aim_unit, contact_dist * 1.5, b)
                const ResolvedHit hit = resolve(in, c, shooter_set, emitter,
                                                aim_unit, contact_dist * 1.5, *b);
                // if normal is None: point = b
                const Vec3 point = hit.normal ? hit.point : *b;
                best = d;
                found = BeamBlocker{.kind = Kind::Ship, .handle = c,
                                    .dist = d, .point = point,
                                    .normal = hit.normal, .bubble = b,
                                    .tier = Tier::Bubble};
            }
            continue;
        }
        // point, normal = combat._resolve_hit_point(ship_instances, c,
        //     emitter, aim_unit, contact_dist * 1.5, emitter)
        const ResolvedHit hit = resolve(in, c, shooter_set, emitter, aim_unit,
                                        contact_dist * 1.5, emitter);
        // if normal is None: continue
        if (!hit.normal) continue;
        // d = _dist(emitter, point)
        const double d = dist(emitter, hit.point);
        if (d < best) {
            best = d;
            found = BeamBlocker{.kind = Kind::Ship, .handle = c, .dist = d,
                                .point = hit.point, .normal = hit.normal,
                                .tier = Tier::Mesh};
        }
    }
    // for planet, iid in planet_rows(shooter_set, planet_instances):
    // (planet_rows(None) is [])
    if (shooter_set == -1) return found;
    for (std::size_t i = 0; i < in.planets.size(); ++i) {
        const BeamPlanet& p = in.planets[i];
        // planet_rows: the shooter set's own Planets. Its second check,
        // `frames.containing_set(planet) is not shooter_set`, is the same
        // `set` (BeamPlanet's contract).
        if (p.set != shooter_set) continue;
        // if planet is shooter or planet is target: continue
        if (p.handle != -1 && (p.handle == shooter || p.handle == target))
            continue;
        // radius = world_radius(planet); bound = radius * PLANET_BOUND_SLACK
        const double radius = p.radius;
        const double bound = radius * kPlanetBoundSlack;
        if (!in_reach(p.centre, emitter, aim_unit, contact_dist, bound))
            continue;
        const auto planet = static_cast<int64_t>(i);
        // if iid is not None:
        if (p.iid || p.iid_bad) {
            // point, normal = combat._resolve_hit_point(planet_instances,
            //     planet, emitter, aim_unit, contact_dist * 1.5, emitter)
            // Only the mesh tier yields a normal; a value that is no
            // InstanceId raises inside the try (no mesh).
            const std::optional<Vec3> off = view_offset(in, p.set);
            std::optional<std::pair<Vec3, Vec3>> mesh;
            if (!p.iid_bad)
                mesh = trace_instance_point(in.hooks, *p.iid, emitter,
                                            aim_unit, contact_dist * 1.5, off);
            // if normal is None: continue
            if (!mesh) continue;
            const double d = dist(emitter, mesh->first);
            if (d < best) {
                best = d;
                found = BeamBlocker{.kind = Kind::Planet, .planet = planet,
                                    .dist = d, .point = mesh->first,
                                    .normal = mesh->second,
                                    .tier = Tier::Mesh};
            }
            continue;
        }
        // point = combat.ray_sphere_entry(emitter, aim_unit, contact_dist,
        //     planet.GetWorldLocation(), radius)
        // if point is None or point is emitter: continue
        const SphereEntry e =
            ray_sphere_entry(emitter, aim_unit, contact_dist, p.centre, radius);
        if (e.kind != SphereEntry::Kind::Point) continue;
        const double d = dist(emitter, e.point);
        if (d < best) {
            best = d;
            found = BeamBlocker{.kind = Kind::Planet, .planet = planet,
                                .dist = d, .point = e.point,
                                .tier = Tier::Sphere};
        }
    }
    return found;
}

}  // namespace

std::optional<BeamBlocker> first_blocker(const BeamBlockInputs& in,
                                         int64_t shooter, int64_t target,
                                         const Vec3& emitter,
                                         const Vec3& aim_unit,
                                         double contact_dist) {
    try {
        return walk(in, shooter, target, emitter, aim_unit, contact_dist);
    } catch (const std::invalid_argument& e) {
        // A geometry port's refusal (fall_back, PartStale, MountUnknown).
        throw NeedPython(e.what());
    }
}

}  // namespace dauntless::combat
