// native/src/assets/src/mesh_fix.cc
// Parsing + application halves of the hull name-cut fix (spec:
// docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
#include <assets/mesh_fix.h>

#include <cmath>
#include <cstdio>
#include <limits>
#include <unordered_map>
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

namespace {

constexpr std::size_t kNoIndex = static_cast<std::size_t>(-1);

/// Block-array index whose `file.block_ids` entry equals `link_id`, or
/// kNoIndex. `patch.block` / `target.block` (MeshFixShapeRef::block) are
/// already array indices, not link IDs — only cross-block references
/// (data_link, child_links) need this.
std::size_t index_of(const nif::File& file, std::uint32_t link_id) {
    for (std::size_t i = 0; i < file.block_ids.size(); ++i)
        if (file.block_ids[i] == link_id) return i;
    return kNoIndex;
}

/// The AvObjectBase of a block that has one (NiNode, NiTriShape), else null.
const nif::AvObjectBase* av_of(const nif::Block& b) {
    if (const auto* n = std::get_if<nif::NiNode>(&b)) return &n->av;
    if (const auto* s = std::get_if<nif::NiTriShape>(&b)) return &s->av;
    return nullptr;
}

/// Block-array index of the NiNode whose child_links resolves to `idx`, or
/// kNoIndex if `idx` is unparented (e.g. the scene root).
std::size_t parent_of(const nif::File& file, std::size_t idx) {
    for (std::size_t i = 0; i < file.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&file.blocks[i]);
        if (!node) continue;
        for (std::uint32_t link : node->child_links) {
            if (index_of(file, link) == idx) return i;
        }
    }
    return kNoIndex;
}

glm::mat4 local_transform(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    m[0] = glm::vec4(av.rotation.m[0], av.rotation.m[3], av.rotation.m[6], 0.0f);
    m[1] = glm::vec4(av.rotation.m[1], av.rotation.m[4], av.rotation.m[7], 0.0f);
    m[2] = glm::vec4(av.rotation.m[2], av.rotation.m[5], av.rotation.m[8], 0.0f);
    m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
    if (av.scale != 1.0f) {
        m[0] *= av.scale;
        m[1] *= av.scale;
        m[2] *= av.scale;
    }
    return m;
}

/// One merge, fully validated: everything Phase 2 needs to apply it without
/// re-deriving or re-checking anything.
struct MergePlan {
    std::size_t target_shape_idx = 0;
    std::size_t patch_shape_idx = 0;
    std::size_t target_data_idx = 0;
    std::size_t patch_data_idx = 0;
    /// patch vertex index -> target-data vertex index (welded onto an
    /// existing target vertex, or a newly appended one), size ==
    /// patch.num_vertices.
    std::vector<std::uint16_t> patch_to_target;
    /// Patch vertex indices that get appended (not welded), in ascending
    /// patch-vertex order — the order they land in the target's arrays.
    std::vector<std::uint16_t> append_order;
};

