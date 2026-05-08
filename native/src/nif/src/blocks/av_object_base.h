// native/src/nif/src/blocks/av_object_base.h
//
// Shared parsing helper for the NiAVObject base fields, present on every
// scene-graph block (NiNode, NiTriShape, NiBone, ...). Field layout per
// nifxml schema filtered for v3.1.
#pragma once

#include "../reader.h"

#include <nif/block.h>

namespace nif {

/// Reads the NiObjectNET + NiAVObject fields in v3.1 order. Throws if the
/// has_bounding_volume flag is 1 (bounding-volume body parsing is deferred
/// until a sample file requires it).
AvObjectBase parse_av_object_base(Reader& r, const char* block_type);

}  // namespace nif
