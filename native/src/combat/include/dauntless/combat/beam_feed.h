#pragma once

#include <array>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/beam_trace.h"
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
// engine/systems/frames.py helpers it needs are file-local in beam_feed.cc.
// Every float is the Python's: double, the same operand order, Python's
// `x or d` / max / `** 0.5` (py_math.h), -0.0 kept where the Python keeps it.
//
// Handles: ships are Object rows (-1: a ship with no row), sets Set rows,
// banks and systems Subsystem rows; -1 is Python's None.

namespace dauntless::combat {

// frames.frame_of(set): the frame's key as a small id (two sets share a
// frame exactly when their ids are equal) and its anchor_gu.
struct BeamFrame {
    int64_t id;
    Vec3 anchor;
};

struct BeamFeedCtx {
    int64_t view = -1;           // frames.viewing_set() Set handle; -1 none
    Vec3 origin{0, 0, 0};        // frames.render_origin()
    std::unordered_map<int64_t, BeamFrame> frames;  // every registered Set
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

// The phaser list into `phasers` and the tractor list into `tractors`
// (both cleared first), in the Python's order: per ship in `ships` order,
// per firing bank in `_children` order, the outer shell then the inner core.
// Phasers carry end_width_scale 1.0 (beam_from_dict's default), tractors
// ctx.tractor_end_width_scale.
//
// Throws std::invalid_argument wherever the mirror cannot answer as the
// Python would: a -1 ship (or one that is not a ShipClass), a set missing
// from ctx.frames, an unset colour, an unrepresentable or stale ref, and
// every throw of the geometry it calls. The outputs are then partial: the
// caller discards both.
void build_beam_feed(Mirror& m, const std::vector<int64_t>& ships,
                     const BeamFeedCtx& ctx, std::vector<BeamOut>& phasers,
                     std::vector<BeamOut>& tractors);

}  // namespace dauntless::combat
