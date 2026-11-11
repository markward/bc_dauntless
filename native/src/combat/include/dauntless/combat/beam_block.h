#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/mirror.h"

// The first object in a beam's path: the C++ port of
// engine/appc/beam_blockers.first_blocker (spec docs/superpowers/specs/
// 2026-11-11-beam-blocking-design.md section 4), statement by statement --
// the same candidate order, the same broadphase expression order, double
// arithmetic, `d < best` strict (a tie goes to the earlier candidate, and
// nothing ties the target: `best` starts at contact_dist). Keep the two in
// step: a change to either changes both.
//
// Candidates are the ships list (Object handles, Python's `ships` in list
// order), then the planets (beam_blockers.planet_rows: the shooter set's
// Planets in the set's object order). A ship blocks at its shield bubble
// (shields_block, then shield_bubble_entry nearer than the best so far) or
// at a mesh trace hit; the sphere tier never counts. A planet with an
// instance blocks at a mesh hit only; one without an instance at its sphere
// entry (never when the emitter is inside the sphere).
//
// NeedPython. Every read the existing ports cannot answer exactly as the
// Python would throws NeedPython, never a guess: a candidate or shooter with
// no live row, a candidate without a real IsDead, an unnameable
// `_containing_set`, a non-ShipClass candidate (bubble_bound_radius), a
// non-ShipClass with a real GetShields, an unnameable shield or cloak ref, a
// zero bubble semi-axis, an invalid transform, a candidate's set with no
// view-offset entry while it has an instance, and a candidate listed in
// `python_candidates` (its class overrides a method the walk reads from the
// mirror instead: IsDead, IsHidden, GetWorldLocation, ... -- the caller's
// class flags, native_combat._k2_python_candidates), thrown where the
// Python first calls one of them (its IsDead). Every geometry refusal of
// beam_geometry / projectile_geometry (std::invalid_argument) is rethrown as
// NeedPython. Checks run in the Python's order, so a candidate the Python
// skips early (shooter, target, dead, hidden, another set, out of reach) is
// never asked about.

namespace dauntless::combat {

// beam_blockers.PLANET_BOUND_SLACK
constexpr double kPlanetBoundSlack = 1.02;

// One Planet (a Sun included) of the step, as beam_blockers reads it.
//   set    -- the set whose `_objects` holds it (planet_rows), which is also
//             its frames.containing_set: the feeder must hand only planets
//             for which the two agree (the Python checks both);
//   handle -- its Object row, -1 for none: compared with the shooter and the
//             target (`planet is shooter or planet is target`);
//   centre -- planet.GetWorldLocation();
//   radius -- collisions.world_radius(planet);
//   iid    -- planet_instances.get(planet): nullopt (and !iid_bad) is None;
//   iid_bad -- the entry is not an InstanceId: the mesh path runs, the trace
//             raises inside _resolve_hit_point's try, and the planet does not
//             block (never the sphere path).
struct BeamPlanet {
    int64_t set = -1;
    int64_t handle = -1;
    Vec3 centre{};
    double radius = 0.0;
    std::optional<InstanceId> iid;
    bool iid_bad = false;
};

struct BeamBlockInputs {
    const Mirror& m;
    const TraceHooks& hooks;
    // ship_instances by Object handle (K2Context::iids' meaning).
    const std::unordered_map<int64_t, InstanceRef>& iids;
    // frames.view_offset(set) by Set handle: nullopt = None (no shift).
    const std::unordered_map<int64_t, std::optional<Vec3>>& view_offsets;
    // combat.shields_block's dev cheat and the player's Object handle.
    bool npc_shields_off = false;
    int64_t player = -1;
    // The step's ships (Python's `ships`), in list order.
    const std::vector<int64_t>& ships;
    // Every planet of the step; only those in the shooter's set are read,
    // in this order (which must be each set's object order).
    const std::vector<BeamPlanet>& planets;
    // Candidates only Python may decide (see NeedPython above); null: none.
    const std::unordered_set<int64_t>* python_candidates = nullptr;
};

// beam_blockers.Blocker. `handle` is the ship's Object handle, -1 for a
// planet; `planet` is the planet's index in BeamBlockInputs::planets (-1 for
// a ship). `bubble` is set only for Tier::Bubble.
struct BeamBlocker {
    enum class Kind { Ship, Planet } kind = Kind::Ship;
    int64_t handle = -1;
    int64_t planet = -1;
    double dist = 0.0;
    Vec3 point{};
    std::optional<Vec3> normal;
    std::optional<Vec3> bubble;
    enum class Tier { Mesh, Sphere, Bubble } tier = Tier::Mesh;
};

// The candidate needs an answer only Python has (see above).
struct NeedPython : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// beam_blockers.first_blocker(shooter, target, emitter, aim_unit,
// contact_dist, ships, planet_instances, ship_instances). nullopt: nothing
// blocks. Throws NeedPython.
std::optional<BeamBlocker> first_blocker(const BeamBlockInputs& in,
                                         int64_t shooter, int64_t target,
                                         const Vec3& emitter,
                                         const Vec3& aim_unit,
                                         double contact_dist);

}  // namespace dauntless::combat