/// Validate merge `m` (index `merge_idx`, for error messages) against `file`
/// and fill `*plan` on success. Returns "" on success, else the refusal
/// reason (prefixed "merge N: "). Never mutates `file`.
std::string validate_merge(const nif::File& file, const MeshFixMerge& m,
                            std::size_t merge_idx, MergePlan* plan) {
    const std::string prefix = "merge " + std::to_string(merge_idx) + ": ";

    // Rule 1.
    if (m.patch.block >= file.blocks.size() || m.target.block >= file.blocks.size())
        return prefix + "block out of range";
    const auto* patch_shape = std::get_if<nif::NiTriShape>(&file.blocks[m.patch.block]);
    const auto* target_shape = std::get_if<nif::NiTriShape>(&file.blocks[m.target.block]);
    if (!patch_shape || !target_shape)
        return prefix + "block is not a NiTriShape";
    if (patch_shape->av.obj.name != m.patch.name)
        return prefix + "patch shape name mismatch";
    if (target_shape->av.obj.name != m.target.name)
        return prefix + "target shape name mismatch";

    // Rule 2.
    const std::size_t patch_data_idx = index_of(file, patch_shape->data_link);
    const std::size_t target_data_idx = index_of(file, target_shape->data_link);
    if (patch_data_idx == kNoIndex || patch_data_idx >= file.blocks.size())
        return prefix + "patch data_link unresolved";
    if (target_data_idx == kNoIndex || target_data_idx >= file.blocks.size())
        return prefix + "target data_link unresolved";
    const auto* patch_data = std::get_if<nif::NiTriShapeData>(&file.blocks[patch_data_idx]);
    const auto* target_data = std::get_if<nif::NiTriShapeData>(&file.blocks[target_data_idx]);
    if (!patch_data || !target_data)
        return prefix + "data_link does not point at NiTriShapeData";
    if (patch_data_idx == target_data_idx)
        return prefix + "patch and target share a data block";

    // Rule 3.
    if (patch_data->uv_sets.size() != 1 || target_data->uv_sets.size() != 1)
        return prefix + "both shapes must have exactly 1 UV set";
    if (!patch_data->has_normals || !target_data->has_normals)
        return prefix + "both shapes must have normals";
    if (patch_data->has_vertex_colors != target_data->has_vertex_colors)
        return prefix + "vertex-color presence mismatch";

    // Phase-1 hardening (final review, Ruling 9). None of these are reached
    // by any stock fix -- a NIF with has_vertices == false or a mismatched
    // array wouldn't have parsed a usable shape in the first place -- but a
    // corrupt or hand-edited fix, or a future non-stock source, must not read
    // out of bounds below.
    if (!patch_data->has_vertices || !target_data->has_vertices)
        return prefix + "shape has no vertex data";
    if (patch_data->vertices.size() != patch_data->num_vertices)
        return prefix + "patch vertex array size does not match num_vertices";
    if (target_data->vertices.size() != target_data->num_vertices)
        return prefix + "target vertex array size does not match num_vertices";
    for (const auto& tri : patch_data->triangles) {
        for (std::uint16_t idx : tri) {
            if (idx >= patch_data->num_vertices)
                return prefix + "patch triangle index out of range";
        }
    }
    {
        const std::size_t merged_tri_count =
            static_cast<std::size_t>(target_data->num_triangles) + patch_data->num_triangles;
        if (merged_tri_count > 65535)
            return prefix + "merged triangle count exceeds 65535";
    }

    // Rule 4.
    if (m.uvs.size() != patch_data->num_vertices)
        return prefix + "uv count does not match patch vertex count";
    if (m.normals.has_value() && m.normals->size() != patch_data->num_vertices)
        return prefix + "normal override count does not match patch vertex count";

    // World transforms (rule 5) — rotation-only for normals; a uniform
    // scale factor cancels out under normalize(), so the plain upper-left
    // 3x3 of the composed T*R*S is enough.
    const glm::mat4 w_target = nif_block_world(file, m.target.block);
    const glm::mat4 w_patch = nif_block_world(file, m.patch.block);
    const glm::mat4 to_target = glm::inverse(w_target) * w_patch;
    const glm::mat3 n_to_target = glm::inverse(glm::mat3(w_target)) * glm::mat3(w_patch);

    // Rule 5.
    std::vector<bool> patch_welded(patch_data->num_vertices, false);
    for (const auto& [pv, tv] : m.weld) {
        if (pv >= patch_data->num_vertices || tv >= target_data->num_vertices)
            return prefix + "weld index out of range";
        if (patch_welded[pv])
            return prefix + "patch vertex welded twice";
        patch_welded[pv] = true;

        const nif::Vec3& pp = patch_data->vertices[pv];
        const glm::vec4 pw = to_target * glm::vec4(pp.x, pp.y, pp.z, 1.0f);
        const nif::Vec3& tp = target_data->vertices[tv];
        const glm::vec3 delta = glm::vec3(pw) - glm::vec3(tp.x, tp.y, tp.z);
        if (glm::length(delta) > 1e-3f)
            return prefix + "weld positions differ";

        const auto& puv = m.uvs[pv];
        const nif::TexCoord& tuv = target_data->uv_sets[0][tv];
        if (std::fabs(puv[0] - tuv.u) > 1e-5f || std::fabs(puv[1] - tuv.v) > 1e-5f)
            return prefix + "weld uv differs";

        const nif::Vec3& pn = patch_data->normals[pv];
        const glm::vec3 pn_t = glm::normalize(n_to_target * glm::vec3(pn.x, pn.y, pn.z));
        const nif::Vec3& tn = target_data->normals[tv];
        if (glm::dot(pn_t, glm::vec3(tn.x, tn.y, tn.z)) <= 0.999f)
            return prefix + "weld normals differ";
    }

    // Rule 6.
    const std::size_t final_count = static_cast<std::size_t>(target_data->num_vertices)
                                   + patch_data->num_vertices - m.weld.size();
    if (final_count > 65535)
        return prefix + "merged vertex count exceeds 65535";

    plan->target_shape_idx = m.target.block;
    plan->patch_shape_idx = m.patch.block;
    plan->target_data_idx = target_data_idx;
    plan->patch_data_idx = patch_data_idx;
    plan->patch_to_target.assign(patch_data->num_vertices, 0);
    std::uint16_t next = target_data->num_vertices;
    for (std::uint16_t pv = 0; pv < patch_data->num_vertices; ++pv) {
        if (patch_welded[pv]) continue;
        plan->patch_to_target[pv] = next++;
        plan->append_order.push_back(pv);
    }
    for (const auto& [pv, tv] : m.weld) {
        plan->patch_to_target[static_cast<std::uint16_t>(pv)] = static_cast<std::uint16_t>(tv);
    }
    return "";
}

