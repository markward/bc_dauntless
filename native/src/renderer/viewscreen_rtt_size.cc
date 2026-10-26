// native/src/renderer/viewscreen_rtt_size.cc
#include "renderer/viewscreen_rtt_size.h"

#include <algorithm>
#include <cmath>

namespace renderer::viewscreen_rtt {

std::optional<PixelExtent> projected_extent_px(const glm::mat4& view_proj,
                                               const glm::mat4& world,
                                               glm::vec3 lo, glm::vec3 hi,
                                               int fw, int fh) {
    const glm::mat4 m = view_proj * world;
    glm::vec2 ndc_min(1e30f), ndc_max(-1e30f);
    int behind = 0;
    for (int i = 0; i < 8; ++i) {
        const glm::vec3 corner((i & 1) ? hi.x : lo.x,
                               (i & 2) ? hi.y : lo.y,
                               (i & 4) ? hi.z : lo.z);
        const glm::vec4 c = m * glm::vec4(corner, 1.0f);
        if (c.w <= 1e-6f) { ++behind; continue; }
        const glm::vec2 ndc(c.x / c.w, c.y / c.w);
        ndc_min = glm::min(ndc_min, ndc);
        ndc_max = glm::max(ndc_max, ndc);
    }
    if (behind == 8) return std::nullopt;
    if (behind > 0) {
        return PixelExtent{static_cast<float>(fw), static_cast<float>(fh)};
    }
    ndc_min = glm::max(ndc_min, glm::vec2(-1.0f));
    ndc_max = glm::min(ndc_max, glm::vec2(1.0f));
    if (ndc_max.x <= ndc_min.x || ndc_max.y <= ndc_min.y) return std::nullopt;
    return PixelExtent{(ndc_max.x - ndc_min.x) * 0.5f * static_cast<float>(fw),
                       (ndc_max.y - ndc_min.y) * 0.5f * static_cast<float>(fh)};
}

int height_for_extent(PixelExtent px) {
    const float need = std::max(px.h, px.w * 9.0f / 16.0f) * kFootprintScale;
    const int steps = static_cast<int>(std::ceil(need / static_cast<float>(kHeightStep)));
    return std::clamp(steps * kHeightStep, kMinHeight, kMaxHeight);
}

int Sizer::update(std::optional<int> wanted, double now_s) {
    if (!wanted || *wanted >= height_) {
        if (wanted) height_ = *wanted;
        shrinking_ = false;
        return height_;
    }
    if (!shrinking_) {
        shrinking_ = true;
        shrink_since_s_ = now_s;
    } else if (now_s - shrink_since_s_ >= kShrinkDelayS) {
        height_ = *wanted;
        shrinking_ = false;
    }
    return height_;
}

}  // namespace renderer::viewscreen_rtt
