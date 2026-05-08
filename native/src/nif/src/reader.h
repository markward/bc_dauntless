// native/src/nif/src/reader.h
#pragma once

#include <nif/error.h>
#include <nif/types.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>

namespace nif {

class Reader {
public:
    Reader(const unsigned char* data, std::size_t size, std::filesystem::path source);

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

    std::string read_string_uint32();
    std::string read_string_uint8();
    /// Read until \n, return content without the newline; consumes the \n.
    /// v3.1 NIFs use multi-line text headers.
    std::string read_line();
    void read_bytes(unsigned char* out, std::size_t n);

    /// Look at the next byte without advancing the cursor.
    std::uint8_t peek_uint8();

    std::size_t offset() const { return offset_; }
    std::size_t bytes_remaining() const { return size_ - offset_; }
    const std::filesystem::path& source() const { return source_; }

    void require(std::size_t n);

private:
    const unsigned char* data_;
    std::size_t size_;
    std::size_t offset_ = 0;
    std::filesystem::path source_;
};

}  // namespace nif
