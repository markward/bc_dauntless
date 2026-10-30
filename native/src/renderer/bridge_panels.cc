// native/src/renderer/bridge_panels.cc
#include "renderer/bridge_panels.h"
#include "renderer/frame_timer.h"

#include <assets/panel_files.h>

#include <lottie/panel_math.h>

#include <optional>
#include <utility>
#include <unordered_map>
#include <vector>

namespace renderer {

BridgePanels::~BridgePanels() {
    for (auto& [k, e] : entries_) free_textures(e);
    for (auto& [frame, sync] : fences_) glDeleteSync(sync);
}

void BridgePanels::free_textures(Entry& e) {
    for (Slot& s : e.slots)
        if (s.tex != 0) glDeleteTextures(1, &s.tex);
    e.slots = {};
    e.front = -1;
    e.pending.reset();
}

namespace {

// A result's mip levels are uploadable: in level order, each inside its level
// and its bytes matching its rect; a whole result carries every level whole
// (a new texture is allocated from it).
bool mips_fit(const lottie::PanelResult& r, bool whole) {
    const int levels = lottie::mip_levels(r.w, r.h);
    if (r.mips.size() > static_cast<std::size_t>(levels - 1)) return false;
    if (whole && r.mips.size() != static_cast<std::size_t>(levels - 1)) return false;
    for (std::size_t k = 0; k < r.mips.size(); ++k) {
        const lottie::PanelLevel& m = r.mips[k];
        const lottie::PanelSize d = lottie::mip_size(r.w, r.h, static_cast<int>(k) + 1);
        if (!m.rgba || m.rect.w == 0 || m.rect.h == 0 || m.rect.x + m.rect.w > d.w ||
            m.rect.y + m.rect.h > d.h ||
            m.bytes != static_cast<std::size_t>(m.rect.w) * m.rect.h * 4)
            return false;
        if (whole && (m.rect.w != d.w || m.rect.h != d.h)) return false;
    }
    return true;
}

}  // namespace

void BridgePanels::drop(Entry& e) {
    free_textures(e);
    worker_.remove_panel(e.key);
}

void BridgePanels::mark_drawn(unsigned long long handle, const assets::Model& model,
                              int panel_index, int bridge_state) {
    if (panel_index < 0 || panel_index >= static_cast<int>(model.panel_sources.size()))
        return;
    const Key k{handle, panel_index};
    auto it = entries_.find(k);
    // Same handle, different model: the cache freed the old one. Its
    // texture and worker key go; the new model gets a fresh key below.
    if (it != entries_.end() && it->second.model != &model) {
        drop(it->second);
        entries_.erase(it);
        it = entries_.end();
    }
    if (it == entries_.end()) {
        Entry e;
        e.model = &model;
        e.source = model.panel_sources[static_cast<std::size_t>(panel_index)];
        e.key = next_key_++;
        // Loaded even with no files: the worker then publishes an info with
        // no valid variant, which never submits, and reload() can find a
        // file added later.
        worker_.set_panel(e.key, e.source.albedo, e.source.probe_dirs);
        it = entries_.emplace(k, std::move(e)).first;
    }
    it->second.drawn = true;
    it->second.state = bridge_state;
}

GLuint BridgePanels::live_texture(unsigned long long handle, const assets::Model& model,
                                  int panel_index) const {
    const auto it = entries_.find(Key{handle, panel_index});
    if (it == entries_.end()) return 0;
    const Entry& e = it->second;
    if (e.model != &model || e.variant < 0 || !e.has_image || e.front < 0) return 0;
    return e.slots[static_cast<std::size_t>(e.front)].tex;
}

void BridgePanels::apply(Entry& e, lottie::PanelResult&& r, bool& bound) {
    // A result carries what changed since the worker's previous one for this
    // key, plus what its target texture lacked (PanelJob::also). One that is
    // not uploaded leaves the textures behind the worker, so the next job
    // asks for the whole frame.
    const lottie::PanelRect& rc = r.rect;
    const bool whole = rc.x == 0 && rc.y == 0 && rc.w == r.w && rc.h == r.h;
    if (rc.w == 0 || rc.h == 0) {
        // Nothing changed. Fine while a texture holds the last result; with
        // none (new, or reallocated since) the next job must be whole.
        if (e.front < 0 || r.w != e.w || r.h != e.h) e.need_full = true;
        return;
    }
    const int target = next_slot(e);
    Slot& s = e.slots[static_cast<std::size_t>(target)];
    if (e.variant < 0 || r.w != e.w || r.h != e.h || !r.rgba ||
        rc.x + rc.w > r.w || rc.y + rc.h > r.h ||
        r.bytes != static_cast<std::size_t>(rc.w) * rc.h * 4 ||
        r.changed.x < rc.x || r.changed.y < rc.y || r.changed.x + r.changed.w > rc.x + rc.w ||
        r.changed.y + r.changed.h > rc.y + rc.h ||
        (s.tex == 0 && !whole) || !mips_fit(r, whole)) {
        e.need_full = true;
        return;
    }
    // Writing a texture the GPU may still read (the one drawn now, or one a
    // queued frame drew) made the driver stall the render thread 5-35 ms a
    // frame (perf P-14). So each panel rotates through kSlots textures and
    // writes one only once the frames that drew it have finished.
    if (s.retired > done_frame_) {
        e.pending = std::move(r);
        return;
    }
    const auto gw = static_cast<GLsizei>(r.w);
    const auto gh = static_cast<GLsizei>(r.h);
    DAUNTLESS_FRAME_SCOPE("bridge_lottie.upload");
    if (!bound) {
        glActiveTexture(GL_TEXTURE0);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        bound = true;
    }
    std::size_t mip_bytes = 0;
    for (const lottie::PanelLevel& m : r.mips) mip_bytes += m.bytes;
    if (s.tex == 0) {
        // A texture's first, whole image allocates it and its whole mip chain.
        glGenTextures(1, &s.tex);
        glBindTexture(GL_TEXTURE_2D, s.tex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, gw, gh, 0, GL_RGBA, GL_UNSIGNED_BYTE,
                     r.rgba.get());
        for (std::size_t k = 0; k < r.mips.size(); ++k)
            glTexImage2D(GL_TEXTURE_2D, static_cast<GLint>(k + 1), GL_RGBA8,
                         static_cast<GLsizei>(r.mips[k].rect.w),
                         static_cast<GLsizei>(r.mips[k].rect.h), 0, GL_RGBA,
                         GL_UNSIGNED_BYTE, r.mips[k].rgba.get());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, static_cast<GLint>(r.mips.size()));
        // As assets::upload_image samples a still, plus mips: panels are seen
        // at grazing angles (spec §6).
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    } else {
        // Later uploads write what changed, every mip level included (the
        // worker built them: the render thread never calls glGenerateMipmap,
        // 5-10 ms a call live), straight from client memory -- the texture
        // is not in use, so nothing waits. Through a pixel-unpack buffer the
        // same uploads stalled 20-37 ms a frame at 4K (perf P-14).
        glBindTexture(GL_TEXTURE_2D, s.tex);
        glTexSubImage2D(GL_TEXTURE_2D, 0, static_cast<GLint>(rc.x), static_cast<GLint>(rc.y),
                        static_cast<GLsizei>(rc.w), static_cast<GLsizei>(rc.h), GL_RGBA,
                        GL_UNSIGNED_BYTE, r.rgba.get());
        {
            DAUNTLESS_FRAME_SCOPE("bridge_lottie.mipmap");
            for (std::size_t k = 0; k < r.mips.size(); ++k) {
                const lottie::PanelLevel& m = r.mips[k];
                glTexSubImage2D(GL_TEXTURE_2D, static_cast<GLint>(k + 1),
                                static_cast<GLint>(m.rect.x), static_cast<GLint>(m.rect.y),
                                static_cast<GLsizei>(m.rect.w), static_cast<GLsizei>(m.rect.h),
                                GL_RGBA, GL_UNSIGNED_BYTE, m.rgba.get());
            }
        }
    }
    // The other textures now lack what changed -- not the rest of `rc`,
    // which only caught this one up (adding it made every texture's lack, and
    // so every upload, grow to the whole frame). The drawn one retires, last
    // drawn (at the latest) in the previous frame.
    for (Slot& o : e.slots)
        if (&o != &s) o.stale = lottie::union_rect(o.stale, r.changed);
    s.stale = lottie::PanelRect{0, 0, 0, 0};
    if (e.front >= 0) e.slots[static_cast<std::size_t>(e.front)].retired = frame_ - 1;
    e.front = target;
    e.has_image = true;
    ++stats_.uploads;
    stats_.upload_bytes += r.bytes + mip_bytes;
}

