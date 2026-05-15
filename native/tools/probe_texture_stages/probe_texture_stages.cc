// native/tools/probe_texture_stages/probe_texture_stages.cc
//
// Dump per-shape texture-stage layout for a single NIF. Used to ground
// material/lightmap investigations (e.g. "does DBridge.NIF carry a
// lightmap in NiMultiTextureProperty stage 1?").
//
// Output per NiTriShape:
//   - name
//   - property block types referenced
//   - for NiTextureProperty: image filename
//   - for NiMultiTextureProperty: stage index → (has_image, uv_set, image filename)
//
// Usage:
//   probe_texture_stages <path-to.nif>

#include <nif/block.h>
#include <nif/file.h>

#include <cstdio>
#include <string>
#include <unordered_map>
#include <variant>

namespace {

const char* slot_name(std::size_t i) {
    switch (i) {
        case 0: return "Base";
        case 1: return "Dark";
        case 2: return "Detail";
        case 3: return "Glow";
        case 4: return "Gloss";
    }
    return "?";
}

std::string image_name(const nif::Block& b) {
    if (auto* p = std::get_if<nif::NiImage>(&b)) {
        if (p->use_external) return p->file_name;
        return "<embedded image_data_link=" + std::to_string(p->image_data_link) + ">";
    }
    return "<not-an-image>";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <path-to.nif>\n", argv[0]);
        return 2;
    }
    nif::File f = nif::load(argv[1]);
    if (!f.eof_reached) {
        std::fprintf(stderr, "parse stopped at block type: %s\n",
                     f.stopped_at_block_type.c_str());
        return 1;
    }

