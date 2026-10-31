#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <stdexcept>

#include "dauntless/combat/mirror.h"

// The K2 kernel's hull trace (native combat phase 2, Task 3): a port of
// combat._resolve_hit_point plus host_io.ray_trace_mesh (map 1.4, F17, F18).
//
// THE TRACE ITSELF IS NOT HERE. The combat library never links the renderer
// and never compiles ray_trace.cc with its own flags (the renderer's copy is
// what the Python path calls, and a recompiled copy could differ in the last
// bits). The host bindings install TraceHooks that call the SAME C++ function
// the `ray_trace_mesh` binding calls (host_bindings.cc,
// trace_instance_for_python) on the host's g_world, at whatever pose it was
// last synced to -- never re-synced here (map 8.3.9). The hooks touch only
// g_world and C++, never Python (ruling J: the kernel holds the GIL).

namespace dauntless::combat {

// scenegraph::InstanceId's two fields; this library does not include the
// scenegraph.
struct InstanceId {
    uint32_t index = 0;
    uint32_t generation = 0;
};

// renderer::RayHit's point, normal and t, in the trace's float.
struct TraceHit {
    float point[3];
    float normal[3];
    float t;
};

// Thrown by a TraceFn (and so by the ray_trace_mesh binding, as RuntimeError)
// for an id g_world no longer holds.
struct StaleInstance : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// The binding's body: (iid, instance-relative origin, direction, max_dist)
// already narrowed to float -> the hit, or nullopt for the binding's None.
// Throws StaleInstance for a stale iid (and std::runtime_error for an
// instance with no model handle), as the binding does.
using TraceFn = std::function<std::optional<TraceHit>(
    InstanceId, const float o[3], const float d[3], float max_dist)>;
// _h.instance_translation: the instance's double view-space translation, or
// nullopt for a stale id.
using TranslationFn = std::function<std::optional<Vec3>(InstanceId)>;

struct TraceHooks {
    TranslationFn translation;
    TraceFn trace;
};

// The process's hooks: the host bindings install the real ones at module
// load. Empty (no host) is host_io with `_h is None`: every trace a miss.
void install_trace_hooks(TraceHooks hooks);
const TraceHooks& installed_trace_hooks();

// pybind's narrowing of a Python float argument to a C++ float:
// `(float) PyFloat_AsDouble(x)` (pybind11 cast.h, type_caster<arithmetic>):
// round to nearest even, inf for an overflow, NaN stays NaN.
float narrow_like_pybind(double x);

struct ResolvedHit {
    // Which Python object the point is: Mesh and Sphere a new TGPoint3,
    // Fallback the caller's fallback_point itself, Origin the ray origin
    // itself (ray_sphere_entry with the origin inside the sphere).
    enum class Tier { Mesh, Sphere, Fallback, Origin } tier = Tier::Fallback;
    Vec3 point{0.0, 0.0, 0.0};
    std::optional<Vec3> normal;  // the mesh tier's surface normal only
};

// combat._resolve_hit_point(ship_instances, target, origin, dir, max_dist,
// fallback_point) with sphere_fallback=True (every phaser call):
//   * iid       -- ship_instances.get(target): nullopt is Python's None
//                  (absent, or no table at all);
//   * dir       -- nullopt is Python's ray_direction None;
//   * view_offset -- frames.view_offset(frames.containing_set(target)),
//                  nullopt for None; (0, 0, 0) by a tuple compare (so -0.0)
//                  is no shift, as frames.shifted has it.
// Throws std::invalid_argument ("ask the Python") only from the sphere tier's
// reads of the target row (stale handle, invalid transform).
ResolvedHit resolve_hit_point(const Mirror& m, const TraceHooks& hooks,
                              int64_t target, std::optional<InstanceId> iid,
                              const Vec3& origin, const std::optional<Vec3>& dir,
                              double max_dist, const Vec3& fallback_point,
                              const std::optional<Vec3>& view_offset);

}  // namespace dauntless::combat
