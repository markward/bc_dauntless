// native/src/assets/include/assets/decal_override.h
//
// Per-instance hull-decal override (spec 2026-09-28-spv-decal-editing-
// design.md §2.5): the Ship Property Viewer previews decal edits on ONE
// instance without rebuilding its model. The override list REPLACES the
// model's baked Model::decals for that instance's draws.
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include <assets/model.h>
#include <assets/texture.h>

namespace assets {

/// A replacement for Model::decals on one instance. Same ModelDecal shape as
/// the baked list, but `texture_index` indexes `texture_ids` (GL texture ids
/// owned by whoever resolved the masks -- the host's DecalMaskCache), not
/// Model::textures. `mesh_masks[m]` is Model::meshes[m]'s enable mask for
/// THIS list (bit i => decals[i] may paint mesh m), the override's
/// counterpart of Mesh::decal_mask(). At most kMaxDecals entries.
struct DecalOverride {
    std::vector<ModelDecal>    decals;
    std::vector<std::uint32_t> texture_ids;
    std::vector<std::uint8_t>  mesh_masks;
};

/// Resolve a mask path to a GL texture id; 0 = could not load.
using DecalMaskResolver = std::function<std::uint32_t(const std::filesystem::path&)>;

/// Build an override from `requests` against `model`'s meshes, exactly as
/// build_model's apply_decals would: a named `shape` enables the decal only
/// on meshes whose Mesh::shape_name() matches; an empty shape enables every
/// mesh. An unknown shape, a degenerate projector or a mask the resolver
/// returns 0 for skips THAT entry (warned once); survivors are packed, so bit
/// i always means decals[i]. Entries past kMaxDecals are dropped (warned
/// once). Never throws for bad input.
DecalOverride build_decal_override(const Model& model,
                                   const std::vector<DecalRequest>& requests,
                                   const DecalMaskResolver& resolve_mask);

/// Once-per-path hull-decal mask textures: decode_image, RGB premultiplied by
/// alpha exactly as apply_decals does, uploaded mipmapped. Owns the GL
/// textures -- clear() (or destruction) must run while the creating GL
/// context is current. A load failure returns 0, warns once per path and is
/// NOT cached, so a mask authored after the first attempt loads on the next.
class DecalMaskCache {
public:
    using Uploader = std::function<Texture(const Image&, bool)>;
    /// Empty uploader => upload_image.
    explicit DecalMaskCache(Uploader upload = {});

    /// The mask's GL texture id, loading it on first use; 0 on failure.
    std::uint32_t get(const std::filesystem::path& mask);
    std::size_t size() const noexcept { return textures_.size(); }
    void clear();

private:
    Uploader upload_;
    std::unordered_map<std::string, Texture> textures_;
};

}  // namespace assets
