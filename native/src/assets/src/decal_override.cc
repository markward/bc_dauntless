// native/src/assets/src/decal_override.cc
//
// See decal_override.h. The per-entry rules (shape lookup, degenerate
// projector, body_to_mask, premultiply) are the SAME functions apply_decals
// uses (model_build.h), so a placement previewed through an override and the
// same placement baked into a model can never disagree.
#include <assets/decal_override.h>

#include "model_build.h"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <unordered_set>

namespace fs = std::filesystem;

namespace assets {

namespace {

bool warn_once(const std::string& key) {
    static std::unordered_set<std::string> warned;
    return warned.insert(key).second;
}

std::vector<std::uint8_t> read_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw std::runtime_error("could not open " + p.string());
    return std::vector<std::uint8_t>(std::istreambuf_iterator<char>(in),
                                     std::istreambuf_iterator<char>());
}

}  // namespace

DecalOverride build_decal_override(const Model& model,
                                   const std::vector<DecalRequest>& requests,
                                   const DecalMaskResolver& resolve_mask) {
    DecalOverride out;
    out.mesh_masks.assign(model.meshes.size(), 0);
    std::vector<std::string> slot_keys;  // decal_mask_key of texture_ids[s]

    for (std::size_t r = 0; r < requests.size(); ++r) {
        const auto& req = requests[r];
        if (static_cast<int>(out.decals.size()) >= kMaxDecals) {
            if (warn_once(model.source.string() + "|override-cap")) {
                std::fprintf(stderr,
                    "set_instance_decals: more than %d decals for %s; "
                    "using the first %d, dropping %zu\n",
                    kMaxDecals, model.source.string().c_str(), kMaxDecals,
                    requests.size() - r);
            }
            break;
        }
        if (!req.shape.empty() &&
            std::none_of(model.meshes.begin(), model.meshes.end(),
                         [&](const Mesh& m) { return m.shape_name() == req.shape; })) {
            if (warn_once(model.source.string() + "|override-shape|" + req.shape)) {
                std::fprintf(stderr,
                    "set_instance_decals: no shape named '%s' in %s; "
                    "skipping decal\n",
                    req.shape.c_str(), model.source.string().c_str());
            }
            continue;
        }
        if (detail::decal_projector_is_degenerate(req.u_axis, req.v_axis, req.normal)) {
            if (warn_once(model.source.string() + "|override-degenerate|" + req.shape)) {
                std::fprintf(stderr,
                    "set_instance_decals: degenerate projector for shape "
                    "'%s' in %s; skipping decal\n",
                    req.shape.c_str(), model.source.string().c_str());
            }
            continue;
        }
        // Shared masks (spec §2.4a): a known mask reuses its slot; a new one
        // past kMaxDecalMasks is skipped BEFORE resolving, so it never loads
        // (or retires) a texture nothing will draw.
        const std::string mask_key = detail::decal_mask_key(req.mask);
        int slot = static_cast<int>(
            std::find(slot_keys.begin(), slot_keys.end(), mask_key) - slot_keys.begin());
        if (slot == static_cast<int>(slot_keys.size())) {
            if (slot >= kMaxDecalMasks) {
                if (warn_once(model.source.string() + "|override-mask-cap")) {
                    std::fprintf(stderr,
                        "set_instance_decals: more than %d distinct masks for "
                        "%s; skipping the entry using %s (and any later one "
                        "needing another new mask)\n",
                        kMaxDecalMasks, model.source.string().c_str(),
                        req.mask.string().c_str());
                }
                continue;
            }
            const std::uint32_t tex = resolve_mask ? resolve_mask(req.mask) : 0u;
            if (tex == 0) continue;  // the resolver warns about its own failures
            slot_keys.push_back(mask_key);
            out.texture_ids.push_back(tex);
        }

        ModelDecal decal;
        decal.body_to_mask =
            detail::decal_body_to_mask(req.origin, req.u_axis, req.v_axis, req.normal);
        decal.normal = glm::normalize(req.normal);
        decal.depth = req.depth;
        decal.mask_slot = slot;

        const auto bit = static_cast<std::uint16_t>(1u << out.decals.size());
        for (std::size_t m = 0; m < model.meshes.size(); ++m) {
            if (req.shape.empty() || model.meshes[m].shape_name() == req.shape)
                out.mesh_masks[m] = static_cast<std::uint16_t>(out.mesh_masks[m] | bit);
        }
        out.decals.push_back(decal);
    }
    return out;
}

DecalMaskCache::DecalMaskCache(Uploader upload) : upload_(std::move(upload)) {}

std::uint32_t DecalMaskCache::get(const fs::path& mask) {
    const std::string key = mask.string();
    std::error_code ec;
    const auto mtime = fs::last_write_time(mask, ec);
    auto it = textures_.find(key);
    if (it != textures_.end()) {
        // A vanished file (ec set) keeps serving the texture it last loaded.
        if (ec || it->second.mtime == mtime) return it->second.texture.id();
    }
    Image image;
    try {
        image = decode_image(read_bytes(mask));
    } catch (const std::exception& e) {
        if (warn_once("mask-cache|" + key)) {
            std::fprintf(stderr,
                "set_instance_decals: failed to load mask '%s' (%s); "
                "skipping decal\n", key.c_str(), e.what());
        }
        // Mid-export (Gimp writing the file): keep the previous texture.
        return it != textures_.end() ? it->second.texture.id() : 0u;
    }
    detail::premultiply_decal_mask(image);
    Texture tex = upload_ ? upload_(image, /*generate_mipmaps=*/true)
                          : upload_image(image, /*generate_mipmaps=*/true);
    const std::uint32_t id = tex.id();
    if (it != textures_.end()) {
        retired_.push_back(std::move(it->second.texture));
        // Bounded: drop the OLDEST retired texture. We are inside
        // set_instance_decals, so the GL context is current (this same call
        // just uploaded). A texture this many reloads old belongs to an
        // override that every later push has already replaced -- the only
        // caller is the SPV previewing ONE instance.
        if (retired_.size() > kMaxRetired) retired_.erase(retired_.begin());
        it->second = Entry{std::move(tex), mtime};
    } else {
        textures_.emplace(key, Entry{std::move(tex), mtime});
    }
    return id;
}

void DecalMaskCache::clear() {
    textures_.clear();
    retired_.clear();
}

}  // namespace assets
