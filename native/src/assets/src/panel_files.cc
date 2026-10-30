#include <assets/panel_files.h>

#include <algorithm>
#include <cctype>
#include <string>
#include <system_error>
#include <utility>

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
    std::vector<fs::path> orphans;
    for (const auto& dir : dirs) {
        std::array<fs::path, kPanelVariants> found;
        std::error_code ec;
        for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
            std::error_code type_ec;
            if (!it->is_regular_file(type_ec)) continue;
            const fs::path& p = it->path();
            if (lower(p.extension().string()) != ".json") continue;
            const std::string name = lower(p.stem().string());
            for (int v = 0; v < kPanelVariants; ++v) {
                if (name == stem + kSuffix[v]) found[v] = p;
            }
        }
        if (!found[kPanelDefault].empty()) {
            out.by_variant = found;
            return out;
        }
        // A later dir may still hold the default; these count only if none does.
        for (int v = 1; v < kPanelVariants; ++v)
            if (!found[v].empty()) orphans.push_back(found[v]);
    }
    out.orphans = std::move(orphans);
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
