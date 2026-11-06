#pragma once

// engine/systems/frames.py's point helpers over a FrameTable, shared by the
// native render feeds (beam_feed.cc, torpedo_feed.cc). Internal to the combat
// library; included only AFTER the including source's
// `#pragma clang fp contract(off)`.
//
// Every helper throws std::invalid_argument ("answer in Python") where the
// table cannot answer as frames.py would: a set handle with no live Set row,
// or a set missing from the table. -1 is Python's None.

#include <optional>
#include <stdexcept>
#include <string>

#include "dauntless/combat/frames_table.h"
#include "dauntless/combat/mirror.h"
#include "geometry_internal.h"

namespace dauntless::combat::detail {

[[noreturn]] inline void frames_fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat frames: ") + why +
                                " -- answer in Python");
}

// frame_of(pSet): None for a non-set; else the set's entry in the table.
inline const BeamFrame* frame_of(const Mirror& m, const FrameTable& frames,
                                 int64_t s) {
    if (s == -1) return nullptr;
    if (s < 0 || !m.set(s)) frames_fall_back("set handle unnamed");
    const auto it = frames.find(s);
    if (it == frames.end())
        frames_fall_back("set missing from the frames table");
    return &it->second;
}

// offset_between(set_a, set_b): `set_a is set_b` -> _ZERO when it is a Set
// (without resolving its frame), else None; different frames -> None; else
// tuple(b - a for a, b in zip(fa.anchor_gu, fb.anchor_gu)).
inline std::optional<Vec3> offset_between(const Mirror& m,
                                          const FrameTable& frames, int64_t a,
                                          int64_t b) {
    if (a == b) {
        if (a == -1) return std::nullopt;
        if (a < 0 || !m.set(a)) frames_fall_back("set handle unnamed");
        return Vec3{0.0, 0.0, 0.0};
    }
    const BeamFrame* fa = frame_of(m, frames, a);
    const BeamFrame* fb = frame_of(m, frames, b);
    if (!fa || !fb || fa->id != fb->id) return std::nullopt;
    return Vec3{fb->anchor[0] - fa->anchor[0], fb->anchor[1] - fa->anchor[1],
                fb->anchor[2] - fa->anchor[2]};
}

// in_view(view, pSet, x, y, z): None outside the viewed frame; the point
// untouched for an offset `== _ZERO` (so -0.0 counts, and a -0.0 coordinate
// survives); else p + off per axis.
inline std::optional<Vec3> in_view(const Mirror& m, const FrameTable& frames,
                                   int64_t view, int64_t pset, const Vec3& p) {
    const std::optional<Vec3> off = offset_between(m, frames, view, pset);
    if (!off) return std::nullopt;
    if (is_zero_offset(*off)) return p;
    return Vec3{p[0] + (*off)[0], p[1] + (*off)[1], p[2] + (*off)[2]};
}

// view_to_render(p) for a point (not None): p untouched when the origin
// `== _ZERO`, else p - origin per axis.
inline Vec3 view_to_render(const Vec3& origin, const Vec3& p) {
    if (is_zero_offset(origin)) return p;
    return Vec3{p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]};
}

// to_render(view, pSet, x, y, z) = view_to_render(in_view(...)).
inline std::optional<Vec3> to_render(const Mirror& m, const FrameTable& frames,
                                     const Vec3& origin, int64_t view,
                                     int64_t pset, const Vec3& p) {
    const std::optional<Vec3> v = in_view(m, frames, view, pset, p);
    if (!v) return std::nullopt;
    return view_to_render(origin, *v);
}

// view_offset(pSet): offset_between(viewing_set(), pSet), None for None or
// _ZERO (and for pSet None).
inline std::optional<Vec3> view_offset(const Mirror& m,
                                       const FrameTable& frames, int64_t view,
                                       int64_t pset) {
    if (pset == -1) return std::nullopt;
    const std::optional<Vec3> off = offset_between(m, frames, view, pset);
    if (!off || is_zero_offset(*off)) return std::nullopt;
    return off;
}

}  // namespace dauntless::combat::detail
