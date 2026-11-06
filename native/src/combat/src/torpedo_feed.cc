// build_torpedo_feed / budget_lights (torpedo_feed.h): the torpedo render
// feed and the light budget over the K3 torpedo table. There is no Python
// copy: the Python builders and blend they were ported from were deleted
// (phase 6 follow-up 4), and the inline Python quotes below are their lines,
// kept as the record of what each block reproduces. The render goldens
// (tests/fixtures/render_goldens/) are the truth.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/torpedo_feed.h"

#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>

#include "dauntless/combat/py_math.h"
#include "frames_internal.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

// The feed's refusals: the torpedo is skipped, counted under `why`.
struct Skip : std::invalid_argument {
    TorpedoSkip why;
    Skip(TorpedoSkip w, const std::string& what)
        : std::invalid_argument("combat torpedo feed: " + what), why(w) {}
};

[[noreturn]] void skip(TorpedoSkip why, const std::string& what) {
    throw Skip(why, what);
}

constexpr uint32_t bit(TorpField f) { return 1u << static_cast<int>(f); }

// What the builders read of a row's mirrored fields.
constexpr uint32_t kReads = bit(TorpField::_age) | bit(TorpField::_velocity) |
                            bit(TorpField::_containing_set);

// set_torpedoes' `d["num_flares"].cast<int>()` / `d["id"].cast<int>()`.
bool fits_c_int(int64_t v) {
    return v >= std::numeric_limits<int>::min() &&
           v <= std::numeric_limits<int>::max();
}

// A colour dimmed: (c[0] * scale, c[1] * scale, c[2] * scale, c[3]).
std::array<double, 4> dim(const TorpedoVisual::Color& c, double s) {
    return {c[0] * s, c[1] * s, c[2] * s, c[3]};
}

// The drawn forward: the unit velocity, (0, 0, 1) when ~stationary (the
// disruptor's default velocity, a torpedo not yet advanced).
Vec3 forward(const Vec3& v) {
    const double mag = py_pow(v[0] * v[0] + v[1] * v[1] + v[2] * v[2], 0.5);
    if (mag < 1e-6) return {0.0, 0.0, 1.0};
    return {v[0] / mag, v[1] / mag, v[2] / mag};
}

// host_loop._camera_distance_fade(position) (the emitter lights' Python
// gate): nullopt is Python's None (culled).
std::optional<double> camera_fade(const TorpedoFeedCtx& ctx, const Vec3& p) {
    if (!ctx.eye) return 1.0;
    const Vec3& eye = *ctx.eye;
    const double dx = p[0] - eye[0];
    const double dy = p[1] - eye[1];
    const double dz = p[2] - eye[2];
    const double d2 = dx * dx + dy * dy + dz * dz;
    if (d2 >= ctx.cull * ctx.cull) return std::nullopt;
    if (d2 <= ctx.fade_start * ctx.fade_start) return 1.0;
    const double t =
        (std::sqrt(d2) - ctx.fade_start) / (ctx.cull - ctx.fade_start);
    return 1.0 - t * t * (3.0 - 2.0 * t);
}

}  // namespace

namespace {

// One row's descriptor and (optional) light, built whole before either is
// appended. `has_torp` false: outside the viewed frame (Python builds
// neither then, the light needing the view position too).
struct Item {
    bool has_torp = false, has_light = false;
    TorpedoOut torp;
    TorpedoLightOut light;
};

Item build_item(const Mirror& m, const TorpedoFeedCtx& ctx,
                const TorpedoRow& r) {
    Item it;
    if (r.unrepresentable & kReads)
        skip(TorpedoSkip::Unrepresentable,
             "a field the feed reads is unrepresentable");
    if (!r.visual_set)
        skip(TorpedoSkip::NoVisual, "a torpedo has no visual record");
    const TorpedoVisual& v = r.visual;
    // p = t.GetTranslate(): the live store slot.
    const TransformStore& store = m.store();
    if (r.xform_index < 0 || r.xform_gen < 0 ||
        r.xform_index > std::numeric_limits<uint32_t>::max() ||
        r.xform_gen > std::numeric_limits<uint32_t>::max())
        skip(TorpedoSkip::Transform, "a torpedo has no transform");
    const auto xi = static_cast<uint32_t>(r.xform_index);
    const auto xg = static_cast<uint32_t>(r.xform_gen);
    if (!store.valid(xi, xg))
        skip(TorpedoSkip::Transform, "a torpedo transform is invalid");
    const Vec3 p = store.position(xi, xg);
    // _frames.containing_set(t): the row's ref, re-checked live.
    const int64_t cset = m.torpedo_ref(r, TorpField::_containing_set);
    if (cset == kRefUnrepresentable)
        skip(TorpedoSkip::ContainingSet, "_containing_set unnamed");
    // pos = in_view(...) -- both builders' first step (to_render is
    // view_to_render of it).
    const std::optional<Vec3> view_pos =
        detail::in_view(m, ctx.frames, ctx.view, cset, p);
    if (!view_pos) return it;
    if (!fits_c_int(v.num_flares) || !fits_c_int(v.id))
        skip(TorpedoSkip::CInt, "num_flares or id outside a C int");
    TorpedoOut& o = it.torp;
    o.visual = &v;
    o.position = detail::view_to_render(ctx.origin, *view_pos);
    // Core, glow, flares dimmed by the knob (the bolt colours are not).
    o.core_color = dim(v.core_color, ctx.brightness);
    o.glow_color = dim(v.glow_color, ctx.brightness);
    o.flares_color = dim(v.flares_color, ctx.brightness);
    o.age = r.age;
    o.forward = forward(r.vel);
    it.has_torp = true;
    // The torpedo's light: none for a disruptor or a zero glow radius.
    if (v.is_disruptor) return it;
    const double radius = ctx.light_radius_scale * v.light_base;
    if (radius <= 0) return it;
    const std::optional<double> fade = camera_fade(ctx, *view_pos);
    if (!fade) return it;  // beyond the cull distance: not built at all
    TorpedoLightOut& l = it.light;
    l.position = detail::view_to_render(ctx.origin, *view_pos);
    l.color = {v.glow_color[0], v.glow_color[1], v.glow_color[2]};
    l.radius = radius;
    l.intensity = ctx.light_intensity * *fade;
    it.has_light = true;
    return it;
}

}  // namespace

