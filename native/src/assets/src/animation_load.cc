// native/src/assets/src/animation_load.cc
#include <assets/animation.h>

#include <nif/block.h>
#include <nif/file.h>

#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <string_view>
#include <variant>

#include <assets/pose_sample.h>

#include "animation_build.h"

namespace assets {
namespace {

// Build a node's parent-relative LOCAL transform from its NiAVObject fields.
// Mirrors model_build.cc's av_to_local_transform: the NIF stores the rotation
// row-major; our mat4 is column-vector, so the rows become the columns.
glm::mat4 av_to_local(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    const auto& r = av.rotation.m;
    m[0] = glm::vec4(r[0], r[3], r[6], 0.0f);
    m[1] = glm::vec4(r[1], r[4], r[7], 0.0f);
    m[2] = glm::vec4(r[2], r[5], r[8], 0.0f);
    m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
    if (av.scale != 1.0f) {
        m[0] *= av.scale;
        m[1] *= av.scale;
        m[2] *= av.scale;
    }
    return m;
}

}  // namespace

std::vector<AnimationClip> load_animation_clips(
    const std::filesystem::path& nif_path) {
    try {
        nif::File f = nif::load(nif_path.string());
        return detail::build_animations(f);
    } catch (const std::exception&) {
        return {};  // unreadable / unparseable NIF -> no clips
    }
}

std::unordered_map<std::string, glm::mat4> load_pose_locals(
    const std::filesystem::path& nif_path, bool sample_at_start) {
    std::unordered_map<std::string, glm::mat4> out;
    try {
        nif::File f = nif::load(nif_path.string());

        // 1. Each NiNode's REST local transform (the placement skeleton). This
        //    is the per-channel fallback for bones the keyframes don't fully
        //    drive (e.g. a rotation-only track keeps the rest translation).
        std::unordered_map<std::string, const nif::AvObjectBase*> rest;
        for (const auto& blk : f.blocks) {
            const auto* n = std::get_if<nif::NiNode>(&blk);
            if (!n || n->av.obj.name.empty()) continue;
            rest[n->av.obj.name] = &n->av;
        }

        // The rest pose (static node skeleton) gives a correctly placed officer
        // with a correct LOWER body for every clip — that's the base. But its
        // UPPER body is a T-pose-ish rest (arms out, shoulders low → long neck).
        // The clip's keyframe rotations settle the upper body into the standing
        // pose. Applying keyframes to the WHOLE skeleton also disturbs the
        // (already-correct) lower body and the root placement, and the sampled
        // frame is bad for some clips. So overlay keyframes ONLY on the upper-
        // body chain (arms, neck, head); keep root/spine/legs at rest.
        auto is_upper_body = [](std::string_view n) {
            for (const char* k : {"Clavicle", "UpperArm", "Forearm", "Hand",
                                  "Finger", "Neck", "Head", "Ponytail"})
                if (n.find(k) != std::string_view::npos) return true;
            return false;
        };
        std::vector<AnimationClip> clips = detail::build_animations(f);
        const float dur = clips.empty() ? 0.0f : clips.front().duration_seconds;
        const float t = sample_at_start ? 0.0f : dur;

        for (const auto& [name, av] : rest) {
            if (!is_upper_body(name)) { out[name] = av_to_local(*av); continue; }
            const glm::vec3 rest_t = glm::vec3(av->translation.x,
                                               av->translation.y,
                                               av->translation.z);
            const glm::quat rest_r = glm::quat_cast(glm::mat3(av_to_local(*av)));
            const float rest_s = av->scale;
            const AnimationClip::NodeTrack* tr = nullptr;
            if (!clips.empty())
                for (const auto& cand : clips.front().tracks)
                    if (cand.target_node_name == name) { tr = &cand; break; }
            out[name] = tr ? sample_track_trs(*tr, t, rest_t, rest_r, rest_s)
                           : av_to_local(*av);
        }
    } catch (const std::exception&) {
        return {};  // unreadable / unparseable NIF
    }
    return out;
}

}  // namespace assets