/// Mutate `target_data` in place: append the patch's un-welded vertices
/// (transformed into the target's frame) and every patch triangle
/// (remapped through `plan.patch_to_target`), then clear match groups.
void apply_merge(nif::File& file, const MeshFixMerge& m, const MergePlan& plan) {
    auto& target_data = std::get<nif::NiTriShapeData>(file.blocks[plan.target_data_idx]);
    const auto& patch_data = std::get<nif::NiTriShapeData>(file.blocks[plan.patch_data_idx]);

    const glm::mat4 w_target = nif_block_world(file, plan.target_shape_idx);
    const glm::mat4 w_patch = nif_block_world(file, plan.patch_shape_idx);
    const glm::mat4 to_target = glm::inverse(w_target) * w_patch;
    const glm::mat3 n_to_target = glm::inverse(glm::mat3(w_target)) * glm::mat3(w_patch);

    const bool has_colors = target_data.has_vertex_colors;

    for (std::uint16_t pv : plan.append_order) {
        const nif::Vec3& pp = patch_data.vertices[pv];
        const glm::vec3 wp = glm::vec3(to_target * glm::vec4(pp.x, pp.y, pp.z, 1.0f));
        target_data.vertices.push_back({wp.x, wp.y, wp.z});

        glm::vec3 src_n;
        if (m.normals.has_value()) {
            const auto& ov = (*m.normals)[pv];
            src_n = glm::vec3(ov[0], ov[1], ov[2]);
        } else {
            const nif::Vec3& pn = patch_data.normals[pv];
            src_n = glm::vec3(pn.x, pn.y, pn.z);
        }
        const glm::vec3 n = glm::normalize(n_to_target * src_n);
        target_data.normals.push_back({n.x, n.y, n.z});

        target_data.uv_sets[0].push_back({m.uvs[pv][0], m.uvs[pv][1]});

        if (has_colors) {
            target_data.vertex_colors.push_back(patch_data.vertex_colors[pv]);
        }
    }

    for (const auto& tri : patch_data.triangles) {
        target_data.triangles.push_back({
            plan.patch_to_target[tri[0]],
            plan.patch_to_target[tri[1]],
            plan.patch_to_target[tri[2]],
        });
    }

    target_data.num_vertices = static_cast<std::uint16_t>(target_data.vertices.size());
    target_data.num_triangles = static_cast<std::uint16_t>(target_data.triangles.size());
    target_data.num_triangle_points = static_cast<std::uint32_t>(target_data.triangles.size()) * 3;
    target_data.num_match_groups = 0;
    target_data.match_groups.clear();

    auto& patch_shape = std::get<nif::NiTriShape>(file.blocks[plan.patch_shape_idx]);
    patch_shape.av.flags |= 0x0001u;
}

}  // namespace

glm::mat4 nif_block_world(const nif::File& file, std::size_t block_index) {
    if (block_index >= file.blocks.size()) return glm::mat4(1.0f);
    const nif::AvObjectBase* av = av_of(file.blocks[block_index]);
    const glm::mat4 local = av ? local_transform(*av) : glm::mat4(1.0f);
    const std::size_t parent = parent_of(file, block_index);
    if (parent == kNoIndex || parent == block_index) return local;
    return nif_block_world(file, parent) * local;
}

std::string apply_mesh_fix(nif::File& file, const MeshFix& fix) {
    std::vector<MergePlan> plans(fix.merges.size());
    for (std::size_t i = 0; i < fix.merges.size(); ++i) {
        std::string err = validate_merge(file, fix.merges[i], i, &plans[i]);
        if (!err.empty()) return err;
    }

    // Cross-merge check: a NiTriShapeData block may play only one role
    // (target or patch) across the whole fix. Threading a cumulative
    // append offset through repeat use is out of scope (fix round 1) — a
    // second merge onto an already-grown target, or reusing a patch, would
    // silently misindex the second merge's triangles into vertices that
    // don't exist yet at validation time. Covers all three shapes: same
    // target twice, same patch twice, and one merge's patch being
    // another's target.
    std::unordered_map<std::size_t, std::size_t> data_block_owner;  // data idx -> first merge idx
    for (std::size_t i = 0; i < plans.size(); ++i) {
        for (std::size_t data_idx : {plans[i].target_data_idx, plans[i].patch_data_idx}) {
            auto [it, inserted] = data_block_owner.try_emplace(data_idx, i);
            if (!inserted) {
                return "merge " + std::to_string(i) + ": data block " +
                       std::to_string(data_idx) + " is also used by merge " +
                       std::to_string(it->second) +
                       " (each NiTriShapeData may appear in only one merge)";
            }
        }
    }

    for (std::size_t i = 0; i < fix.merges.size(); ++i) {
        apply_merge(file, fix.merges[i], plans[i]);
    }
    return "";
}

}  // namespace assets