void BridgePanels::update(double t, BridgeQuality q) {
    // 0. How far the GPU has got: a fence after every command so far (all of
    // frame `frame_ - 1`'s draws), then every fence that has passed. Never a
    // wait -- a texture the GPU may still read is simply not written yet.
    ++frame_;
    if (GLsync f = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)) fences_.emplace_back(frame_ - 1, f);
    while (!fences_.empty() && !hold_fences_) {
        // The flush bit: a fence the driver has not yet sent never signals
        // (the swap flushes in the game; nothing does in a test).
        const GLenum st =
            glClientWaitSync(fences_.front().second, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
        if (st == GL_TIMEOUT_EXPIRED) break;
        done_frame_ = fences_.front().first;   // signalled (or failed: never block on it)
        glDeleteSync(fences_.front().second);
        fences_.pop_front();
    }

    // 1. Size every loaded entry from its canvas at this quality (capped by
    // the canvas itself, lottie::panel_edge_cap), BEFORE any
    // upload, so a frame rasterised at the old size is discarded below rather
    // than uploaded and thrown away. A new size reallocates: the old texture
    // and image go, and the next tick re-renders.
    const std::uint32_t edge = panel_edge_for(q);
    for (auto& [k, e] : entries_) {
        e.info = worker_.info(e.key);
        if (!e.info) continue;   // first load not finished: nothing to size yet
        // A new load (the first, or a reload) restarts the panel the next
        // time it is drawn, even if that is not this frame.
        if (e.info->generation != e.generation) e.restart = true;
        e.generation = e.info->generation;
        bool any_valid = false;
        for (bool v : e.info->valid) any_valid = any_valid || v;
        lottie::PanelSize size{0, 0};
        if (any_valid)
            size = lottie::panel_size(
                e.info->canvas_w, e.info->canvas_h,
                lottie::panel_edge_cap(edge, e.info->canvas_w, e.info->canvas_h));
        if (size.w != e.w || size.h != e.h) {
            free_textures(e);
            e.has_image = false;
            e.has_tick = false;
            e.w = size.w;
            e.h = size.h;
        }
    }

    // 2. Upload the finished frames of the entry's current size: first any
    // held for want of a free texture, then the new ones. take_results() has
    // already dropped any from an older load. Unit 0, so no other unit's
    // binding is disturbed (the bridge pass binds unit 0 per draw anyway).
    bool bound = false;
    for (auto& [k, e] : entries_) {
        if (!e.pending) continue;
        lottie::PanelResult r = std::move(*e.pending);
        e.pending.reset();
        apply(e, std::move(r), bound);
    }
    std::unordered_map<std::uint64_t, Entry*> by_key;
    by_key.reserve(entries_.size());
    for (auto& [k, e] : entries_) by_key.emplace(e.key, &e);
    for (lottie::PanelResult& r : worker_.take_results()) {
        stats_.raster_ms += r.raster_ms;
        const auto it = by_key.find(r.key);
        if (it == by_key.end()) continue;
        Entry& e = *it->second;
        // Never submitted while one is held, so this is defensive: the held
        // one's partial would be lost under it.
        if (e.pending) {
            e.need_full = true;
            continue;
        }
        apply(e, std::move(r), bound);
    }
    if (bound) glBindTexture(GL_TEXTURE_2D, 0);

    for (auto& [k, e] : entries_) {
        // 3. Drawn since the last update: play the state's variant. A new
        // variant (or a reload) starts from its first frame at `t` (spec §5);
        // none valid shows the still.
        if (e.drawn && e.info) {
            const lottie::PanelInfo& info = *e.info;
            const int v = assets::select_panel_variant(e.state, info.valid);
            if (v != e.variant || e.restart) {
                e.restart = false;
                e.variant = v;
                e.start = t;
                e.has_tick = false;
                if (v < 0) e.has_image = false;
            }
            if (v >= 0 && e.w > 0 && e.h > 0) {
                const auto vi = static_cast<std::size_t>(v);
                const lottie::PanelTick tick =
                    lottie::panel_tick(t, e.start, info.total_frames[vi], info.fps[vi]);
                // A refused submit (a job still in flight) leaves the tick
                // unrecorded, so the next update asks again.
                // The result goes to the next texture in turn, so a change
                // also carries what that one lacks -- all of it when it has
                // never been filled (an unchanged frame still carries
                // nothing). Whole with no image yet. None while a result waits
                // for its texture.
                const Slot& target = e.slots[static_cast<std::size_t>(next_slot(e))];
                const bool full = e.front < 0 || e.need_full;
                lottie::PanelJob job{e.key, v, tick.frame, e.w, e.h, info.generation, full};
                job.also = target.tex == 0 ? lottie::PanelRect{0, 0, e.w, e.h} : target.stale;
                if (!e.pending && (!e.has_tick || tick.tick != e.last_tick || e.need_full) &&
                    worker_.submit(job)) {
                    e.has_tick = true;
                    e.last_tick = tick.tick;
                    if (full) e.need_full = false;
                    ++stats_.jobs;
                }
            }
        }
        // 4. The next frame's draws mark afresh.
        e.drawn = false;
    }
}

void BridgePanels::reload() {
    worker_.clear_warnings();
    for (auto& [k, e] : entries_) worker_.set_panel(e.key, e.source.albedo, e.source.probe_dirs);
}

BridgePanels::Stats BridgePanels::take_stats() {
    const Stats s = stats_;
    stats_ = Stats{};
    return s;
}

}  // namespace renderer
