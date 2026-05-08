// native/src/nif/include/nif/error.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>

namespace nif {

class ParseError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
    std::filesystem::path file;
    std::optional<std::size_t> byte_offset;
    std::optional<std::string> block_type;
};

class UnknownBlockType : public ParseError { using ParseError::ParseError; };
class TruncatedBlock   : public ParseError { using ParseError::ParseError; };
class VersionMismatch  : public ParseError { using ParseError::ParseError; };

}  // namespace nif
