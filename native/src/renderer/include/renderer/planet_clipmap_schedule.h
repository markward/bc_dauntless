// native/src/renderer/include/renderer/planet_clipmap_schedule.h
#pragma once

#include <vector>

#include <glm/glm.hpp>

// GL-free scheduler for the planet surface-detail toroidal clipmap: a stack
// of up to kMaxLevels square levels, each kLevelSize texels per side, doubling
// texel size per level. Each level's GPU texture is really a torus-wrapped
// "band" of kBandRows rows (kLevelSize content rows plus one guard row above
// and one below, each a content copy of the opposite edge row so the sample
// pass can filter across the wrap seam without branching). This header is
// GL-free by design: it only ever decides WHAT to bake (as BakeRect, an
// absolute-texel source + a toroidal-band destination) and WHEN (a per-frame
// cost budget in texels x octaves). A later task turns each BakeRect into a
// scissored GL draw.
namespace renderer::planet_detail {

constexpr int kLevelSize = 1024;
constexpr int kBandRows  = 1026;      // 1024 + two guard rows
constexpr int kMaxLevels = 5;

/// An absolute-texel rectangle, right/top-exclusive ([x0,x1) x [y0,y1)).
struct Rect {
    int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool empty() const { return x0 >= x1 || y0 >= y1; }
    long long area() const { return empty() ? 0 : (long long)(x1 - x0) * (y1 - y0); }
};

// One scissored draw into one level's band. abs_* = absolute texel index of the
// piece's lower-left texel; tor_x in [0,1024), band_row in [0,1026).
struct BakeRect { int level; int abs_x, abs_y; int tor_x, band_row; int w, h; };

/// Largest n <= kMaxLevels with 512*ts0*2^(n-1) <= R_gu; minimum 1.
int  level_count_for(float R_gu, float ts0_gu);

/// True once the camera's nadir (in the anchor's tangent plane, GU) has
/// drifted more than half the planet's radius from the anchor — the caller
/// should re-anchor and reset the schedule.
bool needs_reanchor(glm::vec2 nadir_plane_gu, float R_gu);

/// Owns, per level, the absolute-texel rect that is currently baked ("valid")
/// and grows it toward the 1024^2 window centred on the live nadir texel,
/// coarsest level first, spending at most `budget` cost units (texels times
/// that level's octave count) per `update` call.
class ClipmapSchedule {
public:
    ClipmapSchedule(float ts0_gu, std::vector<int> octaves_per_level);   // size = level count

    void reset();                                                        // all valid rects empty

    // Grow valid rects toward the targets around `nadir`, coarse level first,
    // until `budget` cost units (texels x octaves) are spent. Appends draws to
    // `out`. Returns the cost spent. Never exceeds budget by more than one strip.
    long long update(glm::vec2 nadir_plane_gu, long long budget, std::vector<BakeRect>& out);

    Rect target(int level, glm::vec2 nadir_plane_gu) const;   // 1024^2 centred on the nadir texel
    const Rect& valid(int level) const;
    bool complete(glm::vec2 nadir_plane_gu) const;            // every valid == target
    int  levels() const;
    float texel_gu(int level) const;                          // ts0 * 2^level

private:
    void emit(int level, Rect strip, long long& left, std::vector<BakeRect>& out);

    float ts0_gu_;
    std::vector<int> octaves_;
    std::vector<Rect> valid_;
};

}  // namespace renderer::planet_detail
