// native/src/renderer/include/renderer/bridge_panels.h
#pragma once

#include <renderer/bridge_quality.h>

#include <lottie/panel_worker.h>

#include <assets/model.h>

#include <glad/glad.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <utility>

namespace renderer {

/// Bridge Lottie panels (spec 2026-10-28-bridge-lottie-panels-design.md
/// §5-7): the render-thread half. Cached models are immutable
/// (`shared_ptr<const Model>`), so the mutable playback state -- which file
/// plays, when it started, the last tick asked for, the live GL texture --
/// lives here, one entry per drawn (model handle, Material::panel_index).
/// Every Lottie object lives on the PanelWorker's thread; this store only
/// queues jobs and uploads finished frames, so nothing here waits on a
/// raster. Needs the GL context current in every call but take_stats and in
/// the destructor (it deletes its textures, as BridgePass's white texture
/// already assumes).
class BridgePanels {
public:
    BridgePanels() = default;
    ~BridgePanels();
    BridgePanels(const BridgePanels&) = delete;
    BridgePanels& operator=(const BridgePanels&) = delete;

    /// Per draw: this panel was drawn in `bridge_state` (kBridgeState*). The
    /// first mark of a (handle, panel_index) creates its entry and loads its
    /// files; an entry with no files stays registered (reload() looks again)
    /// but never submits. A known entry whose model is not `&model` (the
    /// cache freed the model and another came back under the same handle) is
    /// dropped first -- texture deleted, worker key removed -- then recreated
    /// under a fresh key, so no old result can ever reach it.
    void mark_drawn(unsigned long long handle, const assets::Model& model,
                    int panel_index, int bridge_state);

    /// The live texture to bind instead of the still; 0 (draw the still)
    /// unless the entry exists for this exact `&model`, a variant is playing
    /// and an image has been uploaded for it.
    GLuint live_texture(unsigned long long handle, const assets::Model& model,
                        int panel_index) const;

    /// Once per frame, before any bridge render: reallocates entries whose
    /// size for `q` changed, uploads finished frames of the entry's size
    /// (others, such as one rasterised before a quality change, are
    /// discarded), then for each entry drawn since the last
    /// update picks its variant (a change restarts it at `t`) and submits a
    /// job when its tick moved. A paused `t` therefore submits nothing.
    void update(double t, BridgeQuality q);

    /// Developer reload: every entry looks for its files again and reloads
    /// them; every warning may print once more.
    void reload();

    /// Since the last take_stats(): uploads, the bytes they sent (only each
    /// result's changed rectangle), jobs submitted, and the worker's raster +
    /// composite time of the results taken (unchanged ones included).
    struct Stats {
        int uploads = 0;
        std::size_t upload_bytes = 0;
        int jobs = 0;
        double raster_ms = 0.0;
    };
    Stats take_stats();

    /// Tests only (the raster delay seam).
    lottie::PanelWorker& worker_for_test() { return worker_; }

private:
    struct Entry {
        const assets::Model* model = nullptr;
        assets::PanelSource source;
        std::uint64_t key = 0;
        bool drawn = false;           // marked since the last update()
        int state = 0;                // bridge state of the latest mark
        std::uint64_t generation = 0; // PanelInfo generation last seen
        bool restart = false;         // a new load not yet played from t
        std::optional<lottie::PanelInfo> info;  // this update's, nullopt until loaded
        int variant = -1;             // playing file variant; -1 none
        double start = 0.0;           // when `variant` started playing
        bool has_tick = false;
        std::int64_t last_tick = 0;   // tick of the last submitted job
        std::uint32_t w = 0, h = 0;   // texture size for the current quality
        GLuint tex = 0;
        bool has_image = false;       // `tex` holds a frame of `variant`
        bool need_full = false;       // a result was not uploaded: `tex` is behind the worker
    };
    using Key = std::pair<unsigned long long, int>;

    void drop(Entry& e);

    lottie::PanelWorker worker_;
    std::map<Key, Entry> entries_;
    std::uint64_t next_key_ = 1;
    Stats stats_;
};

}  // namespace renderer
