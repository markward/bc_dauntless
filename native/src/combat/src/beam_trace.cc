// The K2 hull trace -- see beam_trace.h. resolve_hit_point ports
// combat._resolve_hit_point (combat.py:86-141) and the host_io.ray_trace_mesh
// it calls (host_io.py:570-599), statement by statement: keep them in step.
// K2M = docs/reference/engine/native-combat/k2-beams-map.md (1.4, F17, F18).
// The trace is the installed hook (the host's own compiled function).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/beam_trace.h"

#include <exception>
#include <utility>

#include "dauntless/combat/beam_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

using detail::is_zero_offset;
using detail::obj;
using detail::shifted;
using detail::world_location;

namespace {

TraceHooks& hooks_slot() {
    static TraceHooks hooks;
    return hooks;
}

struct MeshResult {
    Vec3 point;
    Vec3 normal;
};

// host_io.ray_trace_mesh (host_io.py:570-599), rest_pose False, `origin` in
// VIEW coordinates. nullopt is its None; a throw is the binding's raise.
std::optional<MeshResult> host_io_ray_trace_mesh(const TraceHooks& hooks,
                                                 InstanceId iid,
                                                 const Vec3& origin,
                                                 const Vec3& dir,
                                                 double max_dist) {
    // host_io.py:586 `if _h is None: return None`.
    if (!hooks.trace || !hooks.translation) return std::nullopt;
    // pybind narrows each argument (K2M F17).
    const float d_f[3] = {narrow_like_pybind(dir[0]), narrow_like_pybind(dir[1]),
                          narrow_like_pybind(dir[2])};
    const float max_f = narrow_like_pybind(max_dist);
    // host_io.py:591 t = _h.instance_translation(instance_id)
    const std::optional<Vec3> t = hooks.translation(iid);
    if (!t) {
        // host_io.py:592-593: a stale id still reaches the binding, with the
        // origin as given (it raises: StaleInstance).
        const float o_f[3] = {narrow_like_pybind(origin[0]),
                              narrow_like_pybind(origin[1]),
                              narrow_like_pybind(origin[2])};
        const std::optional<TraceHit> hit = hooks.trace(iid, o_f, d_f, max_f);
        if (!hit) return std::nullopt;
        return MeshResult{{hit->point[0], hit->point[1], hit->point[2]},
                          {hit->normal[0], hit->normal[1], hit->normal[2]}};
    }
    // host_io.py:594 rel = _relative_to(t, origin): a double subtract
    // (host_io.py:369), then narrowed.
    const Vec3 rel{origin[0] - (*t)[0], origin[1] - (*t)[1],
                   origin[2] - (*t)[2]};
    const float rel_f[3] = {narrow_like_pybind(rel[0]),
                            narrow_like_pybind(rel[1]),
                            narrow_like_pybind(rel[2])};
    // host_io.py:595-599
    const std::optional<TraceHit> hit = hooks.trace(iid, rel_f, d_f, max_f);
    if (!hit) return std::nullopt;
    const double px = hit->point[0];
    const double py = hit->point[1];
    const double pz = hit->point[2];
    return MeshResult{{px + (*t)[0], py + (*t)[1], pz + (*t)[2]},
                      {hit->normal[0], hit->normal[1], hit->normal[2]}};
}

}  // namespace

void install_trace_hooks(TraceHooks hooks) { hooks_slot() = std::move(hooks); }

const TraceHooks& installed_trace_hooks() { return hooks_slot(); }

float narrow_like_pybind(double x) {
    // pybind11 cast.h: `value = (T) py_value;` with py_value the double.
    return static_cast<float>(x);
}

// ── combat.py:86 _resolve_hit_point (K2M 1.4) ───────────────────────────────

ResolvedHit resolve_hit_point(const Mirror& m, const TraceHooks& hooks,
                              int64_t target, std::optional<InstanceId> iid,
                              const Vec3& origin, const std::optional<Vec3>& dir,
                              double max_dist, const Vec3& fallback_point,
                              const std::optional<Vec3>& view_offset) {
    using Tier = ResolvedHit::Tier;
    // combat.py:106-110: no direction, or no instance -> the fallback point,
    // with NO sphere tier (K2M 8.3.6).
    if (!dir) return {Tier::Fallback, fallback_point, std::nullopt};
    if (!iid) return {Tier::Fallback, fallback_point, std::nullopt};
    // combat.py:115-116 o = frames.shifted(ray_origin, to_view)
    // frames.shifted (frames.py:166-177): `p` ITSELF when off is None or
    // zero (detail::is_zero_offset), else p + sign * off per axis.
    const bool shift = view_offset && !is_zero_offset(*view_offset);
    const Vec3 o = shift ? shifted(origin, *view_offset, 1.0) : origin;
    // combat.py:117-125: any raise degrades to the sphere tier.
    std::optional<MeshResult> result;
    try {
        result = host_io_ray_trace_mesh(hooks, *iid, o, *dir, max_dist);
    } catch (const std::exception&) {
        result = std::nullopt;
    }
    // combat.py:127-130: the hit moved back out by -1.0 * to_view.
    if (result) {
        const Vec3 p =
            shift ? shifted(result->point, *view_offset, -1.0) : result->point;
        return {Tier::Mesh, p, result->normal};
    }
    // combat.py:133-141 (sphere_fallback is True for every phaser call).
    const Vec3 center = world_location(m, obj(m, target));
    // hasattr(ship, "GetRadius"): every Object row is an ObjectClass.
    const double radius = world_radius(m, target);
    // The UNSHIFTED ray_origin and the caller's direction, in double.
    const SphereEntry entry =
        ray_sphere_entry(origin, *dir, max_dist, center, radius);
    switch (entry.kind) {
        case SphereEntry::Kind::Point:
            return {Tier::Sphere, entry.point, std::nullopt};
        case SphereEntry::Kind::Origin:
            return {Tier::Origin, origin, std::nullopt};
        default:
            return {Tier::Fallback, fallback_point, std::nullopt};
    }
}

}  // namespace dauntless::combat
