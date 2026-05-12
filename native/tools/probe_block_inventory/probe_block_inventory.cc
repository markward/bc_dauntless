// native/tools/probe_block_inventory/probe_block_inventory.cc
//
// Item #9 deep dive: produce the full RTTI vocabulary BC NIFs actually
// use. scan_nifs already confirmed there are zero unknown block types
// (805/805 files reach EOF), but doesn't tell us which of our registered
// types BC exercises and which we registered "just in case."
//
// Walks every NIF under <root>, visits each Block variant, and reports:
//   - per-type total occurrences and per-file presence counts
//   - registered-but-unused types (dead-code candidates)
//   - the 10 most common types (load-bearing for parser priority)
//
// Usage:
//   probe_block_inventory <root-directory>

#include <nif/block.h>
#include <nif/file.h>

#include <cstdio>
#include <filesystem>
#include <map>
#include <set>
#include <string>
#include <type_traits>
#include <variant>

namespace fs = std::filesystem;

namespace {

bool is_nif(const fs::path& p) {
    auto ext = p.extension().string();
    for (auto& c : ext) c = static_cast<char>(std::tolower(c));
    return ext == ".nif";
}

// Map a Block variant alternative to its RTTI name string.
const char* block_type_name(const nif::Block& b) {
    return std::visit([](auto&& x) -> const char* {
        using T = std::decay_t<decltype(x)>;
        if      constexpr (std::is_same_v<T, std::monostate>)               return "<monostate>";
        else if constexpr (std::is_same_v<T, nif::NiNode>)                  return "NiNode";
        else if constexpr (std::is_same_v<T, nif::NiTriShape>)              return "NiTriShape";
        else if constexpr (std::is_same_v<T, nif::NiTriShapeData>)          return "NiTriShapeData";
        else if constexpr (std::is_same_v<T, nif::NiZBufferProperty>)       return "NiZBufferProperty";
        else if constexpr (std::is_same_v<T, nif::NiVertexColorProperty>)   return "NiVertexColorProperty";
        else if constexpr (std::is_same_v<T, nif::NiAlphaProperty>)         return "NiAlphaProperty";
        else if constexpr (std::is_same_v<T, nif::NiTextureModeProperty>)   return "NiTextureModeProperty";
        else if constexpr (std::is_same_v<T, nif::NiImage>)                 return "NiImage";
        else if constexpr (std::is_same_v<T, nif::NiTextureProperty>)       return "NiTextureProperty";
        else if constexpr (std::is_same_v<T, nif::NiMaterialProperty>)      return "NiMaterialProperty";
        else if constexpr (std::is_same_v<T, nif::NiKeyframeController>)    return "NiKeyframeController";
        else if constexpr (std::is_same_v<T, nif::NiTriShapeSkinController>) return "NiTriShapeSkinController";
        else if constexpr (std::is_same_v<T, nif::NiTexturingProperty>)     return "NiTexturingProperty";
        else if constexpr (std::is_same_v<T, nif::NiMultiTextureProperty>)  return "NiMultiTextureProperty";
        else if constexpr (std::is_same_v<T, nif::NiKeyframeData>)          return "NiKeyframeData";
        else if constexpr (std::is_same_v<T, nif::NiStringExtraData>)       return "NiStringExtraData";
        else if constexpr (std::is_same_v<T, nif::NiFlipController>)        return "NiFlipController";
        else if constexpr (std::is_same_v<T, nif::NiBinaryVoxelExtraData>)  return "NiBinaryVoxelExtraData";
        else if constexpr (std::is_same_v<T, nif::NiBinaryVoxelData>)       return "NiBinaryVoxelData";
        else if constexpr (std::is_same_v<T, nif::NiCamera>)                return "NiCamera";
        else if constexpr (std::is_same_v<T, nif::NiPointLight>)            return "NiPointLight";
        else if constexpr (std::is_same_v<T, nif::NiSpotLight>)             return "NiSpotLight";
        else if constexpr (std::is_same_v<T, nif::NiAmbientLight>)          return "NiAmbientLight";
        else if constexpr (std::is_same_v<T, nif::NiDirectionalLight>)      return "NiDirectionalLight";
        else if constexpr (std::is_same_v<T, nif::NiRawImageData>)          return "NiRawImageData";
        else if constexpr (std::is_same_v<T, nif::NiVisController>)         return "NiVisController";
        else if constexpr (std::is_same_v<T, nif::NiVisData>)               return "NiVisData";
        else if constexpr (std::is_same_v<T, nif::NiLookAtController>)      return "NiLookAtController";
        else if constexpr (std::is_same_v<T, nif::NiRollController>)        return "NiRollController";
        else if constexpr (std::is_same_v<T, nif::NiFloatData>)             return "NiFloatData";
        else                                                                return "<unmapped>";
    }, b);
}

// Currently-registered block types we count for the dead-code check.
// We omit `NiBone` from this list intentionally: it's a class-name alias
// that reuses the NiNode body parser, so any NiBone block deserializes
// to an `NiNode` variant value. The probe can't distinguish bones from
// regular nodes after parsing — so NiBone would always appear as
// "unused" even when bones are present. Leaving it out keeps the
// dead-code list signal-rich.
const char* kRegisteredTypes[] = {
    "NiAlphaProperty", "NiAmbientLight", "NiBinaryVoxelData",
    "NiBinaryVoxelExtraData", "NiCamera", "NiDirectionalLight",
    "NiFlipController", "NiFloatData", "NiImage", "NiKeyframeController",
    "NiKeyframeData", "NiLookAtController", "NiMaterialProperty",
    "NiMultiTextureProperty", "NiNode", "NiPointLight", "NiRawImageData",
    "NiRollController", "NiSpotLight", "NiStringExtraData",
    "NiTextureModeProperty", "NiTextureProperty", "NiTexturingProperty",
    "NiTriShape", "NiTriShapeData", "NiTriShapeSkinController",
    "NiVertexColorProperty", "NiVisController", "NiVisData",
    "NiZBufferProperty",
};

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <root-directory>\n", argv[0]);
        return 2;
    }
    fs::path root = argv[1];

    std::map<std::string, std::size_t> per_type_total;
    std::map<std::string, std::size_t> per_type_files;
    std::size_t total_files = 0;
    std::size_t total_blocks = 0;

    for (auto& entry : fs::recursive_directory_iterator(root)) {
        if (!entry.is_regular_file()) continue;
        if (!is_nif(entry.path())) continue;
        ++total_files;
        nif::File f;
        try {
            f = nif::load(entry.path());
        } catch (const std::exception&) {
            continue;
        }
        std::set<std::string> types_in_file;
        for (auto& b : f.blocks) {
            ++total_blocks;
            std::string name = block_type_name(b);
            per_type_total[name]++;
            types_in_file.insert(name);
        }
        for (auto& n : types_in_file) per_type_files[n]++;
    }

    std::printf("=== block-inventory survey ===\n");
    std::printf("files scanned: %zu\n", total_files);
    std::printf("blocks total : %zu\n\n", total_blocks);

    // Print histogram sorted by total occurrences (descending).
    std::vector<std::pair<std::string, std::size_t>> sorted(per_type_total.begin(),
                                                            per_type_total.end());
    std::sort(sorted.begin(), sorted.end(),
              [](auto& a, auto& b) { return a.second > b.second; });

    std::printf("type histogram (count, present-in-files, %%-of-corpus):\n");
    for (auto& [name, n] : sorted) {
        std::size_t fc = per_type_files[name];
        std::printf("  %-32s %8zu  %5zu  %5.1f%%\n",
                    name.c_str(), n, fc,
                    total_files > 0 ? 100.0 * fc / total_files : 0.0);
    }

    // Compare against registered types — which registered types never
    // appear in BC content?
    std::printf("\nregistered-but-unused types (dead-code candidates):\n");
    std::set<std::string> seen;
    for (auto& [name, _] : per_type_total) seen.insert(name);
    bool any_unused = false;
    for (auto* reg : kRegisteredTypes) {
        if (seen.find(reg) == seen.end()) {
            std::printf("  %s\n", reg);
            any_unused = true;
        }
    }
    if (!any_unused) std::printf("  (none — every registered type appears at least once)\n");

    return 0;
}
