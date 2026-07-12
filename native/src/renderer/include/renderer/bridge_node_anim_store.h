#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>
#include <assets/animation.h>

namespace assets { struct Model; }

namespace renderer {

/// One active non-skinned node clip on an instance: a lift door, or a chair turn.
struct ActiveNodeClip {
    assets::AnimationClip clip;
    std::string key;                 ///< identity: lower-cased clip path
    double start_wall_time = 0.0;
    bool   loop    = false;
    bool   reverse = false;
};

/// The bridge's active node animations.
///
/// BC plays MANY named animations on a set's anim node at once — lift doors and
/// chair turns both animate the bridge's node hierarchy — and the SDK never
/// arbitrates between them (there is no busy-check in any of the 1228 SDK files).
/// So an instance holds a SET of active clips whose sampled node overrides are
/// MERGED. They touch disjoint nodes ("door 04a"/"door 04b" vs "console seat NN"),
/// so the merge is unambiguous; on an overlap, insertion order decides.
///
/// Identity is the lower-cased clip PATH, not the animation name: BC registers one
/// door NIF under two names ("doorl1" from GalaxyBridge.PreloadAnimations,
/// "DB_Door_L1" from LoadBridge.PreloadCommonAnimations) and E1M1 fires BOTH for
/// the same door (the camera walk-on sequence and Picard's move builder). Keying by
/// path collapses the aliases, so the second play RESTARTS the door instead of
/// stacking a rival copy that fights over the same nodes.
///
/// Every clip HOLDS its last frame once settled — one uniform rule, matching BC: a
/// turned chair stays turned (BC ships a dedicated reverse NIF to bring it back),
/// and a door clip ends back at rest anyway, so holding it is invisible.
class BridgeNodeAnimStore {
public:
    /// Start the clip under `key` on `instance_index`, or RESTART it in place if
    /// that key is already active. Never stacks a duplicate.
    void play(std::uint32_t instance_index, const std::string& key,
              assets::AnimationClip clip, double now, bool loop, bool reverse);

    /// Drop every clip on one instance (mission reset / bridge teardown).
    void stop(std::uint32_t instance_index);

    /// Drop everything (shutdown).
    void clear();

    bool empty() const { return clips_.empty(); }
    std::vector<std::uint32_t> instances() const;
    std::size_t active_count(std::uint32_t instance_index) const;

    /// Sample every active clip on `instance_index` at wall time `now` and merge
    /// the results into one node_index -> local_transform override map.
    std::unordered_map<int, glm::mat4> sample(std::uint32_t instance_index,
                                              const assets::Model& model, double now) const;

private:
    std::unordered_map<std::uint32_t, std::vector<ActiveNodeClip>> clips_;
};

/// Lower-case a clip path so two case-different registrations of the same NIF
/// resolve to one identity.
std::string normalize_clip_key(const std::string& path);

}  // namespace renderer
