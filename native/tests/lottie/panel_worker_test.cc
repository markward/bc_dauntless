#include <lottie/lottie_clip.h>
#include <lottie/panel_math.h>
#include <lottie/panel_worker.h>

#include <assets/file_bytes.h>
#include <assets/texture.h>

#include <gtest/gtest.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;
using namespace std::chrono_literals;

// The result buffer is a plain array: destroying it is one delete[], never
// a per-element loop (a 2 MB std::vector<uint8_t> took ~5 ms to destroy in
// the Debug build, on the render thread and under the worker mutex).
static_assert(std::is_same_v<decltype(lottie::PanelResult::rgba),
                             std::unique_ptr<std::uint8_t[]>>);

namespace {

inline int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return static_cast<int>(::getpid());
#endif
}

fs::path fixture(const char* name) {
    return fs::path(LOTTIE_FIXTURES) / name;
}

bool wait_for(const std::function<bool()>& pred,
              std::chrono::milliseconds timeout = 2000ms) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (pred()) return true;
        std::this_thread::sleep_for(5ms);
    }
    return pred();
}

std::size_t count_of(const std::string& haystack, const std::string& needle) {
    std::size_t n = 0;
    for (auto at = haystack.find(needle); at != std::string::npos;
         at = haystack.find(needle, at + needle.size()))
        ++n;
    return n;
}

class PanelWorker : public ::testing::Test {
protected:
    fs::path tmp_dir;
    fs::path still;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "lottie-pw";
        for (int i = 0;; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(current_pid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
        // 2x1 uncompressed 24-bit TGA (blue, red).
        const std::vector<std::uint8_t> tga = {
            0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 24, 0,
            0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
        still = tmp_dir / "panel.tga";
        std::ofstream out(still, std::ios::binary);
        out.write(reinterpret_cast<const char*>(tga.data()),
                  static_cast<std::streamsize>(tga.size()));
    }
    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }

    // Copies a fixture beside the still as `as`: the worker finds a panel's
    // files itself, from the still's stem and its probe dirs.
    fs::path put(const char* name, const char* as = "panel.json") {
        const fs::path to = tmp_dir / as;
        fs::copy_file(fixture(name), to, fs::copy_options::overwrite_existing);
        return to;
    }
    std::vector<fs::path> dirs() const { return {tmp_dir}; }

    static std::optional<lottie::PanelInfo> await_info(lottie::PanelWorker& w,
                                                       std::uint64_t key) {
        wait_for([&] { return w.info(key).has_value(); });
        return w.info(key);
    }

    static std::optional<lottie::PanelInfo> await_new_info(lottie::PanelWorker& w,
                                                           std::uint64_t key,
                                                           std::uint64_t old_gen) {
        wait_for([&] {
            auto i = w.info(key);
            return i && i->generation != old_gen;
        });
        return w.info(key);
    }

    static std::vector<lottie::PanelResult> await_results(lottie::PanelWorker& w) {
        std::vector<lottie::PanelResult> got;
        wait_for([&] {
            auto r = w.take_results();
            got.insert(got.end(), std::make_move_iterator(r.begin()),
                       std::make_move_iterator(r.end()));
            return !got.empty();
        });
        return got;
    }
};

}  // namespace

TEST_F(PanelWorker, InfoAppearsAfterLoad) {
    lottie::PanelWorker w;
    put("solid_red.json");
    w.set_panel(7, still, dirs());
    auto info = await_info(w, 7);
    ASSERT_TRUE(info);
    EXPECT_TRUE(info->valid[0]);
    EXPECT_FALSE(info->valid[1]);
    EXPECT_FALSE(info->valid[2]);
    EXPECT_FALSE(info->valid[3]);
    EXPECT_FLOAT_EQ(info->canvas_w, 64.f);
    EXPECT_FLOAT_EQ(info->canvas_h, 32.f);
    EXPECT_FLOAT_EQ(info->total_frames[0], 30.f);
    EXPECT_NEAR(info->fps[0], 30.f, 1e-3);
    EXPECT_FALSE(w.info(8).has_value());
}

