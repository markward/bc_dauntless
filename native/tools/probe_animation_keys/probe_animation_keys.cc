// native/tools/probe_animation_keys/probe_animation_keys.cc
//
// Survey #6 + #7 from the round-2 follow-up list:
//
//  6. BC NIF rotation key types in use — which of LIN/BEZ/TCB/EULER/STEP
//     does BC author? Drives test-coverage priority.
//  7. BC NIF position/scale key presence — does BC actually animate
//     translation or scale, or only rotation? Determines how completely
//     we need to implement the channel readers.
//
// Walks every NIF under <root>, finds all NiKeyframeData blocks, and
// reports per-channel type histograms plus per-file presence counts.

#include <nif/block.h>
#include <nif/file.h>

#include <cstdio>
#include <filesystem>
#include <map>
#include <string>
#include <variant>

namespace fs = std::filesystem;

namespace {

bool is_nif(const fs::path& p) {
    auto ext = p.extension().string();
    for (auto& c : ext) c = static_cast<char>(std::tolower(c));
    return ext == ".nif";
}

const char* rot_type_name(std::uint32_t t) {
    switch (t) {
        case 0: return "NONE";   // num_rotation_keys == 0
        case 1: return "LIN";
        case 2: return "BEZ";    // Hermite/quadratic
        case 3: return "TCB";
        case 4: return "EULER";
        case 5: return "STEP";
        default: return "?";
    }
}

const char* float_type_name(std::uint32_t t) {
    switch (t) {
        case 0: return "NONE";
        case 1: return "LIN";
        case 2: return "BEZ";
        case 3: return "TCB";
        case 5: return "STEP";
        default: return "?";
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <root-directory>\n", argv[0]);
        return 2;
    }
    fs::path root = argv[1];

    std::size_t total_files = 0;
    std::size_t files_with_kfd = 0;
    std::size_t total_kfd = 0;

    std::map<std::uint32_t, std::size_t> rot_type_hist;
    std::map<std::uint32_t, std::size_t> trans_type_hist;
    std::map<std::uint32_t, std::size_t> scale_type_hist;
    std::size_t kfd_with_rotation = 0;
    std::size_t kfd_with_translation = 0;
    std::size_t kfd_with_scale = 0;
    std::size_t total_rotation_keys = 0;
    std::size_t total_translation_keys = 0;
    std::size_t total_scale_keys = 0;
    std::size_t max_rot_keys = 0;
    std::size_t max_trans_keys = 0;
    std::size_t max_scale_keys = 0;

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
        bool any_kfd = false;
        for (auto& b : f.blocks) {
            auto* kd = std::get_if<nif::NiKeyframeData>(&b);
            if (!kd) continue;
            ++total_kfd;
            any_kfd = true;
            rot_type_hist[kd->rotation_type]++;
            trans_type_hist[kd->translations.interpolation]++;
            scale_type_hist[kd->scales.interpolation]++;
            if (kd->num_rotation_keys != 0) {
                ++kfd_with_rotation;
                total_rotation_keys += kd->num_rotation_keys;
                if (kd->num_rotation_keys > max_rot_keys) max_rot_keys = kd->num_rotation_keys;
            }
            if (kd->translations.num_keys != 0) {
                ++kfd_with_translation;
                total_translation_keys += kd->translations.num_keys;
                if (kd->translations.num_keys > max_trans_keys) max_trans_keys = kd->translations.num_keys;
            }
            if (kd->scales.num_keys != 0) {
                ++kfd_with_scale;
                total_scale_keys += kd->scales.num_keys;
                if (kd->scales.num_keys > max_scale_keys) max_scale_keys = kd->scales.num_keys;
            }
        }
        if (any_kfd) ++files_with_kfd;
    }

    std::printf("=== animation-key survey (%zu files, %zu with NiKeyframeData, "
                "%zu NiKeyframeData blocks total) ===\n\n",
                total_files, files_with_kfd, total_kfd);

    std::printf("rotation channel:\n");
    std::printf("  blocks with rotation keys: %zu / %zu (%.1f%%)\n",
                kfd_with_rotation, total_kfd,
                total_kfd > 0 ? 100.0 * kfd_with_rotation / total_kfd : 0.0);
    std::printf("  rotation_type histogram:\n");
    for (auto& [t, n] : rot_type_hist) {
        std::printf("    %u (%-5s): %zu\n", t, rot_type_name(t), n);
    }
    std::printf("  total rotation keys across corpus: %zu (max per block: %zu)\n\n",
                total_rotation_keys, max_rot_keys);

    std::printf("translation channel:\n");
    std::printf("  blocks with translation keys: %zu / %zu (%.1f%%)\n",
                kfd_with_translation, total_kfd,
                total_kfd > 0 ? 100.0 * kfd_with_translation / total_kfd : 0.0);
    std::printf("  translation interpolation histogram:\n");
    for (auto& [t, n] : trans_type_hist) {
        std::printf("    %u (%-5s): %zu\n", t, float_type_name(t), n);
    }
    std::printf("  total translation keys: %zu (max per block: %zu)\n\n",
                total_translation_keys, max_trans_keys);

    std::printf("scale channel:\n");
    std::printf("  blocks with scale keys: %zu / %zu (%.1f%%)\n",
                kfd_with_scale, total_kfd,
                total_kfd > 0 ? 100.0 * kfd_with_scale / total_kfd : 0.0);
    std::printf("  scale interpolation histogram:\n");
    for (auto& [t, n] : scale_type_hist) {
        std::printf("    %u (%-5s): %zu\n", t, float_type_name(t), n);
    }
    std::printf("  total scale keys: %zu (max per block: %zu)\n",
                total_scale_keys, max_scale_keys);
    return 0;
}
