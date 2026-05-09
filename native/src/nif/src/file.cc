// native/src/nif/src/file.cc
#include <nif/file.h>
#include <nif/error.h>

#include "dispatch.h"
#include "header.h"
#include "reader.h"
#include "resolver.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <vector>

namespace nif {

namespace {

std::vector<unsigned char> slurp(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) {
        ParseError e("could not open file");
        e.file = path;
        throw e;
    }
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0);
    std::vector<unsigned char> bytes(size);
    if (size > 0) {
        in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    }
    return bytes;
}

// v3.x block-stream walker. Format derived from NifSkope's pre-v3.3.0.13
// reader (nifmodel.cpp:1944+):
//
//   loop:
//     uint32 len
//     <len> ASCII bytes -> type_name
//     if type_name == "End Of File": stop, set eof_reached.
//     if type_name == "Top Level Object":
//       uint32 len; <len> ASCII bytes -> type_name (the actual type)
//     uint32 p (block link ID, stored in File::block_ids)
//     dispatch(type_name) consumes the body bytes.
//
// Length sanity: NifSkope uses 80 as an upper bound for a plausible type
// name; we adopt the same bound to detect corruption / format mismatch.
constexpr std::uint32_t kMaxTypeNameLen = 80;

// Walk blocks. Returns true when "End Of File" was reached. Returns false
// (without throwing) if an unimplemented block type was encountered — the
// file is then partially-parsed, which is the expected state during early
// phases when only some parsers are registered.
bool walk_blocks(File& f, Reader& r) {
    // NIF_TRACE is process-wide and inspected once per load to avoid the
    // per-block getenv cost (env-block walks aren't free).
    static const bool kTrace = std::getenv("NIF_TRACE") != nullptr;
    auto& dispatch = Dispatch::instance();
    while (true) {
        if (r.bytes_remaining() < 4) {
            TruncatedBlock e("expected block-type length, file truncated");
            e.file = r.source();
            e.byte_offset = r.offset();
            throw e;
        }
        auto len = r.read_uint32();
        if (len > kMaxTypeNameLen) {
            VersionMismatch e("block-type length " + std::to_string(len) +
                              " exceeds plausible bound — file may be corrupt or "
                              "not a v3.x NIF");
            e.file = r.source();
            e.byte_offset = r.offset();
            throw e;
        }
        auto type_name = r.read_string_fixed(len);

        if (type_name == "End Of File") {
            return true;
        }
        if (type_name == "Top Level Object") {
            // Re-read the actual block type after the label.
            auto inner_len = r.read_uint32();
            if (inner_len > kMaxTypeNameLen) {
                VersionMismatch e("inner type length after Top Level Object too large: " +
                                  std::to_string(inner_len));
                e.file = r.source();
                e.byte_offset = r.offset();
                throw e;
            }
            type_name = r.read_string_fixed(inner_len);
        }

        auto link_id = r.read_uint32();

        if (!dispatch.has(type_name)) {
            if (kTrace) {
                std::fprintf(stderr,
                             "[nif] STOP: no parser for block %zu type=%s\n",
                             f.blocks.size(), type_name.c_str());
            }
            f.stopped_at_block_type = type_name;
            return false;
        }

        if (kTrace) {
            std::fprintf(stderr,
                         "[nif] block %zu @ 0x%zx type=%s body_starts_at=0x%zx\n",
                         f.blocks.size(), r.offset() - 4 - type_name.size() - 4,
                         type_name.c_str(), r.offset());
        }
        // Parser exceptions propagate. During incremental development we
        // caught ParseError to keep nif::load usable across many files;
        // now that the corpus is fully covered, parser bugs should fail
        // loud so tests catch them.
        auto block = dispatch.get(type_name)(r);
        if (kTrace) {
            std::fprintf(stderr, "[nif]   body_ended_at=0x%zx\n", r.offset());
        }
        f.block_ids.push_back(link_id);
        f.blocks.push_back(std::move(block));
    }
}

}  // namespace

File load(const std::filesystem::path& path) {
    auto bytes = slurp(path);
    Reader r(bytes.data(), bytes.size(), path);

    File f;
    f.source = path;

    auto h = parse_header(r);
    f.version = h.version;
    f.header_lines = h.lines;
    r.set_version(h.version);  // make version available to per-block parsers

    f.eof_reached = walk_blocks(f, r);

    resolve_references(f);
    if (!f.blocks.empty()) {
        f.root = BlockHandle{ &f.blocks.front() };
    }
    return f;
}

}  // namespace nif
