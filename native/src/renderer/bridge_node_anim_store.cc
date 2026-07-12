#include <renderer/bridge_node_anim_store.h>

#include <renderer/node_anim.h>
#include <assets/model.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <utility>

namespace renderer {

std::string normalize_clip_key(const std::string& path) {
    std::string out(path);
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

void BridgeNodeAnimStore::play(std::uint32_t instance_index, const std::string& key,
                               assets::AnimationClip clip, double now,
                               bool loop, bool reverse) {
    const std::string k = normalize_clip_key(key);
    auto& list = clips_[instance_index];
    for (auto& a : list) {
        if (a.key == k) {                       // restart in place, never stack
            a.clip = std::move(clip);
            a.start_wall_time = now;
            a.loop = loop;
            a.reverse = reverse;
            a.settled = false;
            return;
        }
    }
    ActiveNodeClip a;
    a.clip = std::move(clip);
    a.key = k;
    a.start_wall_time = now;
    a.loop = loop;
    a.reverse = reverse;
    list.push_back(std::move(a));
}

void BridgeNodeAnimStore::stop(std::uint32_t instance_index) {
    clips_.erase(instance_index);
}

void BridgeNodeAnimStore::clear() { clips_.clear(); }

std::vector<std::uint32_t> BridgeNodeAnimStore::instances() const {
    std::vector<std::uint32_t> out;
    out.reserve(clips_.size());
    for (const auto& kv : clips_) out.push_back(kv.first);
    return out;
}

std::size_t BridgeNodeAnimStore::active_count(std::uint32_t instance_index) const {
    auto it = clips_.find(instance_index);
    return it == clips_.end() ? 0u : it->second.size();
}

std::unordered_map<int, glm::mat4> BridgeNodeAnimStore::sample(
        std::uint32_t instance_index, const assets::Model& model, double now) {
    std::unordered_map<int, glm::mat4> merged;
    auto it = clips_.find(instance_index);
    if (it == clips_.end()) return merged;

    for (auto& a : it->second) {
        const float dur = a.clip.duration_seconds;
        double elapsed = now - a.start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;

        float t;
        if (a.loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= static_cast<double>(dur)) {
            t = dur;
            a.settled = true;                   // HOLD the last frame
        } else {
            t = static_cast<float>(elapsed);
        }
        if (a.reverse) t = dur - t;

        // Merge: clips touch disjoint nodes; on overlap, insertion order wins.
        for (const auto& kv : sample_node_overrides(a.clip, model, t))
            merged[kv.first] = kv.second;
    }
    return merged;
}

}  // namespace renderer
