// native/src/assets/src/animation_load.cc
#include <assets/animation.h>

#include <nif/block.h>
#include <nif/file.h>

#include <variant>

#include "animation_build.h"

namespace assets {
namespace {

// NIF stores the node rotation row-major; our mat4 is column-vector, so rows
// become columns. Mirrors model_build.cc / skeleton_build.cc av_to_local.
glm::mat4 av_to_local(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    const auto& r = av.rotation.m;
    m[0] = glm::vec4(r[0], r[3], r[6], 0.0f);
    m[1] = glm::vec4(r[1], r[4], r[7], 0.0f);
    m[2] = glm::vec4(r[2], r[5], r[8], 0.0f);
    m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
    if (av.scale != 1.0f) { m[0] *= av.scale; m[1] *= av.scale; m[2] *= av.scale; }
    return m;
}

}  // namespace

std::vector<AnimationClip> load_animation_clips(
    const std::filesystem::path& nif_path) {
    try {
        nif::File f = nif::load(nif_path.string());
        std::vector<AnimationClip> clips = detail::build_animations(f);

        // Capture the source NIF's per-node REST local transforms (the placed
        // standing pose the clip animates around) so sample_pose can use them as
        // the per-bone base instead of the body's T-pose bind.
        std::unordered_map<std::string, glm::mat4> rest;
        for (const auto& blk : f.blocks) {
            const auto* n = std::get_if<nif::NiNode>(&blk);
            if (!n || n->av.obj.name.empty()) continue;
            rest[n->av.obj.name] = av_to_local(n->av);
        }
        for (auto& c : clips) c.rest_locals = rest;
        return clips;
    } catch (const std::exception&) {
        return {};  // unreadable / unparseable NIF -> no clips
    }
}

}  // namespace assets
