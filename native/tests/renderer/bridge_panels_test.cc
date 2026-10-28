// native/tests/renderer/bridge_panels_test.cc
//
// Bridge Lottie panels (spec 2026-10-28-bridge-lottie-panels-design.md §5-7):
// renderer::BridgePanels, the render-thread store that keeps each drawn
// panel's playback state and live GL texture, feeds its PanelWorker and
// uploads finished frames. The model is built by hand: one 2x2 still texture,
// one PanelSource whose albedo is a TGA in a temp dir beside a copy of a
// lottie fixture, and a material with panel_index 0. Skips cleanly without a
// GL context (a hidden renderer::Window, as the other bridge GL tests).
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bridge_panels.h>
#include <renderer/bridge_quality.h>
#include <renderer/window.h>

#include <lottie/lottie_clip.h>
#include <lottie/panel_math.h>
#include <lottie/panel_worker.h>

#include <assets/file_bytes.h>

#include <assets/material.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;
using namespace std::chrono_literals;
using renderer::BridgeQuality;

namespace {

int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return static_cast<int>(::getpid());
#endif
}

fs::path fixture(const char* name) { return fs::path(LOTTIE_FIXTURES) / name; }

/// A 2x2 uncompressed 24-bit TGA, every pixel blue.
void write_blue_tga(const fs::path& p) {
    std::vector<std::uint8_t> tga = {0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                     2, 0, 2, 0, 24, 0};
    for (int i = 0; i < 4; ++i) tga.insert(tga.end(), {0xFF, 0x00, 0x00});  // BGR
    std::ofstream(p, std::ios::binary)
        .write(reinterpret_cast<const char*>(tga.data()),
               static_cast<std::streamsize>(tga.size()));
}

struct Readback {
    int w = 0, h = 0;
    std::vector<std::uint8_t> rgba;
};

Readback read_texture(GLuint tex) {
    Readback r;
    glBindTexture(GL_TEXTURE_2D, tex);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &r.w);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &r.h);
    r.rgba.resize(static_cast<std::size_t>(r.w) * r.h * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, r.rgba.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    return r;
}

bool all_red(const Readback& r) {
    if (r.rgba.empty()) return false;
    for (std::size_t i = 0; i < r.rgba.size(); i += 4)
        if (r.rgba[i] != 255 || r.rgba[i + 1] != 0 || r.rgba[i + 2] != 0) return false;
    return true;
}

