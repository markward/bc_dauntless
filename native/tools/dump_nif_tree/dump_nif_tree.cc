// native/tools/dump_nif_tree/dump_nif_tree.cc
//
// Load a single NIF and print its NiNode hierarchy with per-node
// NiTriShape leaf counts. Used to verify how EBridge.nif partitions
// geometry between the top-level groups (Gamma, Dim Maps, LCARs, etc.).
//
// Usage:
//   dump_nif_tree <path/to/file.nif>
#include <nif/file.h>
#include <nif/block.h>

#include <cstdio>
#include <exception>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace fs = std::filesystem;

namespace {

// BC NIFs store cross-block "links" as raw 8-digit pointer IDs (the
// original engine's in-memory pointers), not as block array indices.
// `f.block_ids[i]` is the link ID for `f.blocks[i]`; invert that.
std::unordered_map<std::uint32_t, std::size_t> build_link_map(const nif::File& f) {
    std::unordered_map<std::uint32_t, std::size_t> m;
    m.reserve(f.block_ids.size());
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) m[f.block_ids[i]] = i;
    return m;
}

const std::string& block_name(const nif::Block& b) {
    static const std::string EMPTY;
    if (auto* n = std::get_if<nif::NiNode>(&b))     return n->av.obj.name;
    if (auto* s = std::get_if<nif::NiTriShape>(&b)) return s->av.obj.name;
    return EMPTY;
}

// Returns -1 if the block is not a NiNode.
int link_count_if_node(const nif::Block& b) {
    if (auto* n = std::get_if<nif::NiNode>(&b)) {
        return static_cast<int>(n->child_links.size());
    }
    return -1;
}

std::size_t count_shapes(const nif::File& f,
                         const std::unordered_map<std::uint32_t, std::size_t>& links,
                         std::size_t root, std::vector<bool>& seen) {
    if (root >= f.blocks.size() || seen[root]) return 0;
    seen[root] = true;
    if (std::holds_alternative<nif::NiTriShape>(f.blocks[root])) return 1;
    auto* n = std::get_if<nif::NiNode>(&f.blocks[root]);
    if (!n) return 0;
    std::size_t total = 0;
    for (auto link : n->child_links) {
        auto it = links.find(link);
        if (it != links.end()) total += count_shapes(f, links, it->second, seen);
    }
    return total;
}

void print_node(const nif::File& f,
                const std::unordered_map<std::uint32_t, std::size_t>& links,
                std::size_t idx, int depth,
                std::vector<bool>& visited) {
    if (idx >= f.blocks.size()) return;
    if (visited[idx]) {
        std::printf("%*s[cycle to block %zu]\n", depth * 2, "", idx);
        return;
    }
    visited[idx] = true;

    const auto& blk = f.blocks[idx];
    const auto& name = block_name(blk);
    const char* kind = std::holds_alternative<nif::NiNode>(blk) ? "NiNode"
                     : std::holds_alternative<nif::NiTriShape>(blk) ? "NiTriShape"
                     : "?";

    if (std::holds_alternative<nif::NiNode>(blk)) {
        std::vector<bool> seen(f.blocks.size(), false);
        auto shapes = count_shapes(f, links, idx, seen);
        auto* nn = std::get_if<nif::NiNode>(&blk);
        std::printf("%*s[%zu] %s '%s'  (children=%d, shapes=%zu)",
                    depth * 2, "", idx, kind, name.c_str(),
                    link_count_if_node(blk), shapes);
        if (!nn->av.property_links.empty()) {
            std::printf("  props=[");
            for (std::size_t i = 0; i < nn->av.property_links.size(); ++i) {
                if (i) std::printf(" ");
                auto it = links.find(nn->av.property_links[i]);
                if (it != links.end()) {
                    const auto& pb = f.blocks[it->second];
                    const char* pkind =
                        std::holds_alternative<nif::NiMaterialProperty>(pb)    ? "Mat"
                      : std::holds_alternative<nif::NiTextureProperty>(pb)     ? "Tex"
                      : std::holds_alternative<nif::NiMultiTextureProperty>(pb)? "MultiTex"
                      : std::holds_alternative<nif::NiAlphaProperty>(pb)       ? "Alpha"
                      : std::holds_alternative<nif::NiZBufferProperty>(pb)     ? "Z"
                      : std::holds_alternative<nif::NiVertexColorProperty>(pb) ? "VColor"
                      : "?";
                    std::printf("%s@%zu", pkind, it->second);
                } else {
                    std::printf("UNRESOLVED");
                }
            }
            std::printf("]");
        }
        std::printf("\n");
        auto* n = nn;
        for (auto link : n->child_links) {
            auto it = links.find(link);
            if (it != links.end()) print_node(f, links, it->second, depth + 1, visited);
            else std::printf("%*s[unresolved link 0x%08x]\n",
                             (depth + 1) * 2, "", link);
        }
    } else if (std::holds_alternative<nif::NiTriShape>(blk)) {
        auto* s = std::get_if<nif::NiTriShape>(&blk);
        std::printf("%*s[%zu] %s '%s'", depth * 2, "", idx, kind, name.c_str());
        if (!s->av.property_links.empty()) {
            std::printf("  props=[");
            for (std::size_t i = 0; i < s->av.property_links.size(); ++i) {
                if (i) std::printf(" ");
                auto it = links.find(s->av.property_links[i]);
                if (it != links.end()) {
                    const auto& pb = f.blocks[it->second];
                    const char* pkind =
                        std::holds_alternative<nif::NiMaterialProperty>(pb)    ? "Mat"
                      : std::holds_alternative<nif::NiTextureProperty>(pb)     ? "Tex"
                      : std::holds_alternative<nif::NiMultiTextureProperty>(pb)? "MultiTex"
                      : std::holds_alternative<nif::NiAlphaProperty>(pb)       ? "Alpha"
                      : std::holds_alternative<nif::NiZBufferProperty>(pb)     ? "Z"
                      : std::holds_alternative<nif::NiVertexColorProperty>(pb) ? "VColor"
                      : "?";
                    std::printf("%s@%zu", pkind, it->second);
                } else {
                    std::printf("UNRESOLVED");
                }
            }
            std::printf("]");
        }
        std::printf("\n");
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <path/to/file.nif>\n", argv[0]);
        return 2;
    }
    fs::path path = argv[1];
    nif::File f;
    try {
        f = nif::load(path);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "load failed: %s\n", e.what());
        return 1;
    }

    std::printf("# %s — %zu blocks (eof_reached=%d)\n\n",
                path.filename().string().c_str(), f.blocks.size(),
                f.eof_reached);

    // Print every top-level NiNode (block 0 is typically the root; we
    // walk all NiNode-typed blocks not reached by recursion). Simpler:
    // start from block 0 and print descendants; then list any unreached
    // NiNode blocks as orphans.
    auto links = build_link_map(f);
    std::vector<bool> visited(f.blocks.size(), false);
    print_node(f, links, 0, 0, visited);

    bool printed_orphan_header = false;
    for (std::size_t i = 1; i < f.blocks.size(); ++i) {
        if (visited[i]) continue;
        if (!std::holds_alternative<nif::NiNode>(f.blocks[i])) continue;
        if (!printed_orphan_header) {
            std::printf("\n# Orphan NiNodes (not reached from block 0):\n");
            printed_orphan_header = true;
        }
        print_node(f, links, i, 0, visited);
    }
    return 0;
}
