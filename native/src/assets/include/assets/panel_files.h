#pragma once

#include <array>
#include <filesystem>
#include <vector>

namespace assets {

/// Bridge Lottie panels (spec 2026-10-28-bridge-lottie-panels-design.md §3, §5):
/// the animation files that sit beside a panel's still. Slots are the file
/// variants, not the bridge states: 0 `<stem>.json`, 1 `_y`, 2 `_r`, 3 `_s`.
inline constexpr int kPanelDefault = 0;
inline constexpr int kPanelYellow  = 1;
inline constexpr int kPanelRed     = 2;
inline constexpr int kPanelSpecial = 3;
inline constexpr int kPanelVariants = 4;

struct PanelFiles {
    /// An empty path means absent. When the default is absent every entry is
    /// empty: a state file never plays without its default.
    std::array<std::filesystem::path, kPanelVariants> by_variant;
    /// State files found when no dir holds the default: ignored, for the
    /// caller to report (the panel worker warns once per file).
    std::vector<std::filesystem::path> orphans;
};

/// Looks for `<stem>.json` (stem = the albedo's filename stem) in `dirs`,
/// case-insensitively, regular files only; the first dir holding it wins.
/// The state files are searched only in that same dir. Each dir is listed
/// once, and nothing is printed.
PanelFiles find_panel_files(const std::filesystem::path& albedo,
                            const std::vector<std::filesystem::path>& dirs);

/// Which variant plays for a bridge state (the `kBridgeState*` values:
/// 0 green, 1 yellow, 2 red, 3 offline, 4 special), given which variants are
/// valid. Green/offline -> default; yellow -> _y else default; red -> _r else
/// _y else default; special -> _s else default. -1 when nothing on the chain
/// is valid.
int select_panel_variant(int bridge_state,
                         const std::array<bool, kPanelVariants>& valid);

}  // namespace assets
