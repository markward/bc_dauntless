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
    assets::PanelFiles files;
    std::filesystem::path albedo;
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
        if (const auto* l = std::get_if<Load>(&cmd)) load(*l, panels);
        else if (const auto* r = std::get_if<Remove>(&cmd)) panels.erase(r->key);
        else raster(std::get<PanelJob>(cmd), panels, premul);
    }
}

void PanelWorker::Impl::load(const Load& cmd,
                             std::unordered_map<std::uint64_t, Loaded>& panels) {
    {
        std::lock_guard<std::mutex> lk(mu);
        if (!is_current(cmd.key, cmd.generation)) return;  // superseded or removed
    }
    Loaded p;
    p.generation = cmd.generation;
    PanelInfo info;
    info.generation = cmd.generation;
    bool any = false;
    for (int v = 0; v < assets::kPanelVariants; ++v) {
        const auto& path = cmd.files.by_variant[v];
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
                warn_once("[lottie] " + cmd.files.by_variant[v].string() +
                          ": canvas aspect differs from " +
                          cmd.files.by_variant[assets::kPanelDefault].filename().string() +
                          "; stretched");
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

    const auto t0 = std::chrono::steady_clock::now();
    if (!it->second.clips[job.variant]->render(job.frame, job.w, job.h, premul)) {
        drop();
        return;
    }
    PanelResult r{job.key, job.generation, job.w, job.h,
                  composite_panel(it->second.still, premul, job.w, job.h), 0.0};
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

void PanelWorker::set_panel(std::uint64_t key, assets::PanelFiles files,
                            std::filesystem::path albedo) {
    {
        std::lock_guard<std::mutex> lk(impl_->mu);
        const std::uint64_t gen = ++impl_->next_generation;
        impl_->current[key] = gen;
        impl_->queue.push_back(Load{key, gen, std::move(files), std::move(albedo)});
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
    return std::exchange(impl_->results, {});
}

void PanelWorker::clear_warnings() {
    std::lock_guard<std::mutex> lk(impl_->mu);
    impl_->warned.clear();
}

void PanelWorker::set_test_raster_delay(std::chrono::milliseconds d) {
    impl_->delay_ms.store(d.count());
}

}  // namespace lottie
