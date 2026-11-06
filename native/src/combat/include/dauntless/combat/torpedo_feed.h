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
// build_torpedo_feed is the only builder of the torpedo descriptors and the
// torpedo lights: there is no Python copy. It began as a line-for-line port
// of engine/host_loop.py's Python torpedo and torpedo-light builders, which
// phase 6 follow-up 4 deleted once their output was recorded as the render
// goldens (tests/fixtures/render_goldens/, checked by tests/host/
// test_native_torpedo_feed.py). It reads the K3 torpedo table
// (torpedo_table.h) and each row's visual record (TorpedoVisual:
// Torpedo.__init__'s default, pushed at row-add, replaced at Create*Model):
// the quad colours dimmed by the brightness knob, `forward` the unit velocity
// ((0, 0, 1) when ~stationary), one light per non-disruptor torpedo with a
// glow radius, faded by camera_fade (host_loop._camera_distance_fade, which
// the emitter lights still use). Positions are the rows'
// TransformStore slots (GetTranslate: the live store, never a published
// pose); the frames.py helpers are frames_internal.h's, shared with the beam
// feed. Every float is as the Python builders made it: double, the same
// operand order, `** 0.5` through py_pow, math.sqrt as std::sqrt, -0.0 kept.
//
// budget_lights is the per-category light budget; it has no Python copy
// either (the old host_loop blend was deleted with the builders).

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

// One torpedo descriptor (set_torpedoes' dict), before the float casts.
// `visual` points into the table row: valid until the table next changes.
struct TorpedoOut {
    const TorpedoVisual* visual = nullptr;
    Vec3 position{0, 0, 0};      // RENDER space
    std::array<double, 4> core_color{}, glow_color{}, flares_color{};
    double age = 0.0;
    Vec3 forward{0, 0, 1};
};

// One torpedo light (a set_dynamic_lights point light).
struct TorpedoLightOut {
    Vec3 position{0, 0, 0};      // RENDER space
    std::array<double, 3> color{};
    double radius = 0.0, intensity = 0.0;
};

// Why the feed skipped an item (phase 6 follow-up 4: no Python fallback).
// An item is one torpedo: its descriptor AND its light. The reasons:
//   Rows             entries of projectiles._active with no live row (the
//                    count is the difference from ctx.expected_rows)
//   Unrepresentable  a row whose _age / _velocity / _containing_set the row
//                    could not hold
//   NoVisual         a row with no visual record (every Torpedo has one
//                    from Torpedo.__init__; Create*Model replaces it)
//   Transform        a dead or missing transform slot
//   ContainingSet    a _containing_set ref whose row is gone
//   Frames           a set missing from ctx.frames, or a set handle unnamed
//   CInt             num_flares or id outside a C int (set_torpedoes' cast)
//   Error            any other exception (none is known to be reachable)
enum class TorpedoSkip : int {
    Rows,
    Unrepresentable,
    NoVisual,
    Transform,
    ContainingSet,
    Frames,
    CInt,
    Error,
    kCount
};
const char* torpedo_skip_name(TorpedoSkip w);
using TorpedoSkips =
    std::array<int64_t, static_cast<size_t>(TorpedoSkip::kCount)>;

// The descriptors into `torps` and the torpedo lights into `lights` (both
// cleared first), each in table (= projectiles._active) order. No view: both
// empty, nothing checked.
//
// Never throws for what the table holds: wherever it cannot answer as the
// Python would, that one torpedo (descriptor and light) is skipped and
// counted in `skips` (zeroed first), and every other torpedo is built. A
// torpedo is appended only once it is whole.
void build_torpedo_feed(const Mirror& m, const TorpedoFeedCtx& ctx,
                        std::vector<TorpedoOut>& torps,
                        std::vector<TorpedoLightOut>& lights,
                        TorpedoSkips& skips);

// The light blend's caps: host_loop's _LIGHT_CAP and the three budgets.
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
