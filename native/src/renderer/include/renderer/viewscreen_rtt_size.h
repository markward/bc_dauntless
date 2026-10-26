// native/src/renderer/include/renderer/viewscreen_rtt_size.h
//
// Size of the bridge viewscreen render-to-texture feed. The feed is drawn
// onto the viewscreen mesh, so it is sized to that mesh's on-screen pixel
// footprint: about one feed pixel per screen pixel. Bigger would be wasted
// scene work (the feed re-renders the whole space scene) and would alias,
// since the feed texture has no mipmaps.
#pragma once

#include <glm/glm.hpp>

#include <optional>

namespace renderer::viewscreen_rtt {

/// Never smaller than the old fixed 640x360 feed.
constexpr int kMinHeight = 360;
/// Guard for a camera zoomed right into the screen.
constexpr int kMaxHeight = 1080;
/// Heights are multiples of this (widths then multiples of 160), so a small
/// camera move does not change the size.
constexpr int kHeightStep = 90;
/// How long a smaller size must be wanted before the feed shrinks to it.
constexpr double kShrinkDelayS = 0.5;

struct PixelExtent { float w = 0.0f; float h = 0.0f; };

/// On-screen extent in pixels of the model-local box [lo, hi] drawn with
/// `world` through `view_proj` into an fw x fh viewport, clipped to the
/// viewport. A box reaching behind the eye plane is taken to fill the
/// viewport. nullopt: no part of it is on screen.
std::optional<PixelExtent> projected_extent_px(const glm::mat4& view_proj,
                                               const glm::mat4& world,
                                               glm::vec3 lo, glm::vec3 hi,
                                               int fw, int fh);

/// The 16:9 feed height that covers `px` in both directions, rounded up to
/// kHeightStep and clamped to [kMinHeight, kMaxHeight].
int height_for_extent(PixelExtent px);

constexpr int width_for_height(int h) { return h * 16 / 9; }

/// Holds the feed height across frames: grows at once, shrinks only once a
/// smaller height has been wanted for kShrinkDelayS without a break.
class Sizer {
public:
    /// `wanted` nullopt (screen not visible) keeps the current height.
    int update(std::optional<int> wanted, double now_s);
    int height() const { return height_; }

private:
    int height_ = kMinHeight;
    bool shrinking_ = false;
    double shrink_since_s_ = 0.0;
};

}  // namespace renderer::viewscreen_rtt
