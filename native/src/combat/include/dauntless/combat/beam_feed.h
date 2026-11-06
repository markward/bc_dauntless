#pragma once

#include <array>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/frames_table.h"
#include "dauntless/combat/k2_beams.h"
#include "dauntless/combat/mirror.h"

// The native per-frame beam descriptor feed (phase 6 follow-up 1, plan
// docs/superpowers/plans/2026-11-06-phase6-native-beam-feed.md, Task 3).
//
// build_beam_feed is a line-for-line port of engine/host_loop.py's
// _build_phaser_beam_render_data and _build_tractor_beam_render_data, with
// _firing_banks (the STOCK path only: the system's `_children` in order, the
// banks whose `_firing` is truthy; a patched GetWeapon / IsFiring is not
// honoured, spec Part A), _ViewMemo.set_of, _beam_descriptor_pair,
// _beam_endpoint and _beam_pair_in_view, reading the Mirror. The geometry is
// beam_geometry.h's and beam_trace.h's (the K2 kernel's own ports); the
// engine/systems/frames.py helpers it needs are frames_internal.h's (shared
// with the torpedo feed).
// Every float is the Python's: double, the same operand order, Python's
// `x or d` / max / `** 0.5` (py_math.h), -0.0 kept where the Python keeps it.
//
// Handles: ships are Object rows (-1: a ship with no row), sets Set rows,
// banks and systems Subsystem rows; -1 is Python's None.

namespace dauntless::combat {

struct BeamFeedCtx {
    int64_t view = -1;           // frames.viewing_set() Set handle; -1 none
    Vec3 origin{0, 0, 0};        // frames.render_origin()
    FrameTable frames;           // every registered Set (frames_table.h)
    // ship_instances by target Object handle (K2's table and meaning).
    std::unordered_map<int64_t, K2Context::Iid> iids;
    TraceHooks hooks;
    // dev_combat_cheats.disable_npc_shields_active() and the player's
    // Object handle (-1 None), as K2Context has them.
    bool npc_shields_off = false;
    int64_t player = -1;
    bool use_memo = false;       // step_memo.active()
    // host_loop's PHASER_BEAM_WIDTH_MUTATOR, PHASER_BEAM_BRIGHTNESS,
    // TRACTOR_BEAM_BRIGHTNESS and TRACTOR_BEAM_END_WIDTH_SCALE.
    double width_mutator = 0.0, phaser_brightness = 0.0,
           tractor_brightness = 0.0, tractor_end_width_scale = 0.0;
};

// One descriptor dict of the Python builders, before beam_from_dict.
struct BeamOut {
    Vec3 emitter, target;  // RENDER space
    std::array<double, 4> color;
    double width, u_tiles;
    int64_t num_sides;
    double taper_radius, taper_ratio, taper_min_length, taper_max_length,
        perimeter_tile, texture_speed, end_width_scale;
};

// Why the feed skipped an item (phase 6 follow-up 4: no Python fallback).
// An item is one bank's pair, or every pair of one ship's walk where the
// refusal is the ship's own (its row, class, set or frame): counted once per
// walk (the phaser walk and the tractor walk each count it). The reasons:
//   ShipRow        a ship with no live Object row (-1, stale, freed)
//   NotShipClass   a ship that is not a ShipClass (a stub answers Python's
//                  hasattr(ship, "GetPhaserSystem"))
//   TargetRow      a bank's _target that names no live Object
//   ContainingSet  a _containing_set the mirror cannot name
//   Frames         a set missing from ctx.frames, or a set handle unnamed
//   PartStale      a posed mount whose part slot is not current
//   MountUnknown   a Manual Aim pick on a posed target whose mount the mirror
//                  cannot tell
//   ColourUnset    a bank's outer shell or inner core colour unset
//   Shields        a non-ShipClass target with a REAL GetShields (no port)
//   Geometry       any other refusal of the geometry (beam_geometry.h)
//   Error          any other exception (none is known to be reachable)
enum class BeamSkip : int {
    ShipRow,
    NotShipClass,
    TargetRow,
    ContainingSet,
    Frames,
    PartStale,
    MountUnknown,
    ColourUnset,
    Shields,
    Geometry,
    Error,
    kCount
};
const char* beam_skip_name(BeamSkip w);
using BeamSkips = std::array<int64_t, static_cast<size_t>(BeamSkip::kCount)>;

// The phaser list into `phasers` and the tractor list into `tractors`
// (both cleared first), in the Python's order: per ship in `ships` order,
// per firing bank in `_children` order, the outer shell then the inner core.
// Phasers carry end_width_scale 1.0 (beam_from_dict's default), tractors
// ctx.tractor_end_width_scale.
//
// Never throws for what the mirror holds: wherever it cannot answer as the
// Python would, that one item is skipped and counted in `skips` (zeroed
// first) under its BeamSkip, and every other item is built. An item is
// appended only once it is whole, so a skip leaves no half pair.
//
// A target that is not a ShipClass is answered as combat.shields_block
// answers it when its GetShields is TGObject's stub (has_real_get_shields
// 0): the stub, HasShields() and IsOn() are truthy, IsDisabled() is truthy,
// so False -- the beam ends on the hull trace, the sphere or the aim point
// as for any unshielded target.
void build_beam_feed(Mirror& m, const std::vector<int64_t>& ships,
                     const BeamFeedCtx& ctx, std::vector<BeamOut>& phasers,
                     std::vector<BeamOut>& tractors, BeamSkips& skips);

}  // namespace dauntless::combat
