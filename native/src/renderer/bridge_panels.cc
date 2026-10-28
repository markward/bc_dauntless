// native/src/renderer/bridge_panels.cc
#include "renderer/bridge_panels.h"
#include "renderer/frame_timer.h"

#include <assets/panel_files.h>

#include <lottie/panel_math.h>

#include <optional>
#include <unordered_map>
#include <vector>

namespace renderer {

BridgePanels::~BridgePanels() {
    for (auto& [k, e] : entries_) {
        if (e.tex != 0) glDeleteTextures(1, &e.tex);
        e.tex = 0;
    }
    if (unpack_ != 0) glDeleteBuffers(1, &unpack_);
}

void BridgePanels::drop(Entry& e) {
    if (e.tex != 0) glDeleteTextures(1, &e.tex);
    e.tex = 0;
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
    if (e.model != &model || e.variant < 0 || !e.has_image) return 0;
    return e.tex;
}

void BridgePanels::update(double t, BridgeQuality q) {
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
            if (e.tex != 0) glDeleteTextures(1, &e.tex);
            e.tex = 0;
            e.has_image = false;
            e.has_tick = false;
            e.w = size.w;
            e.h = size.h;
        }
    }

    // 2. Upload the finished frames of the entry's current size. take_results()
    // has already dropped any from an older load. Unit 0, so no other unit's
    // binding is disturbed (the bridge pass binds unit 0 per draw anyway).
    std::unordered_map<std::uint64_t, Entry*> by_key;
    by_key.reserve(entries_.size());
    for (auto& [k, e] : entries_) by_key.emplace(e.key, &e);
    bool bound = false;
    for (const lottie::PanelResult& r : worker_.take_results()) {
        stats_.raster_ms += r.raster_ms;
        const auto it = by_key.find(r.key);
        if (it == by_key.end()) continue;
        Entry& e = *it->second;
        // A result carries only what changed since the worker's previous one
        // for this key. One that is not uploaded leaves the texture behind
        // the worker, so the next job asks for the whole frame.
        const lottie::PanelRect& rc = r.rect;
        const bool whole = rc.x == 0 && rc.y == 0 && rc.w == r.w && rc.h == r.h;
        if (rc.w == 0 || rc.h == 0) {
            // Nothing changed. Fine for a texture that holds the last result;
            // one that does not (new, or reallocated since) needs a full one.
            if (e.tex == 0 || r.w != e.w || r.h != e.h) e.need_full = true;
            continue;
        }
        if (e.variant < 0 || r.w != e.w || r.h != e.h || !r.rgba ||
            rc.x + rc.w > r.w || rc.y + rc.h > r.h ||
            r.bytes != static_cast<std::size_t>(rc.w) * rc.h * 4 ||
            (e.tex == 0 && !whole)) {
            e.need_full = true;
            continue;
        }
        const auto gw = static_cast<GLsizei>(r.w);
        const auto gh = static_cast<GLsizei>(r.h);
        DAUNTLESS_FRAME_SCOPE("bridge_lottie.upload");
        if (!bound) {
            glActiveTexture(GL_TEXTURE0);
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
            bound = true;
        }
        if (e.tex == 0) {
            // The first, whole image allocates the texture straight from
            // client memory (through the unpack buffer it measured slower).
            glGenTextures(1, &e.tex);
            glBindTexture(GL_TEXTURE_2D, e.tex);
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, gw, gh, 0, GL_RGBA,
                         GL_UNSIGNED_BYTE, r.rgba.get());
            // As assets::upload_image samples a still, plus mips: panels
            // are seen at grazing angles (spec §6).
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
        } else {
            // Every later (partial) upload goes through a pixel-unpack buffer,
            // re-specified per upload (orphaned), so the texture update queues
            // on the GPU instead of the CPU waiting for draws still reading last
            // frame's image. Measured 2026-10-28 (DBridge, Debug): straight
            // from client memory it took 0.75 ms at Medium, 4.3 ms at High.
            if (unpack_ == 0) glGenBuffers(1, &unpack_);
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, unpack_);
            glBufferData(GL_PIXEL_UNPACK_BUFFER, static_cast<GLsizeiptr>(r.bytes), nullptr,
                         GL_STREAM_DRAW);
            glBufferSubData(GL_PIXEL_UNPACK_BUFFER, 0, static_cast<GLsizeiptr>(r.bytes),
                            r.rgba.get());
            glBindTexture(GL_TEXTURE_2D, e.tex);
            glTexSubImage2D(GL_TEXTURE_2D, 0, static_cast<GLint>(rc.x),
                            static_cast<GLint>(rc.y), static_cast<GLsizei>(rc.w),
                            static_cast<GLsizei>(rc.h), GL_RGBA, GL_UNSIGNED_BYTE,
                            nullptr);   // offset 0 in the unpack buffer
            // Never left bound: a later glTexImage2D anywhere would read it.
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
        }
        {
            DAUNTLESS_FRAME_SCOPE("bridge_lottie.mipmap");
            glGenerateMipmap(GL_TEXTURE_2D);
        }
        e.has_image = true;
        ++stats_.uploads;
        stats_.upload_bytes += r.bytes;
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
                const bool full = e.tex == 0 || e.need_full;
                if ((!e.has_tick || tick.tick != e.last_tick || e.need_full) &&
                    worker_.submit(lottie::PanelJob{e.key, v, tick.frame, e.w, e.h,
                                                    info.generation, full})) {
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
