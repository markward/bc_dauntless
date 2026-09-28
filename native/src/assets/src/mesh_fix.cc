// native/src/assets/src/mesh_fix.cc
// Parsing half of the hull name-cut fix (spec:
// docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
#include <assets/mesh_fix.h>

#include <cstdio>
#include <nlohmann/json.hpp>

namespace assets {

std::string fnv1a64_hex(std::string_view bytes) {
    std::uint64_t h = 14695981039346656037ull;
    for (unsigned char c : bytes) { h ^= c; h *= 1099511628211ull; }
    char buf[17];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}

namespace {
MeshFixShapeRef read_ref(const nlohmann::json& j) {
    return {j.at("block").get<std::uint32_t>(), j.at("name").get<std::string>()};
}
}  // namespace

std::optional<MeshFix> parse_mesh_fix(std::string_view text, std::string* error) {
    auto fail = [&](std::string msg) -> std::optional<MeshFix> {
        if (error) *error = std::move(msg);
        return std::nullopt;
    };
    try {
        auto j = nlohmann::json::parse(text);
        MeshFix fix;
        fix.format = j.at("format").get<int>();
        if (fix.format != 1)
            return fail("unsupported mesh-fix format " + std::to_string(fix.format));
        for (const auto& jm : j.at("merges")) {
            MeshFixMerge m;
            m.patch  = read_ref(jm.at("patch"));
            m.target = read_ref(jm.at("target"));
            for (const auto& uv : jm.at("uvs")) {
                if (!uv.is_array() || uv.size() != 2) return fail("uv entry is not [u, v]");
                m.uvs.push_back({uv[0].get<float>(), uv[1].get<float>()});
            }
            for (const auto& w : jm.at("weld")) {
                if (!w.is_array() || w.size() != 2) return fail("weld entry is not a pair");
                m.weld.emplace_back(w[0].get<std::uint32_t>(), w[1].get<std::uint32_t>());
            }
            const auto& jn = jm.at("normals");
            if (!jn.is_null()) {
                std::vector<std::array<float, 3>> ns;
                for (const auto& n : jn) {
                    if (!n.is_array() || n.size() != 3) return fail("normal entry is not [x, y, z]");
                    ns.push_back({n[0].get<float>(), n[1].get<float>(), n[2].get<float>()});
                }
                m.normals = std::move(ns);
            }
            fix.merges.push_back(std::move(m));
        }
        return fix;
    } catch (const std::exception& e) {
        return fail(std::string("mesh-fix parse error: ") + e.what());
    }
}

}  // namespace assets
