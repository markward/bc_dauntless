// native/src/nif/src/header.cc
#include "header.h"
#include "reader.h"

#include <nif/error.h>

#include <cstdint>

namespace nif {

namespace {
bool is_printable_text(unsigned char c) {
    return c == '\t' || (c >= 0x20 && c < 0x7F);
}
}  // namespace

std::uint32_t parse_version_from_magic_line(const std::string& magic_line) {
    auto pos = magic_line.find("Version ");
    if (pos == std::string::npos) {
        throw VersionMismatch("magic line does not contain 'Version ': " + magic_line);
    }
    pos += 8;  // length of "Version "

    std::uint32_t bytes[4] = {0, 0, 0, 0};
    int component = 0;
    std::uint32_t current = 0;
    bool any_digit = false;
    for (; pos < magic_line.size() && component < 4; ++pos) {
        char c = magic_line[pos];
        if (c >= '0' && c <= '9') {
            current = current * 10 + static_cast<std::uint32_t>(c - '0');
            any_digit = true;
        } else if (c == '.') {
            if (!any_digit) {
                throw VersionMismatch("malformed version string: " + magic_line);
            }
            bytes[component++] = current;
            current = 0;
            any_digit = false;
        } else {
            break;  // end of version (whitespace, punctuation, EOL)
        }
    }
    if (any_digit && component < 4) {
        bytes[component++] = current;
    }
    if (component < 2) {
        throw VersionMismatch("version must have at least major.minor: " + magic_line);
    }
    return (bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
}

HeaderInfo parse_header(Reader& r) {
    HeaderInfo h;

    // Consume \n-terminated text lines while the next byte looks like
    // printable ASCII or whitespace. Stop when we hit binary data.
    while (r.bytes_remaining() > 0) {
        auto next = r.peek_uint8();
        if (!is_printable_text(next) && next != '\n') break;
        h.lines.push_back(r.read_line());
    }

    if (h.lines.empty()) {
        VersionMismatch e("file does not start with text header");
        e.file = r.source();
        throw e;
    }

    h.version.value = parse_version_from_magic_line(h.lines.front());
    return h;
}

}  // namespace nif
