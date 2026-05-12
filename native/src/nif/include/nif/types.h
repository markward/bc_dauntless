#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace nif {

struct Vec3 { float x, y, z; };
// NIF stores quaternions on disk in WXYZ order (W first); Reader::read_quat
// unpacks them into named fields here, so .w holds the first on-disk float.
// Composition convention: right-handed, column-vector math (v' = M*v).
struct Quat { float x, y, z, w; };
// Storage: row-major flat array (m[0]=row0col0, m[1]=row0col1, ...).
// Math: column-vector (vectors transform as v' = M*v, parent-world = parent * local).
// Rotation matrices are orthonormal; combined NiAVObject transform is
// parent * (T * R * S) with uniform scalar scale only.
struct Mat3x3 { std::array<float, 9> m; };
struct Color3 { float r, g, b; };
struct Color4 { float r, g, b, a; };

using BlockId = std::int32_t;
constexpr BlockId kNullBlockId = -1;

using StringRef = std::string;

}  // namespace nif
