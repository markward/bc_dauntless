// native/tools/dump_bridge_assets/dump_bridge_assets.cc
//
// Headless load of a NIF through the full assets pipeline (NIF parse +
// link resolve + material build + mesh build), with the GL-upload step
// stubbed out. Prints every node + mesh + base texture index so we can
// spot shapes that fall back to a missing-texture white quad. Also
// catches missing-texture errors thrown by PathResolver and reports
// them per file.
//
// Usage:
//   dump_bridge_assets <path/to/file.nif> <texture-search-dir> [<more-dirs>...]
#include <assets/cache.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <cstdio>
#include <exception>
#include <filesystem>
#include <vector>

namespace fs = std::filesystem;

namespace {

assets::AssetCache::Config stub_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = [](const assets::Image&, bool) {
        return assets::Texture(/*id=*/0, 1, 1, false);
    };
    cfg.mesh_uploader = [](assets::MeshCpu cpu) {
        return assets::Mesh(0, 0, 0,
            static_cast<std::uint32_t>(cpu.indices.size()),
            cpu.material_index, cpu.node_index);
    };
    return cfg;
}

const char* stage_name(assets::Material::StageSlot s) {
    switch (s) {
        case assets::Material::StageSlot::Base:   return "Base";
        case assets::Material::StageSlot::Dark:   return "Dark";
        case assets::Material::StageSlot::Detail: return "Detail";
        case assets::Material::StageSlot::Gloss:  return "Gloss";
        case assets::Material::StageSlot::Glow:   return "Glow";
        case assets::Material::StageSlot::Bump:   return "Bump";
        case assets::Material::StageSlot::Decal0: return "Decal0";
        case assets::Material::StageSlot::Decal1: return "Decal1";
        case assets::Material::StageSlot::Decal2: return "Decal2";
        default: return "?";
    }
}

void dump_model(const assets::Model& m) {
    std::printf("# %zu nodes, %zu meshes, %zu materials, %zu textures\n\n",
                m.nodes.size(), m.meshes.size(), m.materials.size(),
                m.textures.size());

    std::size_t shapes_white = 0;
    std::size_t shapes_total = 0;
    for (std::size_t ni = 0; ni < m.nodes.size(); ++ni) {
        const auto& node = m.nodes[ni];
        if (node.meshes.empty()) continue;
        for (int mesh_idx : node.meshes) {
            ++shapes_total;
            const auto& mesh = m.meshes[mesh_idx];
            const int matidx = mesh.material_index();
            const assets::Material* matp = nullptr;
            if (matidx >= 0 && matidx < static_cast<int>(m.materials.size())) {
                matp = &m.materials[matidx];
            }
            const int base_tex = matp ? matp->stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Base)
            ].texture_index : -1;
            const bool will_render_white = (base_tex < 0);
            if (will_render_white) ++shapes_white;
            std::printf("node[%3zu] '%s'  mesh[%d]  mat=%d  base_tex=%d%s\n",
                        ni, node.name.c_str(), mesh_idx, matidx, base_tex,
                        will_render_white ? "  *** WHITE ***" : "");
            if (matp) {
                // Dump every non-empty stage so we can see whether the
                // texture is assigned to a different slot (Dark, Detail,
                // etc.) instead of Base.
                for (int s = 0; s < static_cast<int>(
                        assets::Material::StageSlot::Count); ++s) {
                    if (s == static_cast<int>(assets::Material::StageSlot::Base)) continue;
                    const auto& st = matp->stages[s];
                    if (st.texture_index >= 0) {
                        std::printf("                                stage[%s] tex=%d uv_set=%u\n",
                                    stage_name(static_cast<assets::Material::StageSlot>(s)),
                                    st.texture_index, st.uv_set);
                    }
                }
            }
        }
    }
    std::printf("\n# %zu shapes total, %zu would render WHITE (no Base texture)\n",
                shapes_total, shapes_white);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr,
            "usage: %s <path/to/file.nif> <texture-search-dir> [<more-dirs>...]\n",
            argv[0]);
        return 2;
    }
    fs::path nif_path = argv[1];
    std::vector<fs::path> dirs;
    for (int i = 2; i < argc; ++i) dirs.emplace_back(argv[i]);

    std::printf("# nif: %s\n# search-dirs:\n", nif_path.string().c_str());
    for (const auto& d : dirs) {
        std::printf("#   %s%s\n", d.string().c_str(),
                    fs::is_directory(d) ? "" : "  (NOT A DIRECTORY)");
    }
    std::printf("\n");

    try {
        assets::AssetCache cache(stub_config());
        auto handle = cache.load(nif_path, dirs);
        dump_model(*handle.get());
    } catch (const std::exception& e) {
        std::fprintf(stderr, "load failed: %s\n", e.what());
        return 1;
    }
    return 0;
}
