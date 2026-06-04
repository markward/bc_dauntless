// Inspect NiFlipController values + per-frame image filenames in a NIF.
#include <nif/file.h>
#include <nif/block.h>
#include <cstdio>
#include <string>
#include <unordered_map>
#include <variant>

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    nif::File f = nif::load(argv[1]);

    std::unordered_map<std::uint32_t, std::size_t> link_map;
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) link_map[f.block_ids[i]] = i;

    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        auto* c = std::get_if<nif::NiFlipController>(&f.blocks[i]);
        if (!c) continue;
        std::printf("Block[%zu] NiFlipController:\n", i);
        std::printf("  flags=0x%04x freq=%.3f phase=%.3f start=%.3f stop=%.3f\n",
            c->flags, c->frequency, c->phase, c->start_time, c->stop_time);
        std::printf("  texture_slot=%u delta=%.4f num_sources=%u\n",
            c->texture_slot, c->delta, c->num_sources);
        for (std::size_t fr = 0; fr < c->image_links.size(); ++fr) {
            const auto link = c->image_links[fr];
            auto it = link_map.find(link);
            std::string name = "<unresolved>";
            if (it != link_map.end()) {
                const auto& blk = f.blocks[it->second];
                if (auto* img = std::get_if<nif::NiImage>(&blk)) {
                    name = img->file_name;
                }
            }
            std::printf("    frame %zu: '%s'\n", fr, name.c_str());
        }
    }
}
