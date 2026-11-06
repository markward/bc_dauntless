#pragma once

#include <cstdint>
#include <optional>
#include <vector>

// A ship model's hull mesh, traced on the CPU: the native copy of
// engine/appc/damage_point.py's _Bvh, built in Python (damage_point._mesh)
// and handed over as it stands, so this walks the same boxes and tests the
// same triangles with the same arithmetic. Model units (the NIF's).
//
// ShipSubsystem.IsHittableFromLocation (engine/appc/hull_line_of_sight.py)
// asks for the nearest crossing of a ray; the stock AI asks it for every
// subsystem it rates (AI/Preprocessors.py RateSubsystemForTargeting), a few
// per ship each FireScript update, which is ~65 us a ray in Python and ~1 us
// here.
namespace dauntless::combat {

struct HullBvhNode {
    double lo[3], hi[3];
    int64_t left = -1, right = -1;     // -1 on a leaf
    std::vector<int64_t> tris;         // a leaf's triangle indices
};

struct HullMesh {
    std::vector<double> tris;          // 9 per triangle: v0, e1, e2
    std::vector<HullBvhNode> nodes;    // nodes[0] is the root
};

// Store a mesh; returns its handle (>= 0).
int64_t hull_trace_register(HullMesh mesh);

// _Bvh.first_hit: the smallest t > 1e-6 at which the ray o + t*d crosses a
// triangle of mesh `h`, or nullopt. Throws std::out_of_range for a bad handle.
std::optional<double> hull_trace_first_hit(int64_t h, const double o[3],
                                           const double d[3]);

// Forget every mesh (tests).
void hull_trace_clear();

}  // namespace dauntless::combat
