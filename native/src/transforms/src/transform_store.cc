#include "dauntless/transform_store.h"

#include <string>

namespace dauntless {

namespace {
constexpr float kIdentity[9] = {1.0f, 0.0f, 0.0f,
                                0.0f, 1.0f, 0.0f,
                                0.0f, 0.0f, 1.0f};
}  // namespace

StaleHandle::StaleHandle(std::uint32_t index, std::uint32_t generation)
    : std::runtime_error("transform handle (" + std::to_string(index) + ", " +
                         std::to_string(generation) + ") is stale") {}

std::pair<std::uint32_t, std::uint32_t> TransformStore::alloc() {
    std::uint32_t index;
    if (!free_.empty()) {
        index = free_.back();
        free_.pop_back();
        ++generations_[index];
    } else {
        index = static_cast<std::uint32_t>(generations_.size());
        generations_.push_back(1);
        slots_.emplace_back();
    }
    Transform& t = slots_[index];
    t.pos[0] = t.pos[1] = t.pos[2] = 0.0f;
    for (int i = 0; i < 9; ++i) t.rot[i] = kIdentity[i];
    ++live_;
    return {index, generations_[index]};
}

void TransformStore::free(std::uint32_t index, std::uint32_t generation) {
    check(index, generation);
    // Bump on free as well as on reuse, so a handle to a freed-but-not-yet
    // reused slot is stale immediately.
    ++generations_[index];
    free_.push_back(index);
    --live_;
}

bool TransformStore::valid(std::uint32_t index,
                           std::uint32_t generation) const {
    return index < generations_.size() && generations_[index] == generation;
}

void TransformStore::check(std::uint32_t index,
                           std::uint32_t generation) const {
    if (!valid(index, generation)) throw StaleHandle(index, generation);
}

std::array<float, 3> TransformStore::position(
        std::uint32_t index, std::uint32_t generation) const {
    check(index, generation);
    const Transform& t = slots_[index];
    return {t.pos[0], t.pos[1], t.pos[2]};
}

void TransformStore::set_position(std::uint32_t index, std::uint32_t generation,
                                  float x, float y, float z) {
    check(index, generation);
    Transform& t = slots_[index];
    t.pos[0] = x;
    t.pos[1] = y;
    t.pos[2] = z;
}

std::array<float, 9> TransformStore::rotation(
        std::uint32_t index, std::uint32_t generation) const {
    check(index, generation);
    const Transform& t = slots_[index];
    std::array<float, 9> out{};
    for (int i = 0; i < 9; ++i) out[i] = t.rot[i];
    return out;
}

void TransformStore::set_rotation(std::uint32_t index, std::uint32_t generation,
                                  const std::array<float, 9>& r) {
    check(index, generation);
    Transform& t = slots_[index];
    for (int i = 0; i < 9; ++i) t.rot[i] = r[i];
}

std::array<float, 3> TransformStore::rotation_col(
        std::uint32_t index, std::uint32_t generation, int col) const {
    check(index, generation);
    if (col < 0 || col > 2) throw std::out_of_range("rotation column");
    const Transform& t = slots_[index];
    return {t.rot[col], t.rot[3 + col], t.rot[6 + col]};
}

TransformStore& transform_store() {
    static TransformStore store;
    return store;
}

}  // namespace dauntless
