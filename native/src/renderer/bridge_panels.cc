// native/src/renderer/bridge_panels.cc
#include "renderer/bridge_panels.h"

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
        worker_.set_panel(e.key, assets::find_panel_files(e.source.albedo, e.source.probe_dirs),
                          e.source.albedo);
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
    // 1. Size every loaded entry from its canvas at this quality, BEFORE any
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
        if (any_valid) size = lottie::panel_size(e.info->canvas_w, e.info->canvas_h, edge);
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
        if (e.variant < 0 || r.w != e.w || r.h != e.h || !r.rgba ||
            r.bytes != static_cast<std::size_t>(r.w) * r.h * 4)
            continue;
        const auto gw = static_cast<GLsizei>(r.w);
        const auto gh = static_cast<GLsizei>(r.h);
        if (!bound) {
            glActiveTexture(GL_TEXTURE0);
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
            bound = true;
        }
        if (e.tex == 0) {
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
            glBindTexture(GL_TEXTURE_2D, e.tex);
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, gw, gh, GL_RGBA, GL_UNSIGNED_BYTE,
                            r.rgba.get());
        }
        glGenerateMipmap(GL_TEXTURE_2D);
        e.has_image = true;
        ++stats_.uploads;
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
                if ((!e.has_tick || tick.tick != e.last_tick) &&
                    worker_.submit(lottie::PanelJob{e.key, v, tick.frame, e.w, e.h,
                                                    info.generation})) {
                    e.has_tick = true;
                    e.last_tick = tick.tick;
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
    for (auto& [k, e] : entries_)
        worker_.set_panel(e.key, assets::find_panel_files(e.source.albedo, e.source.probe_dirs),
                          e.source.albedo);
}

BridgePanels::Stats BridgePanels::take_stats() {
    const Stats s = stats_;
    stats_ = Stats{};
    return s;
}

}  // namespace renderer
