#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

#include "dauntless/combat/frames_table.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/torpedo_table.h"

// The native per-frame torpedo feed (phase 6 follow-up 1b, plan
// docs/superpowers/plans/2026-11-06-phase6-native-torpedo-feed.md, Task 3).
//
// build_torpedo_feed is a line-for-line port of engine/host_loop.py's
// _build_torpedo_render_data and _build_dynamic_light_render_data (with
// _torpedo_colors, _dim_color, _torpedo_forward and _camera_distance_fade),
// reading the K3 torpedo table (torpedo_table.h) and each row's visual record
// (TorpedoVisual, pushed once at Create*Model). Positions are the rows'
// TransformStore slots (GetTranslate: the live store, never a published
// pose); the frames.py helpers are frames_internal.h's, shared with the beam
// feed. Every float is the Python's: double, the same operand order, `** 0.5`
// through py_pow, math.sqrt as std::sqrt, -0.0 kept where Python keeps it.
//
// budget_lights is _budgeted_dynamic_lights' slicing, exactly.

namespace dauntless::combat {

struct TorpedoFeedCtx {
    int64_t view = -1;           // frames.viewing_set() Set handle; -1 none
    Vec3 origin{0, 0, 0};        // frames.render_origin()
    FrameTable frames;           // every registered Set
    // host_loop's knobs, read per frame: TORPEDO_BRIGHTNESS,
    // _TORPEDO_LIGHT_RADIUS_SCALE, _TORPEDO_LIGHT_INTENSITY,
    // DYN_LIGHT_FADE_START_GU and DYN_LIGHT_CULL_GU.
    double brightness = 0.0, light_radius_scale = 0.0, light_intensity = 0.0,
           fade_start = 0.0, cull = 0.0;
    std::optional<Vec3> eye;     // host_loop._last_camera_eye (None: nullopt)
    // len(projectiles._active): the live rows must number exactly this (an
    // entry with no row -- not a Torpedo -- is Python's alone). -1: unchecked.
    int64_t expected_rows = -1;
};

// One _build_torpedo_render_data dict, before set_torpedoes' float casts.
// `visual` points into the table row: valid until the table next changes.
struct TorpedoOut {
    const TorpedoVisual* visual = nullptr;
    Vec3 position{0, 0, 0};      // RENDER space
    std::array<double, 4> core_color{}, glow_color{}, flares_color{};
    double age = 0.0;
    Vec3 forward{0, 0, 1};
};

// One _build_dynamic_light_render_data dict.
struct TorpedoLightOut {
    Vec3 position{0, 0, 0};      // RENDER space
    std::array<double, 3> color{};
    double radius = 0.0, intensity = 0.0;
};

// A live row with no visual record (its model never pushed one): the feed
// cannot answer. Counted apart from the other fall-backs.
struct MissingVisual : std::invalid_argument {
    using std::invalid_argument::invalid_argument;
};

// The descriptors into `torps` and the torpedo lights into `lights` (both
// cleared first), each in table (= projectiles._active) order. No view: both
// empty, nothing checked.
//
// Throws std::invalid_argument wherever the table cannot answer as the
// Python would: a row count that is not ctx.expected_rows, a row with an
// unrepresentable `_age` / `_velocity` / `_containing_set` (or a stale set
// ref), a dead transform slot, a set missing from ctx.frames, a num_flares or
// id outside a C int (set_torpedoes' cast); MissingVisual for a row with no
// visual record. The outputs are then partial: the caller discards both.
void build_torpedo_feed(const Mirror& m, const TorpedoFeedCtx& ctx,
                        std::vector<TorpedoOut>& torps,
                        std::vector<TorpedoLightOut>& lights);

// _budgeted_dynamic_lights' blend: _LIGHT_CAP and the three budgets.
struct LightBudget {
    int64_t cap = 64, explosions = 10, torpedoes = 10, emitters = 40;
};

// One entry of the blended list: group 0 explosions, 1 torpedoes, 2 emitters,
// and the index into that group's list.
struct LightPick {
    int group;
    std::size_t index;
    bool operator==(const LightPick&) const = default;
};

// The blended list, in order: explosions[:be], torpedoes[:bt],
// emitters[:bm], then each group's spill items[b:b + room] while
// room = cap - len(out) > 0 -- Python slice semantics, negative bounds
// included.
std::vector<LightPick> budget_lights(std::size_t n_explosions,
                                     std::size_t n_torpedoes,
                                     std::size_t n_emitters,
                                     const LightBudget& b);

}  // namespace dauntless::combat
