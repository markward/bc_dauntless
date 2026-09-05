#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

namespace dauntless {

// Thrown when a handle's generation no longer matches its slot.
class StaleHandle : public std::runtime_error {
public:
    StaleHandle(std::uint32_t index, std::uint32_t generation);
};

// Contiguous, index-addressed storage for every object's world transform.
//
// Position and rotation live here rather than on the Python object so that
// the renderer and the motion integrator can read them without crossing the
// language boundary. Rotation is row-major nine doubles, matching TGMatrix3's
// mIJ = row I, column J. Column-vector convention: column 1 is forward.
//
// Storage is double, not float: Python's `float` IS a C double, and this store
// is the sole owner of every object's transform (Task 4). Truncating to float
// on every write would make the native backend diverge from the pure-Python
// one over an integration run, breaking the "byte-identical from the SDK's
// point of view" goal. The renderer downconverts to float at the GL boundary
// (Task 6), not here.
//
// Slots are generation-counted: a handle to a freed slot fails loudly rather
// than silently reading whatever object recycled its index. Indices stay
// valid across growth, which is why callers receive an index and never a
// pointer — the backing vector reallocates.
//
// NOT internally synchronised. The threaded integrator (spec phase 5) works
// on disjoint slots inside a window where the GIL is released and no other
// code runs, so no locking is required or wanted here.
class TransformStore {
public:
    struct Transform {
        double pos[3];
        double rot[9];
    };

    // Returns (index, generation). New slots are identity at the origin.
    std::pair<std::uint32_t, std::uint32_t> alloc();
    void free(std::uint32_t index, std::uint32_t generation);

    bool valid(std::uint32_t index, std::uint32_t generation) const;

    std::array<double, 3> position(std::uint32_t index,
                                   std::uint32_t generation) const;
    void set_position(std::uint32_t index, std::uint32_t generation,
                      double x, double y, double z);

    std::array<double, 9> rotation(std::uint32_t index,
                                   std::uint32_t generation) const;
    void set_rotation(std::uint32_t index, std::uint32_t generation,
                      const std::array<double, 9>& r);

    std::array<double, 3> rotation_col(std::uint32_t index,
                                       std::uint32_t generation,
                                       int col) const;

    // Bulk read for per-frame sweeps: one boundary crossing instead of N.
    std::vector<std::array<double, 3>> positions(
        const std::vector<std::pair<std::uint32_t, std::uint32_t>>& handles) const;

    std::uint32_t live_count() const { return live_; }
    std::uint32_t capacity() const {
        return static_cast<std::uint32_t>(generations_.size());
    }

    // Unchecked access for the render and integrate paths, which have already
    // validated the handle. Callers must not retain the reference across an
    // alloc().
    const Transform& at(std::uint32_t index) const { return slots_[index]; }
    Transform& at(std::uint32_t index) { return slots_[index]; }

private:
    void check(std::uint32_t index, std::uint32_t generation) const;

    std::vector<Transform> slots_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint32_t> free_;
    std::uint32_t live_ = 0;
};

// The process-wide store.
TransformStore& transform_store();

}  // namespace dauntless
