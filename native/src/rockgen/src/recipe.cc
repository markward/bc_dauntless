// native/src/rockgen/src/recipe.cc
#include <rockgen/recipe.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace rockgen {
namespace {

using json = nlohmann::json;

/// The value at `key`, or throw naming it. `path` is the dotted location of
/// `j` inside the recipe ("" at the root) so a nested miss names its parent.
const json& req(const json& j, const std::string& key, const std::string& path = "") {
    const std::string name = path.empty() ? key : path + "." + key;
    if (!j.is_object() || !j.contains(key))
        throw std::runtime_error("recipe: missing '" + name + "'");
    return j.at(key);
}

/// Typed read of `j[key]`; a type mismatch also names the key.
template <typename T>
T get(const json& j, const std::string& key, const std::string& path = "") {
    const json& v = req(j, key, path);
    try {
        return v.get<T>();
    } catch (const json::exception&) {
        const std::string name = path.empty() ? key : path + "." + key;
        throw std::runtime_error("recipe: bad type for '" + name + "'");
    }
}

/// A two-element [min, max] array.
template <typename T>
void get_range(const json& j, const std::string& key, const std::string& path,
               T& lo, T& hi) {
    const auto v = get<std::vector<T>>(j, key, path);
    const std::string name = path.empty() ? key : path + "." + key;
    if (v.size() != 2)
        throw std::runtime_error("recipe: '" + name + "' must be [min, max]");
    lo = v[0];
    hi = v[1];
}

KindParams parse_kind(const json& j, const std::string& path, bool with_cuts) {
    KindParams k;
    k.lod_subdivisions = get<std::vector<int>>(j, "lod_subdivisions", path);
    if (k.lod_subdivisions.empty())
        throw std::runtime_error("recipe: '" + path + ".lod_subdivisions' is empty");
    k.texture_size = get<int>(j, "texture_size", path);
    if (with_cuts) get_range(j, "cuts", path, k.cuts_min, k.cuts_max);
    return k;
}

FamilyParams parse_family(const json& j, const std::string& path) {
    FamilyParams f;
    f.name      = get<std::string>(j, "name", path);
    f.majors    = get<int>(j, "majors", path);
    f.fragments = get<int>(j, "fragments", path);
    const auto pal = get<std::vector<std::vector<float>>>(j, "palette", path);
    if (pal.size() != 2 || pal[0].size() != 3 || pal[1].size() != 3)
        throw std::runtime_error("recipe: '" + path + ".palette' must be [[r,g,b],[r,g,b]]");
    f.color_a = glm::vec3(pal[0][0], pal[0][1], pal[0][2]);
    f.color_b = glm::vec3(pal[1][0], pal[1][1], pal[1][2]);
    f.gloss       = get<float>(j, "gloss", path);
    f.displace    = get<float>(j, "displace", path);
    f.octaves     = get<int>(j, "octaves", path);
    f.noise_scale = get<float>(j, "noise_scale", path);
    get_range(j, "axis", path, f.axis_min, f.axis_max);
    get_range(j, "craters", path, f.craters_min, f.craters_max);
    get_range(j, "crater_radius", path, f.crater_radius_min, f.crater_radius_max);
    f.detail_octaves  = get<int>(j, "detail_octaves", path);
    f.detail_scale    = get<float>(j, "detail_scale", path);
    f.normal_strength = get<float>(j, "normal_strength", path);
    return f;
}

std::string two_digits(int n) {
    char buf[16];
    std::snprintf(buf, sizeof buf, "%02d", n);
    return buf;
}

}  // namespace

Recipe parse_recipe(const std::string& json_text) {
    json j;
    try {
        j = json::parse(json_text);
    } catch (const json::parse_error& e) {
        throw std::runtime_error(std::string("recipe: invalid JSON: ") + e.what());
    }
    Recipe r;
    r.tool_version       = get<int>(j, "tool_version");
    r.seed               = get<std::uint64_t>(j, "seed");
    r.bound_radius_m     = get<float>(j, "bound_radius_m");
    r.impostor_view_size = get<int>(j, "impostor_view_size");
    r.volume_dims        = get<int>(j, "volume_dims");
    r.major    = parse_kind(req(j, "major"), "major", /*with_cuts=*/false);
    r.fragment = parse_kind(req(j, "fragment"), "fragment", /*with_cuts=*/true);
    const json& fams = req(j, "families");
    if (!fams.is_array()) throw std::runtime_error("recipe: bad type for 'families'");
    for (size_t i = 0; i < fams.size(); ++i)
        r.families.push_back(parse_family(fams[i], "families[" + std::to_string(i) + "]"));
    return r;
}

std::vector<RockSpec> expand_recipe(const Recipe& r) {
    std::vector<RockSpec> out;
    const std::string recipe_seed = std::to_string(r.seed);
    for (const FamilyParams& f : r.families) {
        for (int pass = 0; pass < 2; ++pass) {
            const bool fragment = (pass == 1);
            const int count = fragment ? f.fragments : f.majors;
            for (int n = 1; n <= count; ++n) {
                RockSpec s;
                s.id = std::string(fragment ? "fragments/" : "majors/") + f.name + "_" + two_digits(n);
                s.fragment = fragment;
                s.family = &f;
                s.kind = fragment ? &r.fragment : &r.major;
                s.seed = fnv1a64(recipe_seed + ":" + s.id);
                s.bound_radius_m = r.bound_radius_m;
                out.push_back(std::move(s));
            }
        }
    }
    return out;
}

std::uint64_t fnv1a64(const std::string& s) {
    // Standard FNV-1a 64 offset basis 14695981039346656037 (0xcbf29ce484222325).
    std::uint64_t h = 0xcbf29ce484222325ull;
    for (unsigned char c : s) {
        h ^= c;
        h *= 0x100000001b3ull;   // FNV prime 1099511628211
    }
    return h;
}

}  // namespace rockgen
