#include "lottie/panel_worker.h"

#include <atomic>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <exception>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>

#include "assets/file_bytes.h"
#include "assets/texture.h"
#include "lottie/lottie_clip.h"
#include "lottie/panel_math.h"

namespace lottie {

namespace {

struct Load {
    std::uint64_t key;
    std::uint64_t generation;
    std::filesystem::path albedo;
    std::vector<std::filesystem::path> probe_dirs;
};
struct Remove {
    std::uint64_t key;
};
using Command = std::variant<Load, Remove, PanelJob>;

// One loaded panel. Lives only on the worker thread.
struct Loaded {
    std::uint64_t generation = 0;
    std::array<std::unique_ptr<LottieClip>, assets::kPanelVariants> clips;
    assets::Image still;  // empty when unreadable: composite over transparent black
    // `still` scaled to the last job's size, so a frame is only an "over".
    std::vector<std::uint8_t> scaled;
    std::uint32_t scaled_w = 0, scaled_h = 0;
    // The whole composite of the last result, which the caller's texture now
    // holds, and the buffer the next one is composited into (swapped after).
    std::unique_ptr<std::uint8_t[]> shown, next;
    std::uint32_t shown_w = 0, shown_h = 0;
};

}  // namespace

struct PanelWorker::Impl {
    // Everything below `mu` is shared with the caller and guarded by it.
    // LottieClips live in run()'s locals, never here.
    mutable std::mutex mu;
    std::condition_variable cv;
    bool stop = false;
    std::deque<Command> queue;
    std::uint64_t next_generation = 0;
    std::unordered_map<std::uint64_t, std::uint64_t> current;  // key -> newest set_panel
    std::unordered_map<std::uint64_t, PanelInfo> infos;
    std::unordered_set<std::uint64_t> busy;                    // a job queued or running
    std::vector<PanelResult> results;
    std::unordered_set<std::string> warned;

    std::atomic<std::int64_t> delay_ms{0};
    std::thread thread;

    // Caller holds `mu`.
    bool is_current(std::uint64_t key, std::uint64_t generation) const {
        auto it = current.find(key);
        return it != current.end() && it->second == generation;
    }

    void warn_once(const std::string& line) {
        {
            std::lock_guard<std::mutex> lk(mu);
            if (!warned.insert(line).second) return;
        }
        std::fprintf(stderr, "%s\n", line.c_str());
    }