    // Build id->block-index map for cross-references.
    std::unordered_map<std::uint32_t, std::size_t> id_to_index;
    id_to_index.reserve(f.blocks.size());
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        id_to_index[f.block_ids[i]] = i;
    }

    auto block_at = [&](std::uint32_t id) -> const nif::Block* {
        auto it = id_to_index.find(id);
        if (it == id_to_index.end()) return nullptr;
        return &f.blocks[it->second];
    };

    // Build child_id -> parent_block_index, so we can walk inherited
    // property_links up the NiNode chain (BC v3.x sets material/texture
    // properties on the parent NiNode, not the individual NiTriShape).
    std::unordered_map<std::uint32_t, std::size_t> child_id_to_parent_index;
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        if (auto* n = std::get_if<nif::NiNode>(&f.blocks[i])) {
            for (std::uint32_t c : n->child_links) {
                child_id_to_parent_index[c] = i;
            }
        }
    }

    struct TaggedLink {
        std::uint32_t link;
        int depth;  // 0 = direct on shape, 1 = on parent NiNode, 2 = grandparent...
    };

    auto inherited_property_links_tagged =
        [&](std::size_t shape_block_index) -> std::vector<TaggedLink> {
        std::vector<TaggedLink> out;
        const auto* shape = std::get_if<nif::NiTriShape>(&f.blocks[shape_block_index]);
        if (shape) {
            for (auto l : shape->av.property_links) out.push_back({l, 0});
        }
        std::uint32_t cur_id = f.block_ids[shape_block_index];
        int depth = 1;
        while (true) {
            auto it = child_id_to_parent_index.find(cur_id);
            if (it == child_id_to_parent_index.end()) break;
            const auto* n = std::get_if<nif::NiNode>(&f.blocks[it->second]);
            if (!n) break;
            for (auto l : n->av.property_links) out.push_back({l, depth});
            cur_id = f.block_ids[it->second];
            ++depth;
        }
        return out;
    };

    int multi_count = 0, single_count = 0, no_tex_count = 0;
    int multi_direct = 0, multi_inherited = 0;
    int single_direct = 0, single_inherited = 0;
    int multi_with_dark = 0, multi_with_detail = 0, multi_with_glow = 0, multi_with_gloss = 0;

    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto& b = f.blocks[i];
        const auto* shape = std::get_if<nif::NiTriShape>(&b);
        if (!shape) continue;

        const std::string& name = shape->av.obj.name;
        auto prop_links = inherited_property_links_tagged(i);

        const nif::NiTextureProperty*      single = nullptr;
        const nif::NiMultiTextureProperty* multi  = nullptr;
        const nif::NiAlphaProperty*        alpha  = nullptr;
        const nif::NiMaterialProperty*     mat    = nullptr;
        int single_depth = -1, multi_depth = -1;

        for (const auto& tagged : prop_links) {
            auto* pb = block_at(tagged.link);
            if (!pb) continue;
            if (auto* p = std::get_if<nif::NiTextureProperty>(pb)) {
                if (!single) { single = p; single_depth = tagged.depth; }
            }
            else if (auto* p = std::get_if<nif::NiMultiTextureProperty>(pb)) {
                if (!multi) { multi = p; multi_depth = tagged.depth; }
            }
            else if (auto* p = std::get_if<nif::NiAlphaProperty>(pb))        { if (!alpha) alpha = p; }
            else if (auto* p = std::get_if<nif::NiMaterialProperty>(pb))     { if (!mat)   mat   = p; }
        }

        auto provenance_tag = [](int depth) -> std::string {
            if (depth == 0) return "[direct]";
            return "[inherited@" + std::to_string(depth) + "]";
        };

        if (multi) {
            ++multi_count;
            if (multi_depth == 0) ++multi_direct; else ++multi_inherited;
            std::printf("shape #%zu \"%s\"  (NiMultiTextureProperty %s%s%s)\n",
                        i, name.c_str(),
                        provenance_tag(multi_depth).c_str(),
                        alpha ? " +Alpha" : "",
                        mat ? " +Material" : "");
            for (std::size_t s = 0; s < 5; ++s) {
                const auto& el = multi->elements[s];
                if (!el.has_image) {
                    std::printf("    stage %zu (%-6s): <empty>\n", s, slot_name(s));
                    continue;
                }
                const auto* img = block_at(el.image_link);
                std::string imgs = img ? image_name(*img) : "<unresolved>";
                std::printf("    stage %zu (%-6s): uv_set=%u  image=%s\n",
                            s, slot_name(s), el.uv_set, imgs.c_str());
                if (s == 1) ++multi_with_dark;
                if (s == 2) ++multi_with_detail;
                if (s == 3) ++multi_with_glow;
                if (s == 4) ++multi_with_gloss;
            }
        } else if (single) {
            ++single_count;
            if (single_depth == 0) ++single_direct; else ++single_inherited;
            const auto* img = block_at(single->image_link);
            std::string imgs = img ? image_name(*img) : "<unresolved>";
            std::printf("shape #%zu \"%s\"  (NiTextureProperty %s%s%s): image=%s\n",
                        i, name.c_str(),
                        provenance_tag(single_depth).c_str(),
                        alpha ? " +Alpha" : "",
                        mat ? " +Material" : "",
                        imgs.c_str());
        } else {
            ++no_tex_count;
            std::printf("shape #%zu \"%s\"  (no texture property%s%s)\n",
                        i, name.c_str(),
                        alpha ? " +Alpha" : "",
                        mat ? " +Material" : "");
        }
    }

    std::printf("\n--- summary ---\n");
    std::printf("shapes with NiMultiTextureProperty: %d (direct=%d, inherited=%d)\n",
                multi_count, multi_direct, multi_inherited);
    std::printf("  of which populate stage Dark   : %d\n", multi_with_dark);
    std::printf("  of which populate stage Detail : %d\n", multi_with_detail);
    std::printf("  of which populate stage Glow   : %d\n", multi_with_glow);
    std::printf("  of which populate stage Gloss  : %d\n", multi_with_gloss);
    std::printf("shapes with NiTextureProperty   : %d (direct=%d, inherited=%d)\n",
                single_count, single_direct, single_inherited);
    std::printf("shapes with no texture property : %d\n", no_tex_count);
    return 0;
}
