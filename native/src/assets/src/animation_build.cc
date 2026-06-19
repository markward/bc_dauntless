#include "animation_build.h"
#include "link_resolver.h"

#include <nif/block.h>

#include <algorithm>
#include <unordered_map>

namespace assets::detail {

namespace {

template <typename DataBlock>
const DataBlock* data_at(const nif::File& f, std::uint32_t block_index) {
    if (block_index >= f.blocks.size()) return nullptr;
    return std::get_if<DataBlock>(&f.blocks[block_index]);
}

void apply_keyframe_data(AnimationClip::NodeTrack& track,
                         const nif::NiKeyframeData& kd,
                         float& clip_duration) {
    for (auto& k : kd.translations.keys) {
        track.translation.push_back({k.time, glm::vec3(k.value.x, k.value.y, k.value.z)});
        clip_duration = std::max(clip_duration, k.time);
    }
    for (auto& k : kd.quaternion_keys) {
        track.rotation.push_back({k.time, glm::quat(k.value.w, k.value.x, k.value.y, k.value.z)});
        clip_duration = std::max(clip_duration, k.time);
    }
    for (auto& k : kd.scales.keys) {
        track.scale.push_back({k.time, k.value});
        clip_duration = std::max(clip_duration, k.time);
    }
}

void apply_vis_data(AnimationClip::NodeTrack& track,
                    const nif::NiVisData& vd,
                    float& clip_duration) {
    for (auto& k : vd.keys) {
        track.visibility.push_back({k.time, k.visible != 0});
        clip_duration = std::max(clip_duration, k.time);
    }
}

void apply_float_data(AnimationClip::NodeTrack& track,
                      const nif::NiFloatData& fd,
                      float& clip_duration) {
    for (auto& k : fd.keys) {
        track.floats.push_back({k.time, k.value});
        clip_duration = std::max(clip_duration, k.time);
    }
}

}  // namespace

std::vector<AnimationClip> build_animations(const nif::File& f) {
    LinkResolver resolver(f);
    std::unordered_map<std::string, AnimationClip::NodeTrack> tracks_by_target;
    float clip_duration = 0.0f;

    // Each NiNode references its FIRST controller via `controller_link`; further
    // controllers chain off it through `next_controller_link`. BC v3.1 turn clips
    // attach BOTH a NiVisController (eye blinks) AND a NiKeyframeController to a
    // node as such a chain. We must WALK the chain, not just match a node's
    // direct controller_link — otherwise the chained controller's data is
    // dropped, which silently emptied db_face_capt_t (VisController head ->
    // KeyframeController tail) and left the Tactical officer un-animated.
    for (const auto& b : f.blocks) {
        const auto* node = std::get_if<nif::NiNode>(&b);
        if (!node) continue;
        std::uint32_t idx = resolver.resolve(node->av.obj.controller_link);
        // The track is created LAZILY, only when a real controller is found in
        // the chain — a node whose controller_link points at a non-controller
        // block must not fabricate an empty animation track.
        auto get_track = [&]() -> AnimationClip::NodeTrack& {
            auto& t = tracks_by_target[node->av.obj.name];
            t.target_node_name = node->av.obj.name;
            return t;
        };
        // Follow the controller chain; the iteration cap guards against a
        // malformed cyclic link in a corrupt file.
        for (int guard = 0; guard < 256 && idx < f.blocks.size(); ++guard) {
            std::uint32_t next_link = 0;
            if (const auto* kc = std::get_if<nif::NiKeyframeController>(&f.blocks[idx])) {
                if (const auto* kd =
                        data_at<nif::NiKeyframeData>(f, resolver.resolve(kc->data_link)))
                    apply_keyframe_data(get_track(), *kd, clip_duration);
                next_link = kc->next_controller_link;
            } else if (const auto* vc = std::get_if<nif::NiVisController>(&f.blocks[idx])) {
                if (const auto* vd =
                        data_at<nif::NiVisData>(f, resolver.resolve(vc->data_link)))
                    apply_vis_data(get_track(), *vd, clip_duration);
                next_link = vc->next_controller_link;
            } else if (const auto* rc = std::get_if<nif::NiRollController>(&f.blocks[idx])) {
                if (const auto* fd =
                        data_at<nif::NiFloatData>(f, resolver.resolve(rc->data_link)))
                    apply_float_data(get_track(), *fd, clip_duration);
                next_link = rc->next_controller_link;
            } else {
                break;      // unknown / non-controller block in the chain
            }
            std::uint32_t next_idx = resolver.resolve(next_link);
            if (next_idx == idx) break;             // self-loop guard
            idx = next_idx;
        }
    }

    if (tracks_by_target.empty()) return {};

    AnimationClip clip;
    clip.name = f.source.stem().string();
    clip.duration_seconds = clip_duration;
    for (auto& [_, track] : tracks_by_target) clip.tracks.push_back(std::move(track));
    return {std::move(clip)};
}

}  // namespace assets::detail
