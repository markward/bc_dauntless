// native/src/nif/src/reader.cc
#include "reader.h"

#include <algorithm>
#include <bit>
#include <cstring>

// NIF format is little-endian. The integer/float readers below memcpy bytes
// into native types; on a big-endian host they would silently produce wrong
// values. All current targets (x86, ARM macOS/Linux) are little-endian; if
// that ever changes, byteswap the appropriate reads instead of just
// firing this assert.
static_assert(std::endian::native == std::endian::little,
              "nif::Reader requires a little-endian host");

namespace nif {

Reader::Reader(const unsigned char* data, std::size_t size, std::filesystem::path source)
    : data_(data), size_(size), source_(std::move(source)) {}

void Reader::require(std::size_t n) {
    if (bytes_remaining() < n) {
        TruncatedBlock e("reader: truncated, " +
                         std::to_string(bytes_remaining()) + " of " +
                         std::to_string(n) + " required bytes available");
        e.file = source_;
        e.byte_offset = offset_;
        throw e;
    }
}

std::uint8_t Reader::read_uint8() { require(1); return data_[offset_++]; }

std::uint8_t Reader::peek_uint8() { require(1); return data_[offset_]; }

std::size_t Reader::peek_bytes(unsigned char* out, std::size_t n) {
    auto take = std::min(n, bytes_remaining());
    if (take > 0) std::memcpy(out, data_ + offset_, take);
    return take;
}

std::uint16_t Reader::read_uint16() {
    require(2); std::uint16_t v; std::memcpy(&v, data_ + offset_, 2); offset_ += 2; return v;
}

std::uint32_t Reader::read_uint32() {
    require(4); std::uint32_t v; std::memcpy(&v, data_ + offset_, 4); offset_ += 4; return v;
}

std::int32_t Reader::read_int32() { return static_cast<std::int32_t>(read_uint32()); }

float Reader::read_float() {
    require(4); float v; std::memcpy(&v, data_ + offset_, 4); offset_ += 4; return v;
}

Vec3 Reader::read_vec3() { return {read_float(), read_float(), read_float()}; }
Vec4 Reader::read_vec4() { return {read_float(), read_float(), read_float(), read_float()}; }
Quat Reader::read_quat() { return {read_float(), read_float(), read_float(), read_float()}; }

Mat3x3 Reader::read_mat3x3() {
    Mat3x3 m;
    for (auto& f : m.m) f = read_float();
    return m;
}

Color3 Reader::read_color3() { return {read_float(), read_float(), read_float()}; }
Color4 Reader::read_color4() { return {read_float(), read_float(), read_float(), read_float()}; }

std::string Reader::read_string_uint32(std::size_t max_len) {
    auto len = read_uint32();
    if (len > max_len) {
        ParseError e("string length " + std::to_string(len) +
                     " exceeds cap " + std::to_string(max_len));
        e.file = source_;
        e.byte_offset = offset_;
        throw e;
    }
    require(len);
    std::string s(reinterpret_cast<const char*>(data_ + offset_), len);
    offset_ += len;
    return s;
}

std::string Reader::read_string_uint8() {
    auto len = read_uint8();
    require(len);
    std::string s(reinterpret_cast<const char*>(data_ + offset_), len);
    offset_ += len;
    return s;
}

std::string Reader::read_string_fixed(std::size_t n) {
    require(n);
    std::string s(reinterpret_cast<const char*>(data_ + offset_), n);
    offset_ += n;
    return s;
}

std::string Reader::read_line() {
    std::string s;
    while (true) {
        auto b = read_uint8();
        if (b == '\n') break;
        s.push_back(static_cast<char>(b));
    }
    return s;
}

void Reader::read_bytes(unsigned char* out, std::size_t n) {
    require(n);
    std::memcpy(out, data_ + offset_, n);
    offset_ += n;
}

}  // namespace nif