    void run();
    // A command threw: free a job's busy flag and warn once.
    void failed(const Command& cmd, const char* what) noexcept;
    void load(const Load& cmd, std::unordered_map<std::uint64_t, Loaded>& panels);
    void raster(const PanelJob& job, std::unordered_map<std::uint64_t, Loaded>& panels,
                std::vector<std::uint8_t>& premul);
};

void PanelWorker::Impl::run() {
    ensure_thorvg_initialised();
    // Worker-only state; destroyed here, so ThorVG objects die on this thread.
    std::unordered_map<std::uint64_t, Loaded> panels;
    std::vector<std::uint8_t> premul;
    for (;;) {
        Command cmd;
        {
            std::unique_lock<std::mutex> lk(mu);
            cv.wait(lk, [&] { return stop || !queue.empty(); });
            if (stop) break;
            cmd = std::move(queue.front());
            queue.pop_front();
        }
        // A throw (bad_alloc, a decoder) must never std::terminate the game.
        try {
            if (const auto* l = std::get_if<Load>(&cmd)) load(*l, panels);
            else if (const auto* r = std::get_if<Remove>(&cmd)) panels.erase(r->key);
            else raster(std::get<PanelJob>(cmd), panels, premul);
        } catch (const std::exception& e) {
            failed(cmd, e.what());
        } catch (...) {
            failed(cmd, "unknown error");
        }
    }
}

void PanelWorker::Impl::failed(const Command& cmd, const char* what) noexcept {
    std::uint64_t key = 0;
    std::string where;
    if (const auto* l = std::get_if<Load>(&cmd)) {
        key = l->key;
        where = l->albedo.string();
    } else if (const auto* r = std::get_if<Remove>(&cmd)) {
        key = r->key;
    } else {
        key = std::get<PanelJob>(cmd).key;
        std::lock_guard<std::mutex> lk(mu);
        busy.erase(key);
    }
    try {
        if (where.empty()) where = "panel " + std::to_string(key);
        warn_once("[lottie] " + where + ": " + what + "; using the still");
    } catch (...) {
    }
}

void PanelWorker::Impl::load(const Load& cmd,
                             std::unordered_map<std::uint64_t, Loaded>& panels) {
    {
        std::lock_guard<std::mutex> lk(mu);
        if (!is_current(cmd.key, cmd.generation)) return;  // superseded or removed
    }
    const assets::PanelFiles files = assets::find_panel_files(cmd.albedo, cmd.probe_dirs);
    for (const auto& orphan : files.orphans)
        warn_once("[lottie] " + orphan.string() + ": no " + cmd.albedo.stem().string() +
                  ".json beside it; ignored");
    Loaded p;
    p.generation = cmd.generation;
    PanelInfo info;
    info.generation = cmd.generation;
    bool any = false;
    for (int v = 0; v < assets::kPanelVariants; ++v) {
        const auto& path = files.by_variant[v];
        if (path.empty()) continue;
        std::string err;
        auto clip = LottieClip::load(path, &err);
        if (!clip) {
            warn_once("[lottie] " + path.string() + ": " + err + "; using the still");
            continue;
        }
        info.valid[v] = true;
        info.total_frames[v] = clip->total_frames();
        info.fps[v] = clip->fps();
        p.clips[v] = std::move(clip);
        any = true;
    }
    if (const auto& def = p.clips[assets::kPanelDefault]) {
        info.canvas_w = def->canvas_width();
        info.canvas_h = def->canvas_height();
        const float aspect = info.canvas_w / info.canvas_h;
        for (int v = 1; v < assets::kPanelVariants; ++v) {
            if (!p.clips[v]) continue;
            const float a = p.clips[v]->canvas_width() / p.clips[v]->canvas_height();
            if (std::abs(a / aspect - 1.f) > 0.01f)
                warn_once("[lottie] " + files.by_variant[v].string() +
                          ": canvas aspect differs from " +
                          files.by_variant[assets::kPanelDefault].filename().string() +
                          "; stretched");
        }
    } else {
        // No default: size from the first valid state file.
        for (const auto& clip : p.clips) {
            if (!clip) continue;
            info.canvas_w = clip->canvas_width();
            info.canvas_h = clip->canvas_height();
            break;
        }
    }
    if (any) {
        bool ok = false;
        if (auto bytes = assets::read_binary_file(cmd.albedo)) {
            try {
                p.still = assets::decode_image(*bytes);
                ok = true;
            } catch (const std::exception&) {
            }
        }
        if (!ok)
            warn_once("[lottie] " + cmd.albedo.string() +
                      ": unreadable still; compositing over transparent black");
    }
    panels[cmd.key] = std::move(p);
    std::lock_guard<std::mutex> lk(mu);
    if (is_current(cmd.key, cmd.generation)) infos[cmd.key] = info;
}

void PanelWorker::Impl::raster(const PanelJob& job,
                               std::unordered_map<std::uint64_t, Loaded>& panels,
                               std::vector<std::uint8_t>& premul) {
    auto drop = [&] {
        std::lock_guard<std::mutex> lk(mu);
        busy.erase(job.key);
    };
    auto it = panels.find(job.key);
    if (it == panels.end() || it->second.generation != job.generation ||
        job.variant < 0 || job.variant >= assets::kPanelVariants ||
        !it->second.clips[job.variant]) {
        drop();
        return;
    }
    if (const auto d = delay_ms.load(); d > 0)
        std::this_thread::sleep_for(std::chrono::milliseconds(d));

    Loaded& p = it->second;
    const auto t0 = std::chrono::steady_clock::now();
    if (!p.clips[job.variant]->render(job.frame, job.w, job.h, premul)) {
        drop();
        return;
    }
    if (p.scaled_w != job.w || p.scaled_h != job.h) {
        p.scaled = scale_still_rgba(p.still, job.w, job.h);
        p.scaled_w = job.w;
        p.scaled_h = job.h;
    }
    // Default-initialised: over_into writes every byte.
    const std::size_t bytes = static_cast<std::size_t>(job.w) * job.h * 4;
    const bool same_size = p.shown && p.shown_w == job.w && p.shown_h == job.h;
    // A new size starts over: both buffers go, so neither is ever written
    // at a size it was not allocated for.
    if (!same_size) {
        p.shown.reset();
        p.next.reset();
    }
    if (!p.next) p.next.reset(new std::uint8_t[bytes]);
    const std::span<std::uint8_t> frame(p.next.get(), bytes);
    over_into(p.scaled, premul, frame);
    // Only what changed since the last result goes back; nothing when the
    // frame is the same (a held keyframe, a static stretch of the loop).
    std::optional<PanelRect> rect = PanelRect{0, 0, job.w, job.h};
    if (same_size && !job.full)
        rect = changed_rect(std::span<const std::uint8_t>(p.shown.get(), bytes), frame,
                            job.w, job.h);
    PanelResult r{job.key, job.generation, job.w, job.h, PanelRect{0, 0, 0, 0}, nullptr, 0,
                  0.0};
    if (rect) {
        r.rect = *rect;
        r.bytes = static_cast<std::size_t>(rect->w) * rect->h * 4;
        r.rgba.reset(new std::uint8_t[r.bytes]);
        copy_rect(frame, job.w, *rect, std::span<std::uint8_t>(r.rgba.get(), r.bytes));
        std::swap(p.shown, p.next);
        p.shown_w = job.w;
        p.shown_h = job.h;
    }
    r.raster_ms = std::chrono::duration<double, std::milli>(
                      std::chrono::steady_clock::now() - t0).count();

    std::lock_guard<std::mutex> lk(mu);
    busy.erase(job.key);
    if (is_current(job.key, job.generation)) results.push_back(std::move(r));
}

PanelWorker::PanelWorker() : impl_(std::make_unique<Impl>()) {
    impl_->thread = std::thread([impl = impl_.get()] { impl->run(); });
}

PanelWorker::~PanelWorker() {
    {
        std::lock_guard<std::mutex> lk(impl_->mu);
        impl_->stop = true;
        impl_->queue.clear();
    }
    impl_->cv.notify_one();
    impl_->thread.join();
}

void PanelWorker::set_panel(std::uint64_t key, std::filesystem::path albedo,
                            std::vector<std::filesystem::path> probe_dirs) {
    {
        std::lock_guard<std::mutex> lk(impl_->mu);
        const std::uint64_t gen = ++impl_->next_generation;
        impl_->current[key] = gen;
        impl_->queue.push_back(Load{key, gen, std::move(albedo), std::move(probe_dirs)});
    }
    impl_->cv.notify_one();
}

void PanelWorker::remove_panel(std::uint64_t key) {
    {
        std::lock_guard<std::mutex> lk(impl_->mu);
        impl_->current.erase(key);
        impl_->infos.erase(key);
        impl_->queue.push_back(Remove{key});
    }
    impl_->cv.notify_one();
}

std::optional<PanelInfo> PanelWorker::info(std::uint64_t key) const {
    std::lock_guard<std::mutex> lk(impl_->mu);
    auto it = impl_->infos.find(key);
    if (it == impl_->infos.end()) return std::nullopt;
    return it->second;
}

bool PanelWorker::submit(const PanelJob& job) {
    {
        std::lock_guard<std::mutex> lk(impl_->mu);
        if (!impl_->busy.insert(job.key).second) return false;
        impl_->queue.push_back(job);
    }
    impl_->cv.notify_one();
    return true;
}

std::vector<PanelResult> PanelWorker::take_results() {
    std::lock_guard<std::mutex> lk(impl_->mu);
    // A set_panel / remove_panel since a result was pushed makes it stale.
    std::vector<PanelResult> out;
    for (auto& r : impl_->results)
        if (impl_->is_current(r.key, r.generation)) out.push_back(std::move(r));
    impl_->results.clear();
    return out;
}

void PanelWorker::clear_warnings() {
    std::lock_guard<std::mutex> lk(impl_->mu);
    impl_->warned.clear();
}

void PanelWorker::set_test_raster_delay(std::chrono::milliseconds d) {
    impl_->delay_ms.store(d.count());
}

}  // namespace lottie
