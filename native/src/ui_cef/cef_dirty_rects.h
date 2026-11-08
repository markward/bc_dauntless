// native/src/ui_cef/cef_dirty_rects.h
//
// Dirty-rect bookkeeping for the CEF overlay. Header-only with no CEF or GL
// dependency, so it is unit-tested on its own
// (native/tests/ui_cef/cef_dirty_rects_test.cc).
//
// CEF's OnPaint hands over the WHOLE latest view buffer plus the rects that
// changed since the previous paint. Instead of copying and uploading the
// whole surface, OnPaint copies only those rects into the cached bitmap
// (apply_paint) and accumulates them in a DirtyRegion; the composite uploads
// only the accumulated rects (GL_UNPACK_ROW_LENGTH sub-image uploads) and
// clears the region. The texture therefore ends up byte-identical to CEF's
// latest buffer, exactly as a whole-surface upload would leave it.
//
// Falls back to one whole copy / upload when:
//   - the surface is new or changed size (w OR h, a w/h swap included, which
//     keeps w*h and so would not even resize the bitmap vector);
//   - CEF reported no rects at all (nothing to trust, so copy everything);
//   - the accumulated rects sum past kFullUploadFraction of the surface,
//     where many small sub-image calls stop being cheaper than one big one.
// More than kMaxDirtyRects disjoint rects collapse to their bounding box,
// which bounds the per-frame glTexSubImage2D count.
//
// Rects are device pixels with a top-left origin. The texture is stored
// top-down (the composite's vertex shader flips v), so a rect maps straight
// to texel rows and columns.
#pragma once

#include "cef_upload_policy.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace dauntless::ui_cef {

struct PixelRect {
    int x, y, w, h;
};

constexpr int   kMaxDirtyRects      = 8;
constexpr float kFullUploadFraction = 0.5f;

// `r` intersected with the surface [0,w) x [0,h); w or h is 0 when empty.
inline PixelRect clip_rect(PixelRect r, int surf_w, int surf_h) {
    const int x0 = std::max(r.x, 0);
    const int y0 = std::max(r.y, 0);
    const int x1 = std::min(r.x + r.w, surf_w);
    const int y1 = std::min(r.y + r.h, surf_h);
    if (x1 <= x0 || y1 <= y0) return PixelRect{x0, y0, 0, 0};
    return PixelRect{x0, y0, x1 - x0, y1 - y0};
}

class DirtyRegion {
public:
    // Clips `r` to the surface and adds it. A rect that overlaps or touches
    // an existing one is merged into their bounding box, repeated until no
    // pair overlaps or touches. Past kMaxDirtyRects the list collapses to one
    // bounding box; past kFullUploadFraction of the surface it becomes full.
    void add(PixelRect r, int surf_w, int surf_h) {
        if (full_) return;
        r = clip_rect(r, surf_w, surf_h);
        if (r.w <= 0 || r.h <= 0) return;

        bool merged = true;
        while (merged) {
            merged = false;
            for (auto it = rects_.begin(); it != rects_.end(); ++it) {
                if (overlaps_or_touches(*it, r)) {
                    r = bounding_box(*it, r);
                    rects_.erase(it);
                    merged = true;
                    break;
                }
            }
        }
        rects_.push_back(r);

        if (static_cast<int>(rects_.size()) > kMaxDirtyRects) {
            PixelRect box = rects_.front();
            for (const PixelRect& q : rects_) box = bounding_box(box, q);
            rects_.assign(1, box);
        }

        long long area = 0;
        for (const PixelRect& q : rects_) {
            area += static_cast<long long>(q.w) * q.h;
        }
        const double surface = static_cast<double>(surf_w) * surf_h;
        if (static_cast<double>(area) > kFullUploadFraction * surface) {
            mark_full();
        }
    }

    void mark_full() {
        full_ = true;
        rects_.clear();
    }
    bool full() const { return full_; }
    bool empty() const { return !full_ && rects_.empty(); }
    // Meaningless when full(); callers check full() first.
    const std::vector<PixelRect>& rects() const { return rects_; }
    void clear() {
        full_ = false;
        rects_.clear();
    }

private:
    static bool overlaps_or_touches(const PixelRect& a, const PixelRect& b) {
        return a.x <= b.x + b.w && b.x <= a.x + a.w &&
               a.y <= b.y + b.h && b.y <= a.y + a.h;
    }
    static PixelRect bounding_box(const PixelRect& a, const PixelRect& b) {
        const int x0 = std::min(a.x, b.x);
        const int y0 = std::min(a.y, b.y);
        const int x1 = std::max(a.x + a.w, b.x + b.w);
        const int y1 = std::max(a.y + a.h, b.y + b.h);
        return PixelRect{x0, y0, x1 - x0, y1 - y0};
    }

    std::vector<PixelRect> rects_;
    bool full_ = false;
};

// True when a paint of w x h onto a bitmap of old_w x old_h must be a whole
// copy: the first paint (old 0 x 0) and any change of w or h, including a
// w/h swap that keeps the byte count.
inline bool paint_needs_full(int old_w, int old_h, int w, int h) {
    return old_w != w || old_h != h;
}

// Copies each rect (clipped to w x h) from src to dst, row by row. Both are
// BGRA, 4 bytes per pixel, tight rows of w pixels.
inline void copy_rects(std::uint8_t* dst, const std::uint8_t* src, int w,
                       int h, const std::vector<PixelRect>& rects) {
    for (PixelRect r : rects) {
        r = clip_rect(r, w, h);
        if (r.w <= 0 || r.h <= 0) continue;
        const size_t row_bytes = static_cast<size_t>(r.w) * 4;
        for (int y = r.y; y < r.y + r.h; ++y) {
            const size_t off = (static_cast<size_t>(y) * w + r.x) * 4;
            std::memcpy(dst + off, src + off, row_bytes);
        }
    }
}

// OnPaint's bitmap update. `buffer` is CEF's whole w x h view; `rects` are
// the rects CEF says changed. Copies the whole buffer (and marks `dirty`
// full) when paint_needs_full or `rects` is empty; otherwise copies only the
// rects and adds them to `dirty`.
inline void apply_paint(std::vector<std::uint8_t>& bitmap, int& bitmap_w,
                        int& bitmap_h, DirtyRegion& dirty,
                        const std::uint8_t* buffer, int w, int h,
                        const std::vector<PixelRect>& rects) {
    if (paint_needs_full(bitmap_w, bitmap_h, w, h) || rects.empty()) {
        const size_t bytes = static_cast<size_t>(w) * h * 4;
        if (bitmap.size() != bytes) bitmap.resize(bytes);
        std::memcpy(bitmap.data(), buffer, bytes);
        bitmap_w = w;
        bitmap_h = h;
        dirty.mark_full();
        return;
    }
    copy_rects(bitmap.data(), buffer, w, h, rects);
    for (const PixelRect& r : rects) dirty.add(r, w, h);
}

// Whether an upload the policy allowed (should_upload) must send the whole
// surface rather than the dirty rects: `always` mode (unchanged behaviour),
// a full region, or a texture that must be (re)allocated.
inline bool upload_needs_full(UploadMode mode, bool texture_allocated,
                              bool size_differs, const DirtyRegion& dirty) {
    return mode == UploadMode::Always || dirty.full() || !texture_allocated ||
           size_differs;
}

}  // namespace dauntless::ui_cef
