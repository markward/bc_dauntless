// Dump NiTextureProperty + NiFlipController + NiImage details for EBridge.
#include <nif/file.h>
#include <nif/block.h>

#include <cstdio>
#include <filesystem>
#include <unordered_map>
#include <variant>

namespace fs = std::filesystem;

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    nif::File f = nif::load(argv[1]);

    std::unordered_map<std::uint32_t, std::size_t> link_map;
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) link_map[f.block_ids[i]] = i;

    auto lookup = [&](std::uint32_t link) -> int {
        auto it = link_map.find(link);
        return it == link_map.end() ? -1 : static_cast<int>(it->second);
    };

    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        if (auto* p = std::get_if<nif::NiTextureProperty>(&f.blocks[i])) {
            int img_idx  = lookup(p->image_link);
            int ctrl_idx = lookup(p->obj.controller_link);
            const char* img_kind = "missing";
            const char* ctrl_kind = "missing";
            std::string img_name, ctrl_name;
            if (img_idx >= 0) {
                if (auto* im = std::get_if<nif::NiImage>(&f.blocks[img_idx])) {
                    img_kind = "NiImage";
                    img_name = im->file_name;
                } else {
                    img_kind = "OTHER";
                }
            }
            if (ctrl_idx >= 0) {
                if (auto* c = std::get_if<nif::NiFlipController>(&f.blocks[ctrl_idx])) {
                    ctrl_kind = "NiFlipController";
                    char buf[256];
                    std::snprintf(buf, sizeof(buf), "%u frames", c->num_sources);
                    ctrl_name = buf;
                } else {
                    ctrl_kind = "OTHER";
                }
            }
            std::printf("[%zu] NiTextureProperty image_link=0x%08x->%s'%s'  ctrl=0x%08x->%s '%s'\n",
                i, p->image_link, img_kind, img_name.c_str(),
                p->obj.controller_link, ctrl_kind, ctrl_name.c_str());
        }
    }
    return 0;
}