class BridgePanels : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> win;
    fs::path dir;
    fs::path albedo;
    std::unique_ptr<assets::Model> model;
    std::unique_ptr<renderer::BridgePanels> panels;
    unsigned long long handle = 0;
    int state = 0;
    BridgeQuality quality = BridgeQuality::Medium;

    void SetUp() override {
        try {
            win = std::make_unique<renderer::Window>(64, 64, "bridge-panels-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        auto base = fs::temp_directory_path() / "bridge-panels";
        for (int i = 0;; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(current_pid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { dir = candidate; break; }
        }
        fs::create_directories(dir);
        albedo = dir / "hull.tga";
        write_blue_tga(albedo);
        model = make_model();
        handle = reinterpret_cast<unsigned long long>(model.get());
        panels = std::make_unique<renderer::BridgePanels>();
    }

    void TearDown() override {
        panels.reset();   // textures die with the context still current
        model.reset();
        win.reset();
        std::error_code ec;
        if (!dir.empty()) fs::remove_all(dir, ec);
    }

    std::unique_ptr<assets::Model> make_model() const {
        auto m = std::make_unique<assets::Model>();
        assets::Image img;
        img.width = 2;
        img.height = 2;
        img.format = assets::Image::Format::RGBA8;
        img.pixels.assign(16, 0);
        for (int i = 0; i < 4; ++i) { img.pixels[i * 4 + 2] = 255; img.pixels[i * 4 + 3] = 255; }
        m->textures.push_back(assets::upload_image(img, /*generate_mipmaps=*/false));
        m->panel_sources.push_back(assets::PanelSource{albedo, {dir}, 0});
        assets::Material mat;
        mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = 0;
        mat.panel_index = 0;
        m->materials.push_back(mat);
        return m;
    }

    void place(const char* fixture_name, const char* as = "hull.json") {
        fs::copy_file(fixture(fixture_name), dir / as, fs::copy_options::overwrite_existing);
    }

    GLuint live() const { return panels->live_texture(handle, *model, 0); }

    /// One frame: the draw (when `mark`) then the per-frame update.
    void frame(double t, bool mark = true) {
        if (mark) panels->mark_drawn(handle, *model, 0, state);
        panels->update(t, quality);
    }

    /// frame() every 5 ms until `until` holds or `limit` passes.
    bool pump(double t, const std::function<bool()>& until,
              std::chrono::milliseconds limit = 2000ms, bool mark = true) {
        const auto deadline = std::chrono::steady_clock::now() + limit;
        for (;;) {
            frame(t, mark);
            if (until && until()) return true;
            if (std::chrono::steady_clock::now() >= deadline) return false;
            std::this_thread::sleep_for(5ms);
        }
    }
};

}  // namespace

TEST_F(BridgePanels, NoJsonNeverMakesALiveTexture) {
    pump(0.0, nullptr, 200ms);
    EXPECT_EQ(live(), 0u);
}

TEST_F(BridgePanels, MarkedPanelGetsALiveTexture) {
    place("solid_red.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    const Readback r = read_texture(live());
    EXPECT_EQ(r.w, 1024);   // 64x32 canvas, Medium's 1024 long edge
    EXPECT_EQ(r.h, 512);
    EXPECT_TRUE(all_red(r));
    // The still the model holds is never the live texture.
    EXPECT_NE(live(), model->textures[0].id());
}

TEST_F(BridgePanels, ImageChangesWithTime) {
    place("slide.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    const Readback first = read_texture(live());
    EXPECT_TRUE(pump(0.5, [&] { return read_texture(live()).rgba != first.rgba; }));
}

TEST_F(BridgePanels, PausedClockSubmitsNoJobs) {
    place("solid_red.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    EXPECT_GE(panels->take_stats().jobs, 1);
    for (int i = 0; i < 20; ++i) {
        frame(0.0);
        std::this_thread::sleep_for(5ms);
    }
    EXPECT_EQ(panels->take_stats().jobs, 0);
}

TEST_F(BridgePanels, UnmarkedPanelSubmitsNoJobs) {
    place("slide.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    panels->take_stats();
    // The clock runs on, but nothing draws the panel.
    for (int i = 1; i <= 20; ++i) {
        frame(0.1 * i, /*mark=*/false);
        std::this_thread::sleep_for(5ms);
    }
    EXPECT_EQ(panels->take_stats().jobs, 0);
}

TEST_F(BridgePanels, StateChangeRestartsAndFallsBack) {
    place("slide.json");
    place("solid_red.json", "hull_y.json");
    // Green plays the default (slide over the blue still): frame 0 at t = 0.
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    const Readback frame0 = read_texture(live());
    ASSERT_FALSE(all_red(frame0));
    // Red with no _r file falls back to the yellow one: solid red.
    state = 2;
    EXPECT_TRUE(pump(0.5, [&] { return all_red(read_texture(live())); }));
    // Back to green at t = 0.5: the default restarts from its first frame,
    // where an unrestarted clock would show frame 0.5 s in.
    state = 0;
    ASSERT_TRUE(pump(0.5, [&] { return !all_red(read_texture(live())); }));
    EXPECT_EQ(read_texture(live()).rgba, frame0.rgba);
}

TEST_F(BridgePanels, InvalidJsonShowsStill) {
    place("broken.json");
    pump(0.0, nullptr, 300ms);
    EXPECT_EQ(live(), 0u);
}

// With every raster sleeping 300 ms first, no update waits for one, and an
// update that uploads stays inside the same bound: the result buffer is a
// plain array, so taking and freeing it is one delete[] (a 2 MB
// std::vector<uint8_t> took ~5.5 ms to destroy element-wise in the Debug
// build; task 5 fix report).
TEST_F(BridgePanels, UpdateNeverBlocks) {
    place("solid_red.json");
    panels->worker_for_test().set_test_raster_delay(300ms);
    double worst_ms = 0.0;
    int jobs = 0, uploads = 0;
    const auto deadline = std::chrono::steady_clock::now() + 1000ms;
    for (int i = 0; std::chrono::steady_clock::now() < deadline; ++i) {
        const auto t0 = std::chrono::steady_clock::now();
        frame(0.04 * i);
        const double ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0)
                .count();
        worst_ms = std::max(worst_ms, ms);
        const auto s = panels->take_stats();
        jobs += s.jobs;
        uploads += s.uploads;
        std::this_thread::sleep_for(5ms);
    }
    EXPECT_LT(worst_ms, 5.0);
    // The delay really was in play, and results did land inside the bound.
    EXPECT_GE(jobs, 2);
    EXPECT_GE(uploads, 1);
}

TEST_F(BridgePanels, DifferentModelUnderSameHandleDropsTheOldEntry) {
    place("solid_red.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    // The cache freed model A and a new model B came back under the same
    // handle value.
    auto b = make_model();
    panels->mark_drawn(handle, *b, 0, 0);
    EXPECT_EQ(panels->live_texture(handle, *model, 0), 0u);
    EXPECT_EQ(panels->live_texture(handle, *b, 0), 0u);   // not A's image
    const auto deadline = std::chrono::steady_clock::now() + 2000ms;
    while (panels->live_texture(handle, *b, 0) == 0 &&
           std::chrono::steady_clock::now() < deadline) {
        panels->mark_drawn(handle, *b, 0, 0);
        panels->update(0.0, quality);
        std::this_thread::sleep_for(5ms);
    }
    const GLuint tb = panels->live_texture(handle, *b, 0);
    ASSERT_NE(tb, 0u);
    EXPECT_TRUE(all_red(read_texture(tb)));
    EXPECT_EQ(panels->live_texture(handle, *model, 0), 0u);
}

TEST_F(BridgePanels, QualityChangeReallocatesAndDiscardsStaleResult) {
    place("solid_red.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    ASSERT_EQ(read_texture(live()).w, 1024);
    // A slow raster, then a new tick: a Medium-sized job is in flight...
    panels->worker_for_test().set_test_raster_delay(150ms);
    panels->take_stats();
    frame(0.1);
    ASSERT_EQ(panels->take_stats().jobs, 1);
    // ...and has finished by the time the quality drops to Low: the switch's
    // own update takes it, and must discard it rather than upload it.
    std::this_thread::sleep_for(400ms);
    quality = BridgeQuality::Low;
    frame(0.1);
    EXPECT_EQ(panels->take_stats().uploads, 0);
    EXPECT_EQ(live(), 0u);
    bool saw_wide = false;
    const bool low = pump(0.1, [&] {
        const GLuint t = live();
        if (t == 0) return false;
        const Readback r = read_texture(t);
        if (r.w != 512) saw_wide = true;
        return r.w == 512;
    });
    ASSERT_TRUE(low);
    EXPECT_FALSE(saw_wide);
    const Readback r = read_texture(live());
    EXPECT_EQ(r.w, 512);
    EXPECT_EQ(r.h, 256);
    EXPECT_TRUE(all_red(r));
}

TEST_F(BridgePanels, ReloadPicksUpAddedAndDeletedFiles) {
    pump(0.0, nullptr, 100ms);
    ASSERT_EQ(live(), 0u);
    place("solid_red.json");
    panels->reload();
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    fs::remove(dir / "hull.json");
    panels->reload();
    EXPECT_TRUE(pump(0.0, [&] { return live() == 0; }));
}

// Uploads bind on unit 0 and leave every other unit's binding alone.
TEST_F(BridgePanels, UploadTouchesOnlyUnitZero) {
    place("solid_red.json");
    GLuint other = 0;
    glGenTextures(1, &other);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, other);
    ASSERT_TRUE(pump(0.0, [&] {
        glActiveTexture(GL_TEXTURE3);
        GLint bound = 0;
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound);
        EXPECT_EQ(static_cast<GLuint>(bound), other);
        return live() != 0;
    }));
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glDeleteTextures(1, &other);
}

// Only changed rectangles are uploaded (spec §7 budget): pasted one onto the
// other, the texture is always exactly the whole composite of the frame the
// clock asks for, never a mix of frames.
TEST_F(BridgePanels, PartialUploadsKeepTheTextureExact) {
    place("slide.json");
    auto clip = lottie::LottieClip::load(dir / "hull.json", nullptr);
    ASSERT_TRUE(clip);
    auto bytes = assets::read_binary_file(albedo);
    ASSERT_TRUE(bytes);
    const assets::Image still = assets::decode_image(*bytes);
    auto want_at = [&](double t, int w, int h) {
        const lottie::PanelTick tick = lottie::panel_tick(t, 0.0, clip->total_frames(), clip->fps());
        std::vector<std::uint8_t> premul;
        clip->render(tick.frame, static_cast<std::uint32_t>(w), static_cast<std::uint32_t>(h),
                     premul);
        return lottie::composite_panel(still, premul, static_cast<std::uint32_t>(w),
                                       static_cast<std::uint32_t>(h));
    };
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    for (double t : {0.0, 0.1, 0.2, 0.5, 0.9}) {
        EXPECT_TRUE(pump(t, [&] {
            const Readback r = read_texture(live());
            return r.rgba == want_at(t, r.w, r.h);
        })) << "t = " << t;
    }
}

TEST_F(BridgePanels, UnchangedFramesUploadNothing) {
    place("solid_red.json");
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    panels->take_stats();
    int jobs = 0, uploads = 0;
    for (int i = 1; i <= 20; ++i) {
        frame(0.05 * i);
        std::this_thread::sleep_for(10ms);
        const auto s = panels->take_stats();
        jobs += s.jobs;
        uploads += s.uploads;
    }
    EXPECT_GE(jobs, 2);       // the clock ran, so frames were asked for...
    EXPECT_EQ(uploads, 0);    // ...but every one was the same solid red
    EXPECT_TRUE(all_red(read_texture(live())));
}

// A partial result that lands on a texture reallocated while it was in flight
// (quality down and back up) is not uploaded: the panel asks again for the
// whole frame at the same tick, so the texture ends up exact, not a patch over
// an empty one.
TEST_F(BridgePanels, ReallocatedTextureNeverTakesAPartial) {
    place("slide.json");
    auto clip = lottie::LottieClip::load(dir / "hull.json", nullptr);
    ASSERT_TRUE(clip);
    auto bytes = assets::read_binary_file(albedo);
    ASSERT_TRUE(bytes);
    const assets::Image still = assets::decode_image(*bytes);
    ASSERT_TRUE(pump(0.0, [&] { return live() != 0; }));
    pump(0.0, nullptr, 100ms);
    panels->worker_for_test().set_test_raster_delay(150ms);
    panels->take_stats();
    frame(0.1);                                   // a partial job, in flight
    ASSERT_EQ(panels->take_stats().jobs, 1);
    quality = BridgeQuality::Low;
    frame(0.1);
    quality = BridgeQuality::Medium;
    frame(0.1);                                   // same size again, new texture
    std::this_thread::sleep_for(400ms);
    panels->worker_for_test().set_test_raster_delay(0ms);
    const lottie::PanelTick tick = lottie::panel_tick(0.1, 0.0, clip->total_frames(), clip->fps());
    EXPECT_TRUE(pump(0.1, [&] {
        const GLuint t = live();
        if (t == 0) return false;
        const Readback r = read_texture(t);
        std::vector<std::uint8_t> premul;
        clip->render(tick.frame, static_cast<std::uint32_t>(r.w), static_cast<std::uint32_t>(r.h),
                     premul);
        return r.rgba == lottie::composite_panel(still, premul, static_cast<std::uint32_t>(r.w),
                                                 static_cast<std::uint32_t>(r.h));
    }));
}
