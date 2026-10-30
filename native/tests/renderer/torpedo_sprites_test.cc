// native/tests/renderer/torpedo_sprites_test.cc
//
// renderer::build_torpedo_sprites -- the CPU half of the instanced torpedo
// pass. TorpedoPass used to issue one draw (and six uniform uploads) per
// textured quad: 11 per photon, ~26,000 a frame with 2,350 torpedoes in
// flight. It now builds every quad here, grouped by texture, and draws each
// group with one instanced call.
//
// The reference below is the old per-layer loop, kept verbatim as the
// sequence of draw_layer() calls it made. The builder must emit exactly
// those quads -- same skips, same values, same order within a texture --
// so the batched pass draws the same picture. Torpedoes wholly outside the
// view are dropped; nothing else is.

#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/torpedo_anim.h>
#include <renderer/torpedo_sprites.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <string>
#include <vector>

namespace {

using renderer::TorpedoDescriptor;
using renderer::TorpedoSprite;
using renderer::TorpedoSpriteBatch;

struct RefQuad {
    std::string texture;
    glm::vec3 pos, axis_x, axis_y;
    float size;
    glm::vec4 tint;
    float alpha;
};

// The old TorpedoPass::render torpedo loop, minus GL.
std::vector<RefQuad> reference_quads(const std::vector<TorpedoDescriptor>& torpedoes,
                                     const glm::vec3& cam_pos,
                                     const glm::vec3& cam_up_world) {
    using namespace renderer;
    std::vector<RefQuad> out;
    auto draw_layer = [&](const std::string& path, const glm::vec4& color, float size,
                          const glm::vec3& world_pos, const glm::vec3& axis_x,
                          const glm::vec3& axis_y, float alpha) {
        if (path.empty() || size <= 0.0f) return;
        out.push_back({path, world_pos, axis_x, axis_y, size, color, alpha});
    };
    for (const auto& t : torpedoes) {
        if (t.is_disruptor) continue;
        const auto p = map_torpedo_params(t);
        const glm::mat3 root3 = torpedo_root_frame(
            cam_pos, t.world_pos, cam_up_world, t.age, p.spin_rate);
        const glm::vec3 x_r = root3[0];
        const glm::vec3 y_r = root3[1];
        const float pulse_half_size = 0.5f * glow_pulse_scale(
            t.age, p.pulse_rate, p.scale_lo, p.scale_hi);
        draw_layer(t.glow_texture, t.glow_color, pulse_half_size, t.world_pos, x_r, y_r, 1.2f);
        draw_layer(t.glow_texture, t.glow_color, 0.5f * p.clone_scale, t.world_pos, x_r, y_r, 1.2f);
        for (int i = 0; i < t.num_flares; ++i) {
            const glm::mat3 quad_basis = flare_basis(
                root3, static_cast<uint32_t>(t.id), static_cast<uint32_t>(i));
            float alpha = 1.0f;
            if (p.flare_period > 0.0f) {
                const float phi = hash01(static_cast<uint32_t>(t.id),
                                         static_cast<uint32_t>(i), 1u);
                const float u = std::fmod(t.age / p.flare_period + phi, 1.0f);
                alpha = flare_trapezoid(u);
            }
            if (alpha <= 0.0f) continue;
            draw_layer(t.flares_texture, t.flares_color, p.flare_half_size, t.world_pos,
                       quad_basis[0] * torpedo_anim_detail::kFlareAspect,
                       quad_basis[1], alpha);
        }
        draw_layer(t.core_texture, t.core_color, p.core_half_size, t.world_pos, x_r, y_r, 1.0f);
    }
    return out;
}

TorpedoDescriptor photon(glm::vec3 pos, int id, float age) {
    TorpedoDescriptor d;
    d.world_pos      = pos;
    d.core_texture   = "core.tga";
    d.core_color     = glm::vec4(1.0f, 0.9f, 0.8f, 1.0f);
    d.core_size_a    = 0.2f;
    d.core_size_b    = 1.2f;
    d.glow_texture   = "glow.tga";
    d.glow_color     = glm::vec4(1.0f, 0.4f, 0.2f, 1.0f);
    d.glow_size_a    = 3.0f;
    d.glow_size_b    = 0.3f;
    d.glow_size_c    = 0.6f;
    d.flares_texture = "flares.tga";
    d.flares_color   = glm::vec4(0.9f, 0.5f, 0.1f, 1.0f);
    d.num_flares     = 8;
    d.flares_size_a  = 0.7f;
    d.flares_size_b  = 0.4f;
    d.age            = age;
    d.id             = id;
    return d;
}

struct View {
    glm::vec3 eye{0.0f, 0.0f, 30.0f};
    glm::vec3 up{0.0f, 1.0f, 0.0f};
    glm::mat4 vp;
    View() {
        vp = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 1000.0f) *
             glm::lookAt(eye, glm::vec3(0.0f), up);
    }
};

std::vector<RefQuad> flatten(const std::vector<TorpedoSpriteBatch>& batches,
                             const std::string& texture) {
    std::vector<RefQuad> out;
    for (const auto& b : batches) {
        if (b.texture != texture) continue;
        for (const TorpedoSprite& s : b.sprites)
            out.push_back({b.texture, glm::vec3(s.centre_size), glm::vec3(s.axis_x_alpha),
                           glm::vec3(s.axis_y), s.centre_size.w, s.tint, s.axis_x_alpha.w});
    }
    return out;
}

