#include <assets/panel_files.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <string>
#include <system_error>

namespace fs = std::filesystem;

namespace assets {

namespace {

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

constexpr const char* kSuffix[kPanelVariants] = {"", "_y", "_r", "_s"};

}  // namespace

PanelFiles find_panel_files(const fs::path& albedo, const std::vector<fs::path>& dirs) {
    PanelFiles out;
    const std::string stem = lower(albedo.stem().string());
    for (const auto& dir : dirs) {
        std::array<fs::path, kPanelVariants> found;
        std::error_code ec;
        for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
            const fs::path& p = it->path();
            if (lower(p.extension().string()) != ".json") continue;
            const std::string name = lower(p.stem().string());
            for (int v = 0; v < kPanelVariants; ++v) {
                if (name == stem + kSuffix[v]) found[v] = p;
            }
        }
        if (found[kPanelDefault].empty()) {
            // Only report a state file in the dir that would otherwise have
            // supplied the default; a later dir may still hold it.
            continue;
        }
        out.by_variant = found;
        return out;
    }
    // No default anywhere. Warn about orphaned state files, once per call.
    for (const auto& dir : dirs) {
        std::error_code ec;
        for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
            const fs::path& p = it->path();
            if (lower(p.extension().string()) != ".json") continue;
            const std::string name = lower(p.stem().string());
            for (int v = 1; v < kPanelVariants; ++v) {
                if (name == stem + kSuffix[v]) {
                    std::fprintf(stderr,
                        "[lottie] %s: no %s.json beside it; ignored\n",
                        p.string().c_str(), albedo.stem().string().c_str());
                    return out;
                }
            }
        }
    }
    return out;
}

int select_panel_variant(int bridge_state,
                         const std::array<bool, kPanelVariants>& valid) {
    // Chains per bridge state; kBridgeStateOffline (3) plays the default.
    int chain[3] = {kPanelDefault, -1, -1};
    switch (bridge_state) {
        case 1: chain[0] = kPanelYellow; chain[1] = kPanelDefault; break;
        case 2: chain[0] = kPanelRed; chain[1] = kPanelYellow; chain[2] = kPanelDefault; break;
        case 4: chain[0] = kPanelSpecial; chain[1] = kPanelDefault; break;
        default: break;
    }
    for (int v : chain) {
        if (v >= 0 && valid[static_cast<std::size_t>(v)]) return v;
    }
    return -1;
}

}  // namespace assets