TEST_F(PanelWorker, JobProducesCompositedResult) {
    lottie::PanelWorker w;
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto info = await_info(w, 1);
    ASSERT_TRUE(info);
    ASSERT_TRUE(w.submit({1, 0, 0.f, 64, 32, info->generation}));
    auto results = await_results(w);
    ASSERT_EQ(results.size(), 1u);
    const auto& r = results[0];
    EXPECT_EQ(r.key, 1u);
    EXPECT_EQ(r.generation, info->generation);
    EXPECT_EQ(r.w, 64u);
    EXPECT_EQ(r.h, 32u);
    ASSERT_EQ(r.bytes, 64u * 32u * 4u);
    ASSERT_TRUE(r.rgba);
    for (std::size_t i = 0; i < r.bytes; i += 4) {
        ASSERT_EQ(r.rgba[i + 0], 255) << i;
        ASSERT_EQ(r.rgba[i + 1], 0) << i;
        ASSERT_EQ(r.rgba[i + 2], 0) << i;
        ASSERT_EQ(r.rgba[i + 3], 255) << i;
    }
    EXPECT_GE(r.raster_ms, 0.0);
}

TEST_F(PanelWorker, SecondSubmitWhileBusyIsRefused) {
    lottie::PanelWorker w;
    w.set_test_raster_delay(200ms);
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto info = await_info(w, 1);
    ASSERT_TRUE(info);
    const lottie::PanelJob job{1, 0, 0.f, 64, 32, info->generation};
    EXPECT_TRUE(w.submit(job));
    EXPECT_FALSE(w.submit(job));
    auto results = await_results(w);
    EXPECT_EQ(results.size(), 1u);
    EXPECT_TRUE(w.submit(job));
}

TEST_F(PanelWorker, InvalidDefaultIsNotValid) {
    const fs::path broken = put("broken.json");
    testing::internal::CaptureStderr();
    {
        lottie::PanelWorker w;
        w.set_panel(1, still, dirs());
        auto first = await_info(w, 1);
        w.set_panel(1, still, dirs());
        auto second = await_new_info(w, 1, first ? first->generation : 0);
        ASSERT_TRUE(first);
        ASSERT_TRUE(second);
        EXPECT_NE(second->generation, first->generation);
        EXPECT_FALSE(second->valid[0]);
    }
    const std::string err = testing::internal::GetCapturedStderr();
    EXPECT_EQ(count_of(err, "using the still"), 1u) << err;
    EXPECT_NE(err.find("[lottie] " + broken.string() + ": "),
              std::string::npos) << err;
}

TEST_F(PanelWorker, ClearWarningsWarnsAgain) {
    put("broken.json");
    testing::internal::CaptureStderr();
    {
        lottie::PanelWorker w;
        w.set_panel(1, still, dirs());
        auto first = await_info(w, 1);
        ASSERT_TRUE(first);
        w.clear_warnings();
        w.set_panel(1, still, dirs());
        ASSERT_TRUE(await_new_info(w, 1, first->generation));
    }
    const std::string err = testing::internal::GetCapturedStderr();
    EXPECT_EQ(count_of(err, "using the still"), 2u) << err;
}

TEST_F(PanelWorker, SetPanelDropsOlderGenerationResults) {
    lottie::PanelWorker w;
    w.set_test_raster_delay(200ms);
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto first = await_info(w, 1);
    ASSERT_TRUE(first);
    ASSERT_TRUE(w.submit({1, 0, 0.f, 64, 32, first->generation}));
    w.set_panel(1, still, dirs());
    auto second = await_new_info(w, 1, first->generation);
    ASSERT_TRUE(second);
    std::this_thread::sleep_for(50ms);
    for (const auto& r : w.take_results())
        EXPECT_NE(r.generation, first->generation);
}

// set_panel always looks again: a deleted file reverts to the still, a file
// added since is found (the dev reload relies on both).
TEST_F(PanelWorker, DeletedFileClearsValidity) {
    lottie::PanelWorker w;
    const fs::path json = put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto first = await_info(w, 1);
    ASSERT_TRUE(first);
    ASSERT_TRUE(first->valid[0]);
    fs::remove(json);
    w.set_panel(1, still, dirs());
    auto second = await_new_info(w, 1, first->generation);
    ASSERT_TRUE(second);
    for (bool v : second->valid) EXPECT_FALSE(v);
}

