// native/src/assets/src/mesh_fix.cc
// Parsing + application halves of the hull name-cut fix (spec:
// docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md) and of the
// bridge-shape-diff shape edits / texture ops (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md).
#include <assets/mesh_fix.h>

#include <algorithm>
#include <bit>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
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

std::optional<std::string> base64_decode(std::string_view text) {
    if (text.size() % 4 != 0) return std::nullopt;
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    };
    std::string out;
    out.reserve(text.size() / 4 * 3);
    for (std::size_t i = 0; i < text.size(); i += 4) {
        int v[4];
        int pad = 0;
        for (int k = 0; k < 4; ++k) {
            const char c = text[i + k];
            if (c == '=' && i + 4 == text.size() && k >= 2) { v[k] = 0; ++pad; continue; }
            if (pad) return std::nullopt;            // data after padding
            v[k] = val(c);
            if (v[k] < 0) return std::nullopt;
        }
        const std::uint32_t n = (v[0] << 18) | (v[1] << 12) | (v[2] << 6) | v[3];
        out.push_back(static_cast<char>((n >> 16) & 0xFF));
        if (pad < 2) out.push_back(static_cast<char>((n >> 8) & 0xFF));
        if (pad < 1) out.push_back(static_cast<char>(n & 0xFF));
    }
    return out;
}

namespace {
static_assert(std::endian::native == std::endian::little,
              "shape-edit payload decoder assumes a little-endian host");

/// Bounds-checked little-endian reader over the payload bytes.
struct PayloadReader {
    std::string_view s;
    std::size_t pos = 0;
    bool ok = true;
    template <class T> T get() {
        T v{};
        if (!ok || pos + sizeof(T) > s.size()) { ok = false; return v; }
        std::memcpy(&v, s.data() + pos, sizeof(T));
        pos += sizeof(T);
        return v;
    }
};
}  // namespace

std::optional<std::vector<ShapeEdit>> decode_shape_edits(std::string_view bytes,
                                                         std::string* error) {
    auto fail = [&](std::string msg) -> std::optional<std::vector<ShapeEdit>> {
        if (error) *error = std::move(msg);
        return std::nullopt;
    };
    if (bytes.size() < 4) return fail("shape_edits: bad magic");
    const std::string_view magic = bytes.substr(0, 4);
    if (magic != "BSD1" && magic != "BSD2") return fail("shape_edits: bad magic");
    const bool v2 = magic == "BSD2";
    PayloadReader r{bytes, 4};
    bool bad_kind = false;
    // BSD2 kind byte: 0 = literal, 1 = reference (u32 block, u16 vertex),
    // 2 = reference + 3 x f32 target-local delta (positions only).
    auto read_kind = [&](std::uint8_t max_kind) -> std::uint8_t {
        if (!v2) return 0;
        const auto kind = r.get<std::uint8_t>();
        if (r.ok && kind > max_kind) { bad_kind = true; r.ok = false; }
        return kind;
    };
    auto read_ref = [&]() {
        const auto block = r.get<std::uint32_t>();
        const auto vertex = r.get<std::uint16_t>();
        return ShapeEditRef{block, vertex};
    };
    auto read_pos = [&]() {
        ShapeEditPos p;
        const auto kind = read_kind(2);
        if (!r.ok) return p;
        if (kind == 0) {
            for (auto& c : p.literal) c = r.get<float>();
        } else {
            p.ref = read_ref();
            if (kind == 2) for (auto& c : p.delta) c = r.get<float>();
        }
        return p;
    };
    auto read_uv = [&]() {
        ShapeEditUv u;
        const auto kind = read_kind(1);
        if (!r.ok) return u;
        if (kind == 0) {
            for (auto& c : u.literal) c = r.get<float>();
        } else {
            u.ref = read_ref();
        }
        return u;
    };
    const auto shape_count = r.get<std::uint16_t>();
    std::vector<ShapeEdit> out;
    for (std::uint16_t s = 0; s < shape_count && r.ok; ++s) {
        ShapeEdit e;
        e.block = r.get<std::uint32_t>();
        e.orig_vertex_count = r.get<std::uint16_t>();
        e.orig_triangle_count = r.get<std::uint16_t>();
        const auto n_move = r.get<std::uint16_t>();
        const auto n_uv = r.get<std::uint16_t>();
        const auto n_addv = r.get<std::uint16_t>();
        const auto n_remt = r.get<std::uint16_t>();
        const auto n_addt = r.get<std::uint16_t>();
        for (int i = 0; i < n_move && r.ok; ++i) {
            const auto idx = r.get<std::uint16_t>();
            e.moves.emplace_back(idx, read_pos());
        }
        for (int i = 0; i < n_uv && r.ok; ++i) {
            const auto idx = r.get<std::uint16_t>();
            e.uvs.emplace_back(idx, read_uv());
        }
        for (int i = 0; i < n_addv && r.ok; ++i) {
            ShapeEditAddVertex v;
            v.pos = read_pos();
            v.uv0 = read_uv();
            if (v2) {
                v.attr_src = r.get<std::uint16_t>();
            } else {
                for (auto& c : v.uv1) c = r.get<float>();
                for (auto& c : v.color) c = r.get<float>();
            }
            e.add_vertices.push_back(v);
        }
        for (int i = 0; i < n_remt && r.ok; ++i) e.remove_triangles.push_back(r.get<std::uint16_t>());
        for (int i = 0; i < n_addt && r.ok; ++i)
            e.add_triangles.push_back({r.get<std::uint16_t>(), r.get<std::uint16_t>(),
                                       r.get<std::uint16_t>()});
        out.push_back(std::move(e));
    }
    if (bad_kind) return fail("shape_edits: unknown position/uv kind byte");
    if (!r.ok) return fail("shape_edits: payload truncated");
    if (r.pos != bytes.size()) return fail("shape_edits: trailing bytes after payload");
    return out;
}