const char* torpedo_skip_name(TorpedoSkip w) {
    switch (w) {
        case TorpedoSkip::Rows: return "rows";
        case TorpedoSkip::Unrepresentable: return "unrepresentable";
        case TorpedoSkip::NoVisual: return "no_visual";
        case TorpedoSkip::Transform: return "transform";
        case TorpedoSkip::ContainingSet: return "containing_set";
        case TorpedoSkip::Frames: return "frames";
        case TorpedoSkip::CInt: return "c_int";
        case TorpedoSkip::Error: return "error";
        case TorpedoSkip::kCount: break;
    }
    return "?";
}

void build_torpedo_feed(const Mirror& m, const TorpedoFeedCtx& ctx,
                        std::vector<TorpedoOut>& torps,
                        std::vector<TorpedoLightOut>& lights,
                        TorpedoSkips& skips) {
    torps.clear();
    lights.clear();
    skips.fill(0);
    // view = _frames.viewing_set(); if view is None: return out (both).
    if (ctx.view == -1) return;
    const TorpedoTable& table = m.torpedoes();
    // An entry of projectiles._active with no row (not a Torpedo, or one
    // the table lost) is not drawn: counted, never fatal.
    if (ctx.expected_rows >= 0) {
        const auto live = static_cast<int64_t>(table.size());
        if (live != ctx.expected_rows) {
            const int64_t d = ctx.expected_rows - live;
            skips[static_cast<size_t>(TorpedoSkip::Rows)] += d < 0 ? -d : d;
        }
    }
    // `for t in projectiles._active:` -- both builders walk the same list in
    // the same order, and read nothing either changes, so one walk builds
    // both lists.
    for (const TorpedoRow& r : table.rows()) {
        if (!r.alive) continue;
        Item it;
        TorpedoSkip why = TorpedoSkip::Error;
        bool ok = false;
        try {
            it = build_item(m, ctx, r);
            ok = true;
        } catch (const Skip& e) {
            why = e.why;
        } catch (const detail::FramesUnanswerable&) {
            why = TorpedoSkip::Frames;
        } catch (const std::exception&) {
            why = TorpedoSkip::Error;
        }
        if (!ok) {
            ++skips[static_cast<size_t>(why)];
            continue;
        }
        if (it.has_torp) torps.push_back(it.torp);
        if (it.has_light) lights.push_back(it.light);
    }
}

namespace {

// items[a:z] for a list of n: Python's slice bounds, clamped into [0, n].
std::pair<int64_t, int64_t> py_slice(int64_t n, int64_t a, int64_t z) {
    auto norm = [n](int64_t x) {
        if (x < 0) {
            x += n;
            if (x < 0) x = 0;
        } else if (x > n) {
            x = n;
        }
        return x;
    };
    return {norm(a), norm(z)};
}

}  // namespace

std::vector<LightPick> budget_lights(std::size_t n_explosions,
                                     std::size_t n_torpedoes,
                                     std::size_t n_emitters,
                                     const LightBudget& b) {
    const int64_t n[3] = {static_cast<int64_t>(n_explosions),
                          static_cast<int64_t>(n_torpedoes),
                          static_cast<int64_t>(n_emitters)};
    const int64_t budget[3] = {b.explosions, b.torpedoes, b.emitters};
    std::vector<LightPick> out;
    // for items, budget in groups: out.extend(items[:budget])
    for (int g = 0; g < 3; ++g) {
        const auto [lo, hi] = py_slice(n[g], 0, budget[g]);
        for (int64_t i = lo; i < hi; ++i)
            out.push_back({g, static_cast<std::size_t>(i)});
    }
    // for items, budget in groups: room = cap - len(out); if room <= 0:
    // break; out.extend(items[budget:budget + room])
    for (int g = 0; g < 3; ++g) {
        const int64_t room = b.cap - static_cast<int64_t>(out.size());
        if (room <= 0) break;
        const auto [lo, hi] = py_slice(n[g], budget[g], budget[g] + room);
        for (int64_t i = lo; i < hi; ++i)
            out.push_back({g, static_cast<std::size_t>(i)});
    }
    return out;
}

}  // namespace dauntless::combat
