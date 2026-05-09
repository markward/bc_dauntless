// native/src/nif/src/header.h
// v3.1 file header parser. The v3.1 format puts vendor text at the start of
// the file (multiple \n-terminated lines including a magic line that names
// the version), then a binary block stream. There is no separate binary
// version field — version is parsed from the magic line text.
#pragma once

#include <nif/version.h>

#include <cstdint>
#include <string>
#include <vector>

namespace nif {

class Reader;

struct HeaderInfo {
    Version version;
    std::vector<std::string> lines;  // verbatim text lines (without trailing \n)
};

HeaderInfo parse_header(Reader& r);

// Parse "Version X.Y" or "Version X.Y.Z.W" from a magic-line string into the
// packed-byte representation. e.g. "Version 3.1" -> 0x03010000.
// Throws nif::VersionMismatch if the input is malformed.
std::uint32_t parse_version_from_magic_line(const std::string& magic_line);

}  // namespace nif