TEST_F(PanelWorker, AddedFileIsFoundOnTheNextSetPanel) {
    lottie::PanelWorker w;
    w.set_panel(1, still, dirs());
    auto first = await_info(w, 1);
    ASSERT_TRUE(first);
    for (bool v : first->valid) EXPECT_FALSE(v);
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto second = await_new_info(w, 1, first->generation);
    ASSERT_TRUE(second);
    EXPECT_TRUE(second->valid[0]);
    EXPECT_FLOAT_EQ(second->canvas_w, 64.f);
}

// A state file with no default beside it warns once per file (spec §5), not
// once per load; a dev reload lets it warn again.
TEST_F(PanelWorker, OrphanStateFileWarnsOncePerFile) {
    const fs::path orphan = put("solid_red.json", "panel_y.json");
    testing::internal::CaptureStderr();
    {
        lottie::PanelWorker w;
        std::uint64_t gen = 0;
        for (int i = 0; i < 3; ++i) {
            if (i == 2) w.clear_warnings();
            w.set_panel(1, still, dirs());
            auto info = await_new_info(w, 1, gen);
            ASSERT_TRUE(info);
            for (bool v : info->valid) EXPECT_FALSE(v);
            gen = info->generation;
        }
    }
    const std::string err = testing::internal::GetCapturedStderr();
    const std::string want = "[lottie] " + orphan.string() + ": no panel.json beside it; ignored";
    EXPECT_EQ(count_of(err, want), 2u) << err;
}

TEST_F(PanelWorker, DestroyWithJobInFlightJoins) {
    auto w = std::make_unique<lottie::PanelWorker>();
    w->set_test_raster_delay(300ms);
    put("solid_red.json");
    w->set_panel(1, still, dirs());
    auto info = await_info(*w, 1);
    ASSERT_TRUE(info);
    ASSERT_TRUE(w->submit({1, 0, 0.f, 64, 32, info->generation}));
    std::this_thread::sleep_for(20ms);  // let the worker pick the job up
    const auto t0 = std::chrono::steady_clock::now();
    w.reset();
    EXPECT_LT(std::chrono::steady_clock::now() - t0, 1s);
}

TEST_F(PanelWorker, UnreadableStillCompositesOverTransparentBlack) {
    const fs::path missing = tmp_dir / "missing.tga";
    testing::internal::CaptureStderr();
    std::vector<lottie::PanelResult> results;
    {
        lottie::PanelWorker w;
        // slide.json frame 0: an opaque white square on the left, clear at x=59.
        put("slide.json", "missing.json");
        w.set_panel(1, missing, dirs());
        auto info = await_info(w, 1);
        ASSERT_TRUE(info);
        ASSERT_TRUE(info->valid[0]);
        ASSERT_TRUE(w.submit({1, 0, 0.f, 64, 32, info->generation}));
        results = await_results(w);
    }
    const std::string err = testing::internal::GetCapturedStderr();
    ASSERT_EQ(results.size(), 1u);
    const auto& rgba = results[0].rgba;
    const std::size_t clear = (16u * 64u + 59u) * 4u;
    EXPECT_EQ(rgba[clear + 0], 0);
    EXPECT_EQ(rgba[clear + 1], 0);
    EXPECT_EQ(rgba[clear + 2], 0);
    EXPECT_EQ(rgba[clear + 3], 0);
    const std::size_t lit = (16u * 64u + 5u) * 4u;
    EXPECT_EQ(rgba[lit + 0], 255);
    EXPECT_EQ(rgba[lit + 3], 255);
    EXPECT_EQ(count_of(err, missing.string()), 1u) << err;
}