std::optional<std::vector<MeshFixSmoothing>> decode_smoothing(std::string_view bytes,
                                                              std::string* error) {
    auto fail = [&](std::string msg) -> std::optional<std::vector<MeshFixSmoothing>> {
        if (error) *error = std::move(msg);
        return std::nullopt;
    };
    if (bytes.size() < 4 || bytes.substr(0, 4) != "BSM1") return fail("smoothing: bad magic");
    PayloadReader r{bytes, 4};
    const int n_shapes = r.get<std::uint16_t>();
    std::vector<MeshFixSmoothing> out;
    for (int i = 0; i < n_shapes && r.ok; ++i) {
        MeshFixSmoothing m;
        m.block = r.get<std::uint32_t>();
        m.vertex_count = r.get<std::uint16_t>();
        const int n_hard = r.get<std::uint16_t>();
        const int n_soft = r.get<std::uint16_t>();
        for (int k = 0; k < n_hard && r.ok; ++k)
            m.edges.hard.push_back({r.get<std::uint16_t>(), r.get<std::uint16_t>()});
        for (int k = 0; k < n_soft && r.ok; ++k)
            m.edges.soft.push_back({r.get<std::uint16_t>(), r.get<std::uint16_t>()});
        out.push_back(std::move(m));
    }
    if (!r.ok) return fail("smoothing: payload truncated");
    if (r.pos != bytes.size()) return fail("smoothing: trailing bytes after payload");
    return out;
}

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

        const bool has_merges = j.contains("merges");
        const bool has_edits = j.contains("shape_edits");
        const bool has_textures = j.contains("textures");
        const bool has_smoothing = j.contains("smoothing");
        if (!has_merges && !has_edits && !has_textures && !has_smoothing)
            return fail("mesh fix has none of \"merges\", \"shape_edits\", \"textures\", "
                        "\"smoothing\"");

        if (has_merges) {
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
        }

        if (has_edits) {
            auto bytes = base64_decode(j.at("shape_edits").get<std::string>());
            if (!bytes) return fail("shape_edits: invalid base64");
            std::string err;
            auto edits = decode_shape_edits(*bytes, &err);
            if (!edits) return fail(err);
            fix.shape_edits = std::move(*edits);
        }

        if (has_textures) {
            for (const auto& jt : j.at("textures")) {
                MeshFixTexture t{jt.at("block").get<std::uint32_t>(),
                                 jt.at("albedo").get<std::string>(), std::nullopt};
                if (jt.contains("flipbook")) {
                    const auto& jf = jt.at("flipbook");
                    if (!jf.is_object()) return fail("flipbook is not an object");
                    const auto& jframes = jf.at("frames");
                    if (!jframes.is_array()) return fail("flipbook frames is not an array");
                    if (!jf.at("fps").is_number()) return fail("flipbook fps is not a number");
                    MeshFixFlipbook fb;
                    for (const auto& name : jframes) fb.frames.push_back(name.get<std::string>());
                    fb.fps = jf.at("fps").get<float>();
                    t.flipbook = std::move(fb);
                }
                fix.textures.push_back(std::move(t));
            }
        }

        if (has_smoothing) {
            auto bytes = base64_decode(j.at("smoothing").get<std::string>());
            if (!bytes) return fail("smoothing: invalid base64");
            std::string err;
            auto recs = decode_smoothing(*bytes, &err);
            if (!recs) return fail(err);
            fix.smoothing = std::move(*recs);
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

/// One added vertex with every reference and attribute already resolved.
struct ResolvedAdd {
    glm::vec3 pos{0.0f};
    nif::TexCoord uv0{};
    std::vector<nif::TexCoord> extra_uvs;   // UV sets 1.. of the target
    nif::Color4 color{1.0f, 1.0f, 1.0f, 1.0f};
};

/// One shape edit, validated against the UNMODIFIED file, with every BSD2
/// reference resolved to a concrete value -- so applying it never reads data
/// that another merge or edit of the same fix may already have changed.
struct EditPlan {
    std::size_t data_idx = 0;
    std::vector<std::pair<std::uint16_t, glm::vec3>> moves;
    std::vector<std::pair<std::uint16_t, nif::TexCoord>> uvs;
    std::vector<ResolvedAdd> adds;
};

/// Resolves BSD2 references against the unmodified file (spec §6.1): a ref
/// names an ORIGINAL vertex of a NiTriShape; its position is carried
/// src-local -> model -> target-local through nif_block_world (in double).
class RefResolver {
public:
    explicit RefResolver(const nif::File& file) : file_(file) {}

    /// The referenced shape's data, or nullptr with *why set.
    const nif::NiTriShapeData* source(std::uint32_t block, std::string* why) const {
        if (block >= file_.blocks.size()) { *why = "reference block out of range"; return nullptr; }
        const auto* shape = std::get_if<nif::NiTriShape>(&file_.blocks[block]);
        if (!shape) { *why = "reference block is not a NiTriShape"; return nullptr; }
        const std::size_t di = index_of(file_, shape->data_link);
        const nif::NiTriShapeData* d =
            di == kNoIndex || di >= file_.blocks.size()
                ? nullptr : std::get_if<nif::NiTriShapeData>(&file_.blocks[di]);
        if (!d) { *why = "reference shape's data is unresolved"; return nullptr; }
        if (!d->has_vertices || d->vertices.size() != d->num_vertices) {
            *why = "reference shape's vertex array is inconsistent"; return nullptr;
        }
        return d;
    }

    std::string position(const ShapeEditPos& p, std::uint32_t target_block, glm::vec3* out) {
        if (!p.ref) {
            *out = glm::vec3(p.literal[0], p.literal[1], p.literal[2]);
            return finite(*out) ? "" : "non-finite literal position";
        }
        if (!std::isfinite(p.delta[0]) || !std::isfinite(p.delta[1]) || !std::isfinite(p.delta[2]))
            return "non-finite position delta";
        std::string why;
        const auto* d = source(p.ref->block, &why);
        if (!d) return why;
        if (p.ref->vertex >= d->num_vertices) return "reference vertex out of range";
        const nif::Vec3& v = d->vertices[p.ref->vertex];
        if (p.ref->block == target_block) {
            *out = glm::vec3(v.x, v.y, v.z);       // same frame: an exact copy
        } else {
            const glm::dmat4 to = glm::inverse(world(target_block)) * world(p.ref->block);
            *out = glm::vec3(to * glm::dvec4(v.x, v.y, v.z, 1.0));
        }
        *out += glm::vec3(p.delta[0], p.delta[1], p.delta[2]);
        return finite(*out) ? "" : "reference resolves to a non-finite position";
    }

    std::string uv(const ShapeEditUv& u, nif::TexCoord* out) const {
        if (!u.ref) {
            *out = {u.literal[0], u.literal[1]};
            return std::isfinite(out->u) && std::isfinite(out->v) ? "" : "non-finite literal uv";
        }
        std::string why;
        const auto* d = source(u.ref->block, &why);
        if (!d) return why;
        if (d->uv_sets.empty() || d->uv_sets[0].size() != d->num_vertices)
            return "reference shape has no consistent UV set 0";
        if (u.ref->vertex >= d->num_vertices) return "reference uv vertex out of range";
        *out = d->uv_sets[0][u.ref->vertex];
        return std::isfinite(out->u) && std::isfinite(out->v)
                   ? "" : "reference resolves to a non-finite uv";
    }

private:
    static bool finite(const glm::vec3& v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    }
    const glm::dmat4& world(std::size_t block) {
        auto it = world_.find(block);
        if (it == world_.end())
            it = world_.emplace(block, glm::dmat4(nif_block_world(file_, block))).first;
        return it->second;
    }
    const nif::File& file_;
    std::unordered_map<std::size_t, glm::dmat4> world_;
};

/// Validate edit `e` (index `edit_idx`) against the UNMODIFIED file and
/// resolve it into `*plan`. Returns "", else the refusal reason
/// ("shape edit N: ...").
std::string validate_edit(const nif::File& file, const ShapeEdit& e,
                          std::size_t edit_idx, RefResolver& refs, EditPlan* plan) {
    const std::string prefix = "shape edit " + std::to_string(edit_idx) + ": ";
    if (e.block >= file.blocks.size()) return prefix + "block out of range";
    const auto* shape = std::get_if<nif::NiTriShape>(&file.blocks[e.block]);
    if (!shape) return prefix + "block is not a NiTriShape";
    const std::size_t data_idx = index_of(file, shape->data_link);
    if (data_idx == kNoIndex || data_idx >= file.blocks.size())
        return prefix + "data_link unresolved";
    const auto* d = std::get_if<nif::NiTriShapeData>(&file.blocks[data_idx]);
    if (!d) return prefix + "data_link does not point at NiTriShapeData";
    if (d->has_normals) return prefix + "shape has authored normals (unsupported)";
    if (!d->has_vertices || d->vertices.size() != d->num_vertices)
        return prefix + "shape vertex array inconsistent";
    if (d->uv_sets.empty()) return prefix + "shape has no UV set";
    for (std::size_t k = 0; k < d->uv_sets.size(); ++k)
        if (d->uv_sets[k].size() != d->num_vertices)
            return prefix + "uv set " + std::to_string(k) + " size mismatch";
    if (d->has_vertex_colors && d->vertex_colors.size() != d->num_vertices)
        return prefix + "vertex color size mismatch";
    if (d->num_vertices != e.orig_vertex_count)
        return prefix + "original vertex count mismatch";
    if (d->num_triangles != e.orig_triangle_count ||
        d->triangles.size() != d->num_triangles)
        return prefix + "original triangle count mismatch";

    const std::size_t final_v = std::size_t{e.orig_vertex_count} + e.add_vertices.size();
    if (final_v > 65535) return prefix + "final vertex count exceeds 65535";

    EditPlan out;
    out.data_idx = data_idx;
    for (const auto& [i, p] : e.moves) {
        if (i >= e.orig_vertex_count) return prefix + "move index out of range";
        glm::vec3 v;
        if (std::string why = refs.position(p, e.block, &v); !why.empty())
            return prefix + "move: " + why;
        out.moves.emplace_back(i, v);
    }
    for (const auto& [i, u] : e.uvs) {
        if (i >= e.orig_vertex_count) return prefix + "uv index out of range";
        nif::TexCoord t;
        if (std::string why = refs.uv(u, &t); !why.empty()) return prefix + "uv: " + why;
        out.uvs.emplace_back(i, t);
    }
    for (const auto& av : e.add_vertices) {
        ResolvedAdd ra;
        if (std::string why = refs.position(av.pos, e.block, &ra.pos); !why.empty())
            return prefix + "added vertex: " + why;
        if (std::string why = refs.uv(av.uv0, &ra.uv0); !why.empty())
            return prefix + "added vertex: " + why;
        if (av.attr_src) {
            // BSD2: colour and UV sets 1.. copied from an original of this shape.
            if (*av.attr_src >= e.orig_vertex_count)
                return prefix + "added vertex attr_src out of range";
            for (std::size_t k = 1; k < d->uv_sets.size(); ++k)
                ra.extra_uvs.push_back(d->uv_sets[k][*av.attr_src]);
            if (d->has_vertex_colors) ra.color = d->vertex_colors[*av.attr_src];
        } else {
            // BSD1: literal attributes.
            const bool finite = std::isfinite(av.uv1[0]) && std::isfinite(av.uv1[1]) &&
                                std::all_of(av.color.begin(), av.color.end(),
                                            [](float c) { return std::isfinite(c); });
            if (!finite) return prefix + "non-finite added vertex field";
            for (std::size_t k = 1; k < d->uv_sets.size(); ++k)
                ra.extra_uvs.push_back({av.uv1[0], av.uv1[1]});
            ra.color = {av.color[0], av.color[1], av.color[2], av.color[3]};
        }
        out.adds.push_back(std::move(ra));
    }

    std::vector<bool> removed(e.orig_triangle_count, false);
    for (std::uint16_t t : e.remove_triangles) {
        if (t >= e.orig_triangle_count) return prefix + "removed triangle out of range";
        if (removed[t]) return prefix + "triangle removed twice";
        removed[t] = true;
    }
    const std::size_t final_t =
        std::size_t{e.orig_triangle_count} - e.remove_triangles.size() + e.add_triangles.size();
    if (final_t > 65535) return prefix + "final triangle count exceeds 65535";

    // Final positions, for the degenerate-triangle check.
    std::vector<glm::vec3> pos;
    pos.reserve(final_v);
    for (const auto& v : d->vertices) pos.emplace_back(v.x, v.y, v.z);
    for (const auto& [i, p] : out.moves) pos[i] = p;
    for (const auto& ra : out.adds) pos.push_back(ra.pos);
    for (const auto& t : e.add_triangles) {
        if (t[0] >= final_v || t[1] >= final_v || t[2] >= final_v)
            return prefix + "added triangle index out of range";
        if (t[0] == t[1] || t[1] == t[2] || t[0] == t[2])
            return prefix + "added triangle repeats an index";
        const glm::vec3 n = glm::cross(pos[t[1]] - pos[t[0]], pos[t[2]] - pos[t[0]]);
        if (glm::length(n) <= 1e-10f) return prefix + "added triangle has zero area";
    }
    *plan = std::move(out);
    return "";
}

void apply_edit(nif::File& file, const ShapeEdit& e, const EditPlan& plan) {
    auto& d = std::get<nif::NiTriShapeData>(file.blocks[plan.data_idx]);
    for (const auto& [i, p] : plan.moves) d.vertices[i] = {p.x, p.y, p.z};
    for (const auto& [i, uv] : plan.uvs) d.uv_sets[0][i] = uv;
    for (const auto& ra : plan.adds) {
        d.vertices.push_back({ra.pos.x, ra.pos.y, ra.pos.z});
        d.uv_sets[0].push_back(ra.uv0);
        for (std::size_t s = 1; s < d.uv_sets.size(); ++s)
            d.uv_sets[s].push_back(ra.extra_uvs[s - 1]);
        if (d.has_vertex_colors) d.vertex_colors.push_back(ra.color);
    }
    std::vector<bool> removed(d.triangles.size(), false);
    for (std::uint16_t t : e.remove_triangles) removed[t] = true;
    std::vector<std::array<std::uint16_t, 3>> tris;
    tris.reserve(d.triangles.size() - e.remove_triangles.size() + e.add_triangles.size());
    for (std::size_t t = 0; t < d.triangles.size(); ++t)
        if (!removed[t]) tris.push_back(d.triangles[t]);
    for (const auto& t : e.add_triangles) tris.push_back(t);
    d.triangles = std::move(tris);

    d.num_vertices = static_cast<std::uint16_t>(d.vertices.size());
    d.num_triangles = static_cast<std::uint16_t>(d.triangles.size());
    d.num_triangle_points = static_cast<std::uint32_t>(d.triangles.size()) * 3;
    d.num_match_groups = 0;
    d.match_groups.clear();

    glm::vec3 lo(std::numeric_limits<float>::max()), hi(-std::numeric_limits<float>::max());
    for (const auto& v : d.vertices) {
        lo = glm::min(lo, glm::vec3(v.x, v.y, v.z));
        hi = glm::max(hi, glm::vec3(v.x, v.y, v.z));
    }
    const glm::vec3 c = (lo + hi) * 0.5f;
    float r = 0.0f;
    for (const auto& v : d.vertices) r = std::max(r, glm::length(glm::vec3(v.x, v.y, v.z) - c));
    d.bound_center = {c.x, c.y, c.z};
    d.bound_radius = r;
}

/// Validate texture op `t` (index `tex_idx`) against the UNMODIFIED file.
/// Returns "" or the refusal reason ("texture N: ...").
/// "" if `name` can bind as a plain Base diffuse, else why not (`what` names
/// the field in the message, e.g. "albedo" or "flipbook frame 3").
std::string check_albedo_name(const std::string& name, const std::string& what) {
    if (name.empty()) return what + " is empty";
    if (name.find_first_of("/\\") != std::string::npos)
        return what + " must be a bare filename (no directory)";
    // The NIF texture loader decodes TGA only (model_build.cc: decode_tga).
    const auto dot = name.find_last_of('.');
    std::string ext = dot == std::string::npos ? "" : name.substr(dot);
    std::transform(ext.begin(), ext.end(), ext.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (ext != ".tga") return what + " must be a .tga file";
    // Mirrors model_build.cc's filename_is_glow / _specular / _normal (case-
    // insensitive, on the extension-less stem): such a file binds to Glow,
    // Gloss or Bump rather than as a plain Base diffuse.
    std::string stem = name.substr(0, dot);
    std::transform(stem.begin(), stem.end(), stem.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    for (const char* suffix : {"_glow", "_specular", "_spec", "_normal", "_norm"}) {
        const std::string_view sv(suffix);
        if (stem.size() >= sv.size() && stem.compare(stem.size() - sv.size(), sv.size(), sv) == 0)
            return what + " '" + name + "' has the reserved suffix '" +
                   std::string(sv) + "' and would not bind as a plain diffuse";
    }
    // Mirrors model_build.cc's filename_is_emissive: an emissive sibling map
    // (task 17) is a derived map that is never probed for siblings itself.
    for (const char* suffix : {"_emissive_y", "_emissive_r", "_emissive_s", "_emissive"}) {
        const std::string_view sv(suffix);
        if (stem.size() >= sv.size() && stem.compare(stem.size() - sv.size(), sv.size(), sv) == 0)
            return what + " '" + name + "' has the reserved suffix '" + std::string(sv) +
                   "': it names an emissive sibling map, not an albedo (use the "
                   "base name; the loader finds its emissive maps beside it)";
    }
    return "";
}

constexpr std::size_t kFlipbookMinFrames = 2;
constexpr std::size_t kFlipbookMaxFrames = 256;

std::string validate_texture(const nif::File& file, const MeshFixTexture& t,
                             std::size_t tex_idx) {
    const std::string prefix = "texture " + std::to_string(tex_idx) + ": ";
    if (t.block >= file.blocks.size()) return prefix + "block out of range";
    if (!std::holds_alternative<nif::NiTriShape>(file.blocks[t.block]))
        return prefix + "block is not a NiTriShape";
    if (std::string err = check_albedo_name(t.albedo, "albedo"); !err.empty())
        return prefix + err;
    if (!t.flipbook) return "";
    const auto& fb = *t.flipbook;
    if (fb.frames.size() < kFlipbookMinFrames || fb.frames.size() > kFlipbookMaxFrames)
        return prefix + "flipbook needs 2..256 frames, has " + std::to_string(fb.frames.size());
    for (std::size_t k = 0; k < fb.frames.size(); ++k) {
        std::string err = check_albedo_name(fb.frames[k], "flipbook frame " + std::to_string(k));
        if (!err.empty()) return prefix + err;
    }
    if (fb.frames.front() != t.albedo)
        return prefix + "albedo '" + t.albedo + "' must equal flipbook frame 0 '" +
               fb.frames.front() + "'";
    if (!std::isfinite(fb.fps) || fb.fps <= 0.0f)
        return prefix + "flipbook fps must be finite and > 0";
    return "";
}

/// Give shape `t.block` its OWN NiTextureProperty, appended with fresh link
/// ids. gather_material_inputs visits the shape's own property_links before
/// any ancestor's, so it wins over the inherited (shared) texture while
/// siblings keep theirs.
///
/// Plain op: property -> one external NiImage (`t.albedo`); field values
/// mirror the stock DBridge pair (NiTextureProperty flags 0; NiImage
/// defaults).
///
/// Flipbook op: the shape of BC's only stock flip controller (EBridge.nif:
/// NiTextureProperty 549 -> NiFlipController 550, guarded by
/// MeshFixFlipbook.RealEbridgeStockControllerHasTheMirroredShape): the
/// property's image_link is 0 and its controller_link names the controller
/// (model_build substitutes source 0 as the static Base); the controller has
/// flags 0x0009 (active, cycle type loop), frequency 1, phase 0, start 0,
/// stop = N * delta, texture_slot 0, no next controller, and its v3.1
/// target field (`unknown_integer`) naming the property; one external
/// NiImage per frame. delta = 1 / fps.
void apply_texture(nif::File& file, const MeshFixTexture& t) {
    // Link ids are handed out in append order, so block k appended after
    // this point has id first_id + k. Identity ids (empty block_ids) for
    // synthetic files: link == index.
    const bool identity = file.block_ids.empty();
    std::uint32_t max_id = 0;
    for (std::uint32_t id : file.block_ids) max_id = std::max(max_id, id);
    const std::uint32_t first_id =
        identity ? static_cast<std::uint32_t>(file.blocks.size()) : max_id + 1;
    std::uint32_t appended = 0;
    auto append = [&](nif::Block b) {
        file.blocks.push_back(std::move(b));
        if (!identity) file.block_ids.push_back(first_id + appended);
        ++appended;
    };
    std::uint32_t prop_id = first_id;

    if (!t.flipbook) {
        nif::NiImage img;
        img.use_external = 1;
        img.file_name = t.albedo;
        append(img);
        prop_id = first_id + 1;
        nif::NiTextureProperty prop;
        prop.image_link = first_id;
        append(prop);
    } else {
        const auto& fb = *t.flipbook;
        const auto n = static_cast<std::uint32_t>(fb.frames.size());
        const std::uint32_t ctrl_id = first_id + 1;
        nif::NiTextureProperty prop;
        prop.image_link = 0;
        prop.obj.controller_link = ctrl_id;
        append(prop);
        nif::NiFlipController ctrl;
        ctrl.flags = 0x0009;
        ctrl.frequency = 1.0f;
        ctrl.phase = 0.0f;
        ctrl.start_time = 0.0f;
        ctrl.delta = 1.0f / fb.fps;
        ctrl.stop_time = static_cast<float>(n) * ctrl.delta;
        ctrl.unknown_integer = prop_id;
        ctrl.texture_slot = 0;
        ctrl.num_sources = n;
        for (std::uint32_t k = 0; k < n; ++k) ctrl.image_links.push_back(ctrl_id + 1 + k);
        append(ctrl);
        for (const auto& name : fb.frames) {
            nif::NiImage img;
            img.use_external = 1;
            img.file_name = name;
            append(img);
        }
    }

    std::get<nif::NiTriShape>(file.blocks[t.block]).av.property_links.push_back(prop_id);
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

namespace {

/// Validate one smoothing record against the unmodified file (spec
/// 2026-10-27-bridge-authored-smoothing-design §3.2) and return its data
/// block index in *data_idx. Returns "", else the refusal reason.
std::string validate_smoothing(const nif::File& file, const MeshFixSmoothing& m,
                               std::size_t idx, const MeshFix& fix,
                               const std::vector<MergePlan>& plans,
                               std::size_t* data_idx) {
    const std::string prefix = "smoothing " + std::to_string(idx) + ": ";
    if (m.block >= file.blocks.size()) return prefix + "block out of range";
    const auto* shape = std::get_if<nif::NiTriShape>(&file.blocks[m.block]);
    if (!shape) return prefix + "block is not a NiTriShape";
    *data_idx = index_of(file, shape->data_link);
    if (*data_idx == kNoIndex || *data_idx >= file.blocks.size())
        return prefix + "data_link unresolved";
    const auto* d = std::get_if<nif::NiTriShapeData>(&file.blocks[*data_idx]);
    if (!d) return prefix + "data_link does not point at NiTriShapeData";
    for (std::size_t mi = 0; mi < plans.size(); ++mi) {
        if (*data_idx == plans[mi].target_data_idx || *data_idx == plans[mi].patch_data_idx)
            return prefix + "data block " + std::to_string(*data_idx) +
                   " is used by merge " + std::to_string(mi);
    }
    for (std::size_t bi = 0; bi < file.blocks.size(); ++bi) {
        const auto* other = std::get_if<nif::NiTriShape>(&file.blocks[bi]);
        if (other && bi != m.block && index_of(file, other->data_link) == *data_idx)
            return prefix + "data block " + std::to_string(*data_idx) +
                   " is shared with shape " + std::to_string(bi);
    }
    if (d->has_normals) return prefix + "shape has authored normals (unsupported)";
    std::size_t final_v = d->num_vertices;
    for (const auto& e : fix.shape_edits)
        if (e.block == m.block) final_v += e.add_vertices.size();
    if (m.vertex_count != final_v)
        return prefix + "vertex count " + std::to_string(m.vertex_count) +
               " != final vertex count " + std::to_string(final_v);
    for (const auto* list : {&m.edges.hard, &m.edges.soft}) {
        for (std::size_t k = 0; k < list->size(); ++k) {
            const auto& [a, b] = (*list)[k];
            if (a >= b) return prefix + "edge is not ascending (a < b)";
            if (b >= m.vertex_count) return prefix + "edge index out of range";
            if (k > 0 && (*list)[k] <= (*list)[k - 1])
                return prefix + "edges are not strictly ascending";
        }
    }
    for (const auto& h : m.edges.hard)
        if (std::binary_search(m.edges.soft.begin(), m.edges.soft.end(), h))
            return prefix + "an edge is listed as both hard and soft";
    return "";
}

}  // namespace

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

    // Every shape edit is validated and its references resolved here, on the
    // UNMODIFIED file, before any merge or edit mutates it: a reference
    // always reads original data, even into a shape this same fix edits.
    std::vector<EditPlan> edit_plans(fix.shape_edits.size());
    RefResolver refs(file);
    for (std::size_t i = 0; i < fix.shape_edits.size(); ++i) {
        std::string err = validate_edit(file, fix.shape_edits[i], i, refs, &edit_plans[i]);
        if (!err.empty()) return err;
        // A data block may be edited once, and never by a merge too.
        auto [it, inserted] = data_block_owner.try_emplace(edit_plans[i].data_idx,
                                                           plans.size() + i);
        if (!inserted) {
            return "shape edit " + std::to_string(i) + ": data block " +
                   std::to_string(edit_plans[i].data_idx) +
                   " is already used by another merge or shape edit";
        }
    }

    // Smoothing records only annotate a shape's final vertices, so they may
    // follow a shape edit of the same block but never a merge (which grows
    // or hides the data), and a data block takes one record.
    std::vector<std::size_t> smoothing_data(fix.smoothing.size(), 0);
    std::unordered_map<std::size_t, std::size_t> smoothing_owner;  // data idx -> first record
    for (std::size_t i = 0; i < fix.smoothing.size(); ++i) {
        std::string err = validate_smoothing(file, fix.smoothing[i], i, fix, plans, &smoothing_data[i]);
        if (!err.empty()) return err;
        auto [it, inserted] = smoothing_owner.try_emplace(smoothing_data[i], i);
        if (!inserted)
            return "smoothing " + std::to_string(i) + ": block " +
                   std::to_string(fix.smoothing[i].block) + " already has smoothing record " +
                   std::to_string(it->second);
    }

    // Texture ops are independent of geometry: a block may take one texture
    // op whether or not it is also merged or edited.
    std::unordered_map<std::uint32_t, std::size_t> texture_owner;  // block -> first op
    for (std::size_t i = 0; i < fix.textures.size(); ++i) {
        std::string err = validate_texture(file, fix.textures[i], i);
        if (!err.empty()) return err;
        for (const auto& plan : plans) {
            if (plan.patch_shape_idx == fix.textures[i].block)
                return "texture " + std::to_string(i) + ": block " +
                       std::to_string(fix.textures[i].block) +
                       " is a merge's patch (hidden and folded into its target)";
        }
        auto [it, inserted] = texture_owner.try_emplace(fix.textures[i].block, i);
        if (!inserted) {
            return "texture " + std::to_string(i) + ": block " +
                   std::to_string(fix.textures[i].block) +
                   " already has texture op " + std::to_string(it->second);
        }
    }

    for (std::size_t i = 0; i < fix.merges.size(); ++i) {
        apply_merge(file, fix.merges[i], plans[i]);
    }
    for (std::size_t i = 0; i < fix.shape_edits.size(); ++i)
        apply_edit(file, fix.shape_edits[i], edit_plans[i]);
    for (std::size_t i = 0; i < fix.smoothing.size(); ++i)
        std::get<nif::NiTriShapeData>(file.blocks[smoothing_data[i]]).authored_edges =
            fix.smoothing[i].edges;
    if (!fix.textures.empty()) {
        // Appending may reallocate `blocks`; File::root points at block 0.
        const bool had_root = file.root.ptr != nullptr;
        for (const auto& t : fix.textures) apply_texture(file, t);
        if (had_root) file.root = nif::BlockHandle{&file.blocks.front()};
    }
    return "";
}

}  // namespace assets
