// native/src/renderer/planet_clipmap_schedule.cc
#include "renderer/planet_clipmap_schedule.h"

#include <algorithm>
#include <cmath>

namespace renderer::planet_detail {

namespace {

Rect isect(Rect a, Rect b) {
    Rect r{std::max(a.x0, b.x0), std::max(a.y0, b.y0), std::min(a.x1, b.x1), std::min(a.y1, b.y1)};
    if (r.empty()) return Rect{};
    return r;
}

bool same(const Rect& a, const Rect& b) {
    return a.x0 == b.x0 && a.y0 == b.y0 && a.x1 == b.x1 && a.y1 == b.y1;
}

// True modulo (not C++ `%`, which can return negative for negative `a`).
int mod1024(int a) {
    int m = a % kLevelSize;
    return m < 0 ? m + kLevelSize : m;
}

}  // namespace

int level_count_for(float R_gu, float ts0_gu) {
    for (int n = kMaxLevels; n >= 1; --n) {
        float half_extent = 512.0f * ts0_gu * (float)(1 << (n - 1));
        if (half_extent <= R_gu) return n;
    }
    return 1;
}

bool needs_reanchor(glm::vec2 nadir_plane_gu, float R_gu) {
    return glm::length(nadir_plane_gu) > 0.5f * R_gu;
}

ClipmapSchedule::ClipmapSchedule(float ts0_gu, std::vector<int> octaves_per_level)
    : ts0_gu_(ts0_gu), octaves_(std::move(octaves_per_level)), valid_(octaves_.size()) {}

void ClipmapSchedule::reset() {
    for (auto& v : valid_) v = Rect{};
}

float ClipmapSchedule::texel_gu(int level) const { return ts0_gu_ * (float)(1 << level); }

int ClipmapSchedule::levels() const { return (int)octaves_.size(); }

Rect ClipmapSchedule::target(int level, glm::vec2 nadir_plane_gu) const {
    float ts = texel_gu(level);
    int cx = (int)std::floor(nadir_plane_gu.x / ts);
    int cy = (int)std::floor(nadir_plane_gu.y / ts);
    return Rect{cx - kLevelSize / 2, cy - kLevelSize / 2, cx + kLevelSize / 2, cy + kLevelSize / 2};
}

const Rect& ClipmapSchedule::valid(int level) const { return valid_[level]; }

bool ClipmapSchedule::complete(glm::vec2 nadir_plane_gu) const {
    for (int L = 0; L < levels(); ++L) {
        if (!same(valid_[L], target(L, nadir_plane_gu))) return false;
    }
    return true;
}

// Splits `strip` by toroidal wrap into <=4 pieces (<=2 in x, <=2 in y), each
// written at its toroidal (tor_x, band_row) destination. A piece that lands
// on the top content row (toroidal row kLevelSize-1) or the bottom content
// row (toroidal row 0) also emits a 1-row guard copy at band_row 0 or
// kBandRows-1 respectively, so the sample pass can filter across the wrap
// seam without branching. Guard texels cost the same as content texels.
void ClipmapSchedule::emit(int level, Rect strip, long long& left, std::vector<BakeRect>& out) {
    const int cost_per_texel = octaves_[level];
    for (int ys = strip.y0; ys < strip.y1;) {
        const int ty = mod1024(ys);
        const int hh = std::min(strip.y1 - ys, kLevelSize - ty);
        for (int xs = strip.x0; xs < strip.x1;) {
            const int tx = mod1024(xs);
            const int ww = std::min(strip.x1 - xs, kLevelSize - tx);

            out.push_back(BakeRect{level, xs, ys, tx, ty + 1, ww, hh});
            left -= (long long)ww * hh * cost_per_texel;

            if (ty + hh - 1 == kLevelSize - 1) {
                // This piece's last row is toroidal row 1023: mirror it to
                // the guard row above band row 1 (band row 0).
                out.push_back(BakeRect{level, xs, ys + hh - 1, tx, 0, ww, 1});
                left -= (long long)ww * cost_per_texel;
            }
            if (ty == 0) {
                // This piece's first row is toroidal row 0: mirror it to the
                // guard row below band row 1024 (band row kBandRows-1).
                out.push_back(BakeRect{level, xs, ys, tx, kBandRows - 1, ww, 1});
                left -= (long long)ww * cost_per_texel;
            }

            xs += ww;
        }
        ys += hh;
    }
}

long long ClipmapSchedule::update(glm::vec2 nadir_plane_gu, long long budget, std::vector<BakeRect>& out) {
    long long left = budget;

    for (int L = levels() - 1; L >= 0 && left > 0; --L) {
        const Rect D = target(L, nadir_plane_gu);
        Rect& B = valid_[L];
        B = isect(B, D);
        if (B.empty()) {
            const int cy = (D.y0 + D.y1) / 2;
            B = Rect{D.x0, cy, D.x1, cy};
        }

        const int cost = octaves_[L];
        while (left > 0 && !same(B, D)) {
            int h = B.y1 - B.y0;
            int w = B.x1 - B.x0;
            if (h == 0) {
                B.x0 = D.x0;
                B.x1 = D.x1;
                w = B.x1 - B.x0;
            }

            Rect s;
            if (h > 0 && B.x0 > D.x0) {
                long long k = std::min<long long>(B.x0 - D.x0, std::max<long long>(1, left / ((long long)h * cost)));
                s = Rect{B.x0 - (int)k, B.y0, B.x0, B.y1};
                B.x0 -= (int)k;
            } else if (h > 0 && B.x1 < D.x1) {
                long long k = std::min<long long>(D.x1 - B.x1, std::max<long long>(1, left / ((long long)h * cost)));
                s = Rect{B.x1, B.y0, B.x1 + (int)k, B.y1};
                B.x1 += (int)k;
            } else if (B.y0 > D.y0 && (B.y0 - D.y0 >= D.y1 - B.y1)) {
                long long k = std::min<long long>(B.y0 - D.y0, std::max<long long>(1, left / ((long long)w * cost)));
                s = Rect{B.x0, B.y0 - (int)k, B.x1, B.y0};
                B.y0 -= (int)k;
            } else {
                long long k = std::min<long long>(D.y1 - B.y1, std::max<long long>(1, left / ((long long)w * cost)));
                s = Rect{B.x0, B.y1, B.x1, B.y1 + (int)k};
                B.y1 += (int)k;
            }

            emit(L, s, left, out);
        }
    }

    return budget - left;
}

}  // namespace renderer::planet_detail
