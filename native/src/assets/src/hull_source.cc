#include <assets/hull_source.h>
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>

namespace assets {
std::string hull_source_string(const std::filesystem::path& path, float scale) {
    if (scale == 1.0f) return path.string();
    char buf[32]; std::snprintf(buf, sizeof buf, "%.6g", static_cast<double>(scale));
    return path.string() + "#s=" + buf;
}
HullSource split_hull_source(const std::filesystem::path& source) {
    const std::string s = source.string();
    const auto at = s.rfind("#s=");
    if (at == std::string::npos) return {source, 1.0f};
    return {std::filesystem::path(s.substr(0, at)), std::strtof(s.c_str() + at + 3, nullptr)};
}
bool is_gltf_path(const std::filesystem::path& p) {
    std::string e = p.extension().string();
    std::transform(e.begin(), e.end(), e.begin(), [](unsigned char c) { return std::tolower(c); });
    return e == ".gltf" || e == ".glb";
}
}  // namespace assets
