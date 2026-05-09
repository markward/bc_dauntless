// native/src/nif/src/reader.h
#pragma once

#include <nif/error.h>
#include <nif/types.h>
#include <nif/version.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>

namespace nif {

class Reader {
public:
    Reader(const unsigned char* data, std::size_t size, std::filesystem::path source);

    /// File-level version, set by the header parser before block parsers run.
    /// Used by per-block parsers to gate version-conditional fields.
    void set_version(Version v) { version_ = v; }
    Version version() const { return version_; }

    std::uint8_t  read_uint8();
    std::uint16_t read_uint16();
    std::uint32_t read_uint32();
    std::int32_t  read_int32();
    float         read_float();
    Vec3          read_vec3();
    Vec4          read_vec4();
    Quat          read_quat();
    Mat3x3        read_mat3x3();
    Color3        read_color3();
    Color4        read_color4();

    /// Read a length-prefixed string. The uint32 length is sanity-capped to
    /// `max_len` (default 64KB) — a malformed or adversarial file with a
    /// huge length prefix would otherwise allocate gigabytes. Throws
    /// nif::ParseError if length exceeds the cap.
    std::string read_string_uint32(std::size_t max_len = 65536);
    std::string read_string_uint8();
    /// Read exactly `n` bytes as a string. Used for v3.x type-name reads
    /// where the length was already consumed.
    std::string read_string_fixed(std::size_t n);
    /// Read until \n, return content without the newline; consumes the \n.
    /// v3.1 NIFs use multi-line text headers.
    std::string read_line();
    void read_bytes(unsigned char* out, std::size_t n);

    /// Look at the next byte without advancing the cursor.
    std::uint8_t peek_uint8();
    /// Peek up to `n` bytes without advancing. Returns the number of bytes
    /// actually written to `out` (capped at bytes_remaining()).
    std::size_t peek_bytes(unsigned char* out, std::size_t n);

    std::size_t offset() const { return offset_; }
    std::size_t bytes_remaining() const { return size_ - offset_; }
    const std::filesystem::path& source() const { return source_; }

    void require(std::size_t n);

private:
    const unsigned char* data_;
    std::size_t size_;
    std::size_t offset_ = 0;
    std::filesystem::path source_;
    Version version_{};
};

}  // namespace nif
