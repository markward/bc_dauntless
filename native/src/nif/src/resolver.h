// native/src/nif/src/resolver.h
//
// After block parsing, cross-block references in the variant payloads still
// hold raw BlockId integers. The resolver pass walks each block and
// converts those references into BlockHandle pointers into the file's
// blocks vector. Each block parser is responsible for declaring its
// reference fields here as it lands; today the variant has only
// std::monostate so the resolver has nothing to do.
#pragma once

#include <nif/file.h>
#include <nif/types.h>

namespace nif {

/// Look up a block by raw index. Null sentinel (-1) yields a falsy handle.
/// Out-of-range indices throw nif::ParseError.
BlockHandle resolve_handle(File& f, BlockId id);

/// Walk every block and replace raw indices in reference fields with
/// BlockHandles. Called once at the end of nif::load.
void resolve_references(File& f);

}  // namespace nif