std::size_t total_sprites(const std::vector<TorpedoSpriteBatch>& batches) {
    std::size_t n = 0;
    for (const auto& b : batches) n += b.sprites.size();
    return n;
}

void expect_same(const std::vector<RefQuad>& got, const std::vector<RefQuad>& want) {
    ASSERT_EQ(got.size(), want.size());
    for (std::size_t i = 0; i < got.size(); ++i) {
        EXPECT_EQ(got[i].pos, want[i].pos) << i;
        EXPECT_EQ(got[i].axis_x, want[i].axis_x) << i;
        EXPECT_EQ(got[i].axis_y, want[i].axis_y) << i;
        EXPECT_EQ(got[i].size, want[i].size) << i;
        EXPECT_EQ(got[i].tint, want[i].tint) << i;
        EXPECT_EQ(got[i].alpha, want[i].alpha) << i;
    }
}

std::vector<RefQuad> only(const std::vector<RefQuad>& quads, const std::string& texture) {
    std::vector<RefQuad> out;
    for (const auto& q : quads)
        if (q.texture == texture) out.push_back(q);
    return out;
}

}  // namespace

TEST(TorpedoSprites, EmitsExactlyTheQuadsTheOldLoopDrew) {
    View v;
    std::vector<TorpedoDescriptor> list;
    for (int i = 0; i < 40; ++i) {
        auto d = photon(glm::vec3(std::sin(i * 1.7f) * 8.0f, std::cos(i * 2.3f) * 6.0f,
                                  std::sin(i * 0.9f) * 4.0f), 100 + i, 0.07f * i);
        if (i % 5 == 0) d.num_flares = 3;
        if (i % 11 == 0) d.glow_texture = "glow_quantum.tga";
        list.push_back(d);
    }
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites(list, v.eye, v.up, v.vp, batches);

    const auto ref = reference_quads(list, v.eye, v.up);
    ASSERT_EQ(total_sprites(batches), ref.size());
    for (const char* tex : {"glow.tga", "glow_quantum.tga", "flares.tga", "core.tga"})
        expect_same(flatten(batches, tex), only(ref, tex));
}

TEST(TorpedoSprites, DisruptorsAreNotSprites) {
    View v;
    TorpedoDescriptor bolt;
    bolt.is_disruptor = true;
    bolt.bolt_length = 2.0f;
    bolt.bolt_width = 0.2f;
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites({bolt}, v.eye, v.up, v.vp, batches);
    EXPECT_EQ(total_sprites(batches), 0u);
}

TEST(TorpedoSprites, LayersWithNoTextureOrNoSizeAreSkipped) {
    View v;
    auto d = photon(glm::vec3(0.0f), 7, 0.1f);
    d.core_texture.clear();
    d.flares_size_a = 0.0f;
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites({d}, v.eye, v.up, v.vp, batches);
    EXPECT_TRUE(flatten(batches, "flares.tga").empty());
    EXPECT_EQ(flatten(batches, "glow.tga").size(), 2u);
    EXPECT_EQ(total_sprites(batches), 2u);
}

TEST(TorpedoSprites, TorpedoesOutsideTheViewAreDropped) {
    View v;
    const auto inside = photon(glm::vec3(0.0f), 1, 0.1f);
    const auto behind = photon(glm::vec3(0.0f, 0.0f, 60.0f), 2, 0.1f);
    const auto aside  = photon(glm::vec3(200.0f, 0.0f, 0.0f), 3, 0.1f);
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites({inside, behind, aside}, v.eye, v.up, v.vp, batches);
    expect_same(flatten(batches, "core.tga"),
                only(reference_quads({inside}, v.eye, v.up), "core.tga"));
    EXPECT_EQ(total_sprites(batches), reference_quads({inside}, v.eye, v.up).size());
}

TEST(TorpedoSprites, ATorpedoJustOffScreenWhoseGlowReachesInIsKept) {
    View v;
    // Half the 60 deg FOV at 30 GU is 30*tan(30 deg) = 17.32 GU to the edge.
    // Centre 0.1 GU outside it; the glow clone's half-size is 0.3 GU, so its
    // quad still crosses the edge.
    const float edge = 30.0f * std::tan(glm::radians(30.0f));
    const auto d = photon(glm::vec3(edge + 0.1f, 0.0f, 0.0f), 4, 0.1f);
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites({d}, v.eye, v.up, v.vp, batches);
    EXPECT_EQ(total_sprites(batches), reference_quads({d}, v.eye, v.up).size());
}

TEST(TorpedoSprites, ReusedBatchesHoldOnlyThisCallsQuads) {
    View v;
    std::vector<TorpedoSpriteBatch> batches;
    renderer::build_torpedo_sprites({photon(glm::vec3(0.0f), 1, 0.1f),
                                     photon(glm::vec3(1.0f), 2, 0.2f)},
                                    v.eye, v.up, v.vp, batches);
    const auto one = photon(glm::vec3(-1.0f), 3, 0.3f);
    renderer::build_torpedo_sprites({one}, v.eye, v.up, v.vp, batches);
    const auto ref = reference_quads({one}, v.eye, v.up);
    ASSERT_EQ(total_sprites(batches), ref.size());
    for (const char* tex : {"glow.tga", "flares.tga", "core.tga"})
        expect_same(flatten(batches, tex), only(ref, tex));
}