TEST_F(PanelWorker, StateFileWithOtherAspectWarnsOnceAndStaysValid) {
    // A square copy of solid_red as the red-alert file.
    std::ifstream in(fixture("solid_red.json"));
    std::string json((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    const auto at = json.find("\"w\":64");
    ASSERT_NE(at, std::string::npos);
    json.replace(at, 6, "\"w\":32");
    const fs::path square = tmp_dir / "panel_r.json";
    std::ofstream(square) << json;

    put("solid_red.json");
    testing::internal::CaptureStderr();
    {
        lottie::PanelWorker w;
        w.set_panel(1, still, dirs());
        auto first = await_info(w, 1);
        ASSERT_TRUE(first);
        EXPECT_TRUE(first->valid[assets::kPanelRed]);
        EXPECT_FLOAT_EQ(first->canvas_w, 64.f);
        w.set_panel(1, still, dirs());
        ASSERT_TRUE(await_new_info(w, 1, first->generation));
    }
    const std::string err = testing::internal::GetCapturedStderr();
    const std::string want = "[lottie] " + square.string() +
                             ": canvas aspect differs from panel.json; stretched";
    EXPECT_EQ(count_of(err, want), 1u) << err;
}

TEST_F(PanelWorker, ResultFinishedBeforeSetPanelIsNotDelivered) {
    lottie::PanelWorker w;
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto first = await_info(w, 1);
    ASSERT_TRUE(first);
    ASSERT_TRUE(w.submit({1, 0, 0.f, 64, 32, first->generation}));
    // FIFO: once key 2 has loaded, key 1's result is already queued.
    w.set_panel(2, still, dirs());
    ASSERT_TRUE(await_info(w, 2));
    w.set_panel(1, still, dirs());
    for (const auto& r : w.take_results())
        EXPECT_FALSE(r.key == 1 && r.generation == first->generation);
}

TEST_F(PanelWorker, ResultFinishedBeforeRemovePanelIsNotDelivered) {
    lottie::PanelWorker w;
    put("solid_red.json");
    w.set_panel(1, still, dirs());
    auto first = await_info(w, 1);
    ASSERT_TRUE(first);
    ASSERT_TRUE(w.submit({1, 0, 0.f, 64, 32, first->generation}));
    w.set_panel(2, still, dirs());
    ASSERT_TRUE(await_info(w, 2));
    w.remove_panel(1);
    for (const auto& r : w.take_results()) EXPECT_NE(r.key, 1u);
}

TEST_F(PanelWorker, InvalidDefaultTakesCanvasFromFirstValidVariant) {
    put("broken.json");
    put("solid_red.json", "panel_y.json");
    testing::internal::CaptureStderr();
    std::optional<lottie::PanelInfo> info;
    {
        lottie::PanelWorker w;
        w.set_panel(1, still, dirs());
        info = await_info(w, 1);
    }
    testing::internal::GetCapturedStderr();
    ASSERT_TRUE(info);
    EXPECT_FALSE(info->valid[0]);
    EXPECT_TRUE(info->valid[1]);
    EXPECT_FALSE(info->valid[2]);
    EXPECT_FALSE(info->valid[3]);
    EXPECT_FLOAT_EQ(info->canvas_w, 64.f);
    EXPECT_FLOAT_EQ(info->canvas_h, 32.f);
}

// The worker scales the still once per (panel, size) and reuses it: every
// result, across size changes, is still exactly composite_panel's bytes.
TEST_F(PanelWorker, CachedStillMatchesCompositeAcrossSizeChanges) {
    auto bytes = assets::read_binary_file(still);
    ASSERT_TRUE(bytes);
    const assets::Image image = assets::decode_image(*bytes);
    auto clip = lottie::LottieClip::load(fixture("slide.json"), nullptr);
    ASSERT_TRUE(clip);

    lottie::PanelWorker w;
    put("slide.json");
    w.set_panel(1, still, dirs());
    auto info = await_info(w, 1);
    ASSERT_TRUE(info);
    const std::pair<std::uint32_t, std::uint32_t> sizes[] = {{64, 32}, {32, 16}, {32, 16}, {64, 32}};
    float frame = 0.f;
    for (auto [sw, sh] : sizes) {
        ASSERT_TRUE(w.submit({1, 0, frame, sw, sh, info->generation}));
        auto results = await_results(w);
        ASSERT_EQ(results.size(), 1u);
        std::vector<std::uint8_t> premul;
        ASSERT_TRUE(clip->render(frame, sw, sh, premul));
        const auto want = lottie::composite_panel(image, premul, sw, sh);
        ASSERT_EQ(results[0].bytes, want.size());
        EXPECT_EQ(std::vector<std::uint8_t>(results[0].rgba.get(),
                                            results[0].rgba.get() + results[0].bytes), want)
            << sw << "x" << sh << " frame " << frame;
        frame += 20.f;
    }
}
