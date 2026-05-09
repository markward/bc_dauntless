#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace nif {

struct Vec3 { float x, y, z; };
struct Vec4 { float x, y, z, w; };
struct Quat { float x, y, z, w; };
struct Mat3x3 { std::array<float, 9> m; };  // row-major
struct Color3 { float r, g, b; };
struct Color4 { float r, g, b, a; };

using BlockId = std::int32_t;
constexpr BlockId kNullBlockId = -1;

using StringRef = std::string;

}  // namespace nif
