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
/// the baked list; `texture_ids` is the override's counterpart of
/// Model::decal_masks -- one GL texture id per DISTINCT mask (at most
/// kMaxDecalMasks), indexed by ModelDecal::mask_slot, owned by whoever
/// resolved the masks (the host's DecalMaskCache). `mesh_masks[m]` is
/// Model::meshes[m]'s enable mask for THIS list (bit i => decals[i] may paint
/// mesh m), the override's counterpart of Mesh::decal_mask(). At most
/// kMaxDecals entries.
struct DecalOverride {
    std::vector<ModelDecal>    decals;
    std::vector<std::uint32_t> texture_ids;
    std::vector<std::uint16_t> mesh_masks;
};

/// Resolve a mask path to a GL texture id; 0 = could not load.
using DecalMaskResolver = std::function<std::uint32_t(const std::filesystem::path&)>;

/// Build an override from `requests` against `model`'s meshes, exactly as
/// build_model's apply_decals would: a named `shape` enables the decal only
/// on meshes whose Mesh::shape_name() matches; an empty shape enables every
/// mesh. Masks dedupe exactly as there (detail::decal_mask_key): each
/// distinct mask is resolved ONCE and shares one slot; an entry that would
/// need a fifth distinct mask is skipped WITHOUT resolving it (warned once).
/// An unknown shape, a degenerate projector or a mask the resolver returns 0
/// for skips THAT entry (warned once) and takes no slot; survivors are
/// packed, so bit i always means decals[i]. Entries past kMaxDecals are
/// dropped (warned once). Never throws for bad input.
DecalOverride build_decal_override(const Model& model,
                                   const std::vector<DecalRequest>& requests,
                                   const DecalMaskResolver& resolve_mask);

/// Once-per-path hull-decal mask textures: decode_image, RGB premultiplied by
/// alpha exactly as apply_decals does, uploaded mipmapped. Owns the GL
/// textures -- clear() (or destruction) must run while the creating GL
/// context is current. A load failure returns 0, warns once per path and is
/// NOT cached, so a mask authored after the first attempt loads on the next.
///
/// A cached path whose file mtime has changed since it loaded is decoded and
/// uploaded again (Ruling K: a mask re-exported from Gimp while the SPV is
/// open shows on the next set_instance_decals). The superseded texture is
/// RETIRED, not freed, until clear(): another instance's override may still
/// hold its id, and freeing it would leave that override naming a dead GL
/// texture. At most kMaxRetired are kept (oldest freed first): a texture that
/// many reloads stale is no longer named by any override the SPV -- the only
/// caller, previewing one instance -- still has installed. Shared masks keep
/// this bound safe: build_decal_override resolves at most kMaxDecalMasks (4)
/// distinct paths per push however many of its (up to 16) placements share
/// them, so one push retires at most 4 textures -- the ones the override it
/// is about to replace still names -- and 8 holds two pushes' worth.
class DecalMaskCache {
public:
    using Uploader = std::function<Texture(const Image&, bool)>;
    /// Empty uploader => upload_image.
    explicit DecalMaskCache(Uploader upload = {});

    /// The mask's GL texture id, loading it on first use (or when its file
    /// mtime changed); 0 on failure.
    std::uint32_t get(const std::filesystem::path& mask);
    /// Retired textures kept alive at most (see the class comment).
    static constexpr std::size_t kMaxRetired = 8;
    static_assert(kMaxRetired >= static_cast<std::size_t>(kMaxDecalMasks),
                  "one push may retire every mask slot the previous override names");

    /// Live entries, one per path (retired textures are not counted).
    std::size_t size() const noexcept { return textures_.size(); }
    std::size_t retired_count() const noexcept { return retired_.size(); }
    void clear();

private:
    struct Entry {
        Texture texture;
        std::filesystem::file_time_type mtime;
    };
    Uploader upload_;
    std::unordered_map<std::string, Entry> textures_;
    std::vector<Texture> retired_;
};

}  // namespace assets
