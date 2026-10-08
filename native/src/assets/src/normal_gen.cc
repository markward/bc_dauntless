#include "normal_gen.h"

#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <utility>
#include <vector>

namespace assets::detail {

namespace {

using PosKey = std::array<std::uint32_t, 3>;

PosKey pos_key(const glm::vec3& p) {
    PosKey k;
    std::memcpy(k.data(), &p.x, sizeof(float) * 3);
    return k;
}

// Where a vertex of the joint pass's combined mesh came from: the shape that
// owns it and its position in that shape's own frame.
struct VertexOrigin {
    std::uint32_t shape;
    glm::vec3     local_pos;
};

// Every per-vertex channel the joint pass carries, grown in lockstep.
struct VertexChannels {
    MeshCpu&                   mesh;
    std::vector<glm::vec4>&    source_colours;  // may be empty: stays empty
    std::vector<VertexOrigin>* origins;         // nullptr outside the joint pass

    // Copy vertex v.
    std::uint32_t duplicate(std::uint32_t v) {
        mesh.vertices.push_back(mesh.vertices[v]);
        for (auto& set : mesh.extra_uvs)
            if (v < set.size()) set.push_back(set[v]);
        if (!source_colours.empty()) source_colours.push_back(source_colours[v]);
        if (origins) origins->push_back((*origins)[v]);
        return static_cast<std::uint32_t>(mesh.vertices.size() - 1);
    }

    // New vertex on a->b at parameter t, carrying a's attributes interpolated
    // towards b's. The owner shape is a's.
    std::uint32_t interpolate(std::uint32_t a, std::uint32_t b, float t) {
        MeshCpu::Vertex v = mesh.vertices[a];
        const auto& vb = mesh.vertices[b];
        v.position = glm::mix(v.position, vb.position, t);
        v.uv = glm::mix(v.uv, vb.uv, t);
        v.uv1 = glm::mix(v.uv1, vb.uv1, t);
        v.color = glm::u8vec4(glm::round(glm::mix(glm::vec4(v.color), glm::vec4(vb.color), t)));
        mesh.vertices.push_back(v);
        for (auto& set : mesh.extra_uvs)
            if (a < set.size() && b < set.size()) set.push_back(glm::mix(set[a], set[b], t));
        if (!source_colours.empty())
            source_colours.push_back(glm::mix(source_colours[a], source_colours[b], t));
        if (origins) {
            const VertexOrigin& oa = (*origins)[a];
            const VertexOrigin& ob = (*origins)[b];
            origins->push_back({oa.shape, glm::mix(oa.local_pos, ob.local_pos, t)});
        }
        return static_cast<std::uint32_t>(mesh.vertices.size() - 1);
    }
};

// Distinct vertices at one position with identical attributes: the only
// reason an exporter splits those is a hard edge. Vertices from different
// shapes (or different local positions) are never twins.
bool is_twin(const VertexChannels& ch, std::uint32_t a, std::uint32_t b) {
    const MeshCpu& m = ch.mesh;
    const auto& src_col = ch.source_colours;
    const auto& va = m.vertices[a];
    const auto& vb = m.vertices[b];
    if (va.uv != vb.uv || va.uv1 != vb.uv1) return false;
    if (a < src_col.size() && b < src_col.size()) {
        if (src_col[a] != src_col[b]) return false;
    } else if (va.color != vb.color) {
        return false;
    }
    for (const auto& set : m.extra_uvs)
        if (a < set.size() && b < set.size() && set[a] != set[b]) return false;
    if (ch.origins) {
        const VertexOrigin& oa = (*ch.origins)[a];
        const VertexOrigin& ob = (*ch.origins)[b];
        if (oa.shape != ob.shape || oa.local_pos != ob.local_pos) return false;
    }
    return true;
}

void smooth_normals_impl(VertexChannels& ch, float crease_deg) {
    MeshCpu& m = ch.mesh;
    const std::size_t tri_count = m.indices.size() / 3;
    if (tri_count == 0) return;
    const float cos_crease = std::cos(glm::radians(crease_deg));

    std::vector<glm::vec3> face_n(tri_count, glm::vec3(0.0f));
    std::vector<float> face_area(tri_count, 0.0f);
    for (std::size_t t = 0; t < tri_count; ++t) {
        const glm::vec3 p0 = m.vertices[m.indices[t * 3 + 0]].position;
        const glm::vec3 p1 = m.vertices[m.indices[t * 3 + 1]].position;
        const glm::vec3 p2 = m.vertices[m.indices[t * 3 + 2]].position;
        const glm::vec3 c = glm::cross(p1 - p0, p2 - p0);
        const float len = glm::length(c);
        if (len < 1e-12f) continue;  // degenerate: contributes nothing
        face_n[t] = c / len;
        face_area[t] = 0.5f * len;
    }

    // Weld corners by position (corner id = t*3 + k).
    std::map<PosKey, std::uint32_t> weld_id;
    std::vector<std::uint32_t> corner_w(tri_count * 3);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const auto key = pos_key(m.vertices[m.indices[c]].position);
        auto it = weld_id.try_emplace(key, static_cast<std::uint32_t>(weld_id.size())).first;
        corner_w[c] = it->second;
    }

    // Smoothing groups: corners around one welded position join when their
    // faces share an EDGE whose fold is under the crease, chained around the
    // fan. Union-find with parity: parity = this corner's orientation relative
    // to its parent (+1 same, -1 flipped), because BC winding is mixed and the
    // shared edge tells us exactly when a neighbour is wound the other way.
    std::vector<std::uint32_t> parent(tri_count * 3);
    std::vector<int> parity(tri_count * 3, 1);
    for (std::uint32_t c = 0; c < parent.size(); ++c) parent[c] = c;
    auto find = [&](std::uint32_t x) {
        int sign = 1;
        while (parent[x] != x) { sign *= parity[x]; x = parent[x]; }
        return std::pair<std::uint32_t, int>{x, sign};
    };
    auto unite = [&](std::uint32_t a, std::uint32_t b, int s) {
        const auto [ra, pa] = find(a);
        const auto [rb, pb] = find(b);
        if (ra == rb) return;
        parent[rb] = ra;
        parity[rb] = pa * s * pb;
    };

    struct EdgeUse { std::uint32_t tri; std::uint32_t ca, cb; bool forward; };
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::vector<EdgeUse>> edges;
    for (std::uint32_t t = 0; t < tri_count; ++t) {
        if (glm::length(face_n[t]) < 0.5f) continue;  // degenerate
        for (std::uint32_t k = 0; k < 3; ++k) {
            const std::uint32_t ca = t * 3 + k, cb = t * 3 + (k + 1) % 3;
            const std::uint32_t wa = corner_w[ca], wb = corner_w[cb];
            if (wa == wb) continue;
            const bool fwd = wa < wb;
            edges[{std::min(wa, wb), std::max(wa, wb)}].push_back(
                {t, fwd ? ca : cb, fwd ? cb : ca, fwd});
        }
    }
    for (const auto& [key, uses] : edges) {
        for (std::size_t i = 0; i < uses.size(); ++i) {
            for (std::size_t j = i + 1; j < uses.size(); ++j) {
                const EdgeUse& a = uses[i];
                const EdgeUse& b = uses[j];
                // Consistent winding walks a shared edge in opposite
                // directions; the same direction means b is flipped.
                const int s = (a.forward == b.forward) ? -1 : 1;
                if (s * glm::dot(face_n[a.tri], face_n[b.tri]) < cos_crease) continue;
                const std::pair<std::uint32_t, std::uint32_t> ends[2] = {
                    {a.ca, b.ca}, {a.cb, b.cb}};
                for (const auto& [c1, c2] : ends) {
                    const std::uint32_t v1 = m.indices[c1], v2 = m.indices[c2];
                    if (v1 != v2 && is_twin(ch, v1, v2)) continue;
                    unite(c1, c2, s);
                }
            }
        }
    }

    std::vector<glm::vec3> group_sum(tri_count * 3, glm::vec3(0.0f));
    std::vector<int> corner_sign(tri_count * 3, 1);
    std::vector<std::uint32_t> corner_root(tri_count * 3);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const auto [r, sign] = find(c);
        corner_root[c] = r;
        corner_sign[c] = sign;
        group_sum[r] += static_cast<float>(sign) * face_n[c / 3] * face_area[c / 3];
    }
    std::vector<glm::vec3> corner_n(tri_count * 3, glm::vec3(0.0f));
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const glm::vec3& sum = group_sum[corner_root[c]];
        const float len = glm::length(sum);
        const glm::vec3& own = face_n[c / 3];
        corner_n[c] = len > 1e-12f ? static_cast<float>(corner_sign[c]) * sum / len
                    : (glm::length(own) > 0.5f ? own : glm::vec3(0, 0, 1));
    }

    // One normal per vertex: corners of the same vertex that disagree get
    // their own copy of the vertex.
    std::vector<std::vector<std::uint32_t>> variants(m.vertices.size());
    std::vector<bool> assigned(m.vertices.size(), false);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const std::uint32_t v = m.indices[c];
        const glm::vec3& n = corner_n[c];
        if (!assigned[v]) {
            m.vertices[v].normal = n;
            assigned[v] = true;
            variants[v].push_back(v);
            continue;
        }
        std::uint32_t found = UINT32_MAX;
        for (std::uint32_t cand : variants[v])
            if (glm::dot(m.vertices[cand].normal, n) > 0.9999f) { found = cand; break; }
        if (found == UINT32_MAX) {
            found = ch.duplicate(v);
            m.vertices[found].normal = n;
            variants[v].push_back(found);
        }
        m.indices[c] = found;
    }
    for (std::size_t v = 0; v < assigned.size(); ++v)
        if (!assigned[v]) m.vertices[v].normal = glm::vec3(0, 0, 1);  // unreferenced
}

void repair_t_junctions_impl(VertexChannels& ch) {
    MeshCpu& m = ch.mesh;
    // Distinct positions: the candidates that may lie inside an edge.
    std::vector<glm::vec3> points;
    {
        std::map<PosKey, bool> seen;
        for (const auto& v : m.vertices)
            if (seen.try_emplace(pos_key(v.position), true).second)
                points.push_back(v.position);
    }

    // Points strictly inside edge a->b: parameter u in (eps, 1-eps) and a
    // perpendicular distance under 1e-3 of the edge length.
    auto points_inside = [&](const glm::vec3& a, const glm::vec3& b) {
        std::vector<glm::vec3> found;
        const glm::vec3 ab = b - a;
        const float len2 = glm::dot(ab, ab);
        if (len2 < 1e-12f) return found;
        const float tol = 1e-3f * std::sqrt(len2);
        for (const auto& p : points) {
            const float u = glm::dot(p - a, ab) / len2;
            if (u <= 1e-3f || u >= 1.0f - 1e-3f) continue;
            if (glm::length(p - a - u * ab) < tol) found.push_back(p);
        }
        return found;
    };
    auto param = [](const glm::vec3& a, const glm::vec3& b, const glm::vec3& p) {
        const glm::vec3 ab = b - a;
        return glm::dot(p - a, ab) / glm::dot(ab, ab);
    };

    // New vertex on edge a->b at parameter u, carrying the triangle's own
    // attributes interpolated along the edge; position is the T vertex's.
    auto insert = [&](std::uint32_t a, std::uint32_t b, float u, const glm::vec3& p) {
        // Interpolate with the endpoints in a FIXED order (lexicographic by
        // position), recomputing u for that order. Both triangles sharing
        // this edge walk it in opposite directions; without a canonical order
        // their interpolated attributes (incl. the joint pass's local
        // positions) differ in the last bit and the shared edge cracks.
        const glm::vec3& pa = m.vertices[a].position;
        const glm::vec3& pb = m.vertices[b].position;
        if (std::lexicographical_compare(&pb.x, &pb.x + 3, &pa.x, &pa.x + 3)) {
            std::swap(a, b);
            u = param(m.vertices[a].position, m.vertices[b].position, p);
        }
        const std::uint32_t v = ch.interpolate(a, b, u);
        m.vertices[v].position = p;
        return v;
    };

    // Each work item carries, per edge, the T points still to insert on it.
    // Only the triangle's ORIGINAL edges are searched: a diagonal created by a
    // split starts empty, because a vertex on it lies inside the face
    // (overlapping geometry), not on a neighbour's edge.
    struct Work {
        std::array<std::uint32_t, 3> v;
        std::array<std::vector<glm::vec3>, 3> pts;
    };
    std::vector<std::uint32_t> out;
    out.reserve(m.indices.size());
    for (std::size_t t = 0; t < m.indices.size() / 3; ++t) {
        Work first;
        first.v = {m.indices[t * 3], m.indices[t * 3 + 1], m.indices[t * 3 + 2]};
        for (int e = 0; e < 3; ++e)
            first.pts[e] = points_inside(m.vertices[first.v[e]].position,
                                         m.vertices[first.v[(e + 1) % 3]].position);
        std::vector<Work> work = {std::move(first)};
        while (!work.empty()) {
            Work w = std::move(work.back());
            work.pop_back();
            int k = -1;
            for (int e = 0; e < 3; ++e) if (!w.pts[e].empty()) { k = e; break; }
            if (k < 0) {
                out.insert(out.end(), w.v.begin(), w.v.end());
                continue;
            }
            const std::uint32_t a = w.v[k], b = w.v[(k + 1) % 3], c = w.v[(k + 2) % 3];
            const glm::vec3 pa = m.vertices[a].position, pb = m.vertices[b].position;
            const glm::vec3 p = w.pts[k][w.pts[k].size() / 2];
            const float u = param(pa, pb, p);
            std::vector<glm::vec3> lo, hi;
            for (const auto& q : w.pts[k]) {
                if (q == p) continue;
                (param(pa, pb, q) < u ? lo : hi).push_back(q);
            }
            const std::uint32_t v = insert(a, b, u, p);
            // Same winding as (a, b, c).
            Work w1{{a, v, c}, {std::move(lo), {}, w.pts[(k + 2) % 3]}};
            Work w2{{v, b, c}, {std::move(hi), w.pts[(k + 1) % 3], {}}};
            work.push_back(std::move(w1));
            work.push_back(std::move(w2));
        }
    }
    m.indices = std::move(out);
}

// Shape-frame position -> shared model space, snapped (1/1024 unit) so
// coincident vertices from different node frames weld despite float
// round-off in the transform.
glm::vec3 to_shared(const glm::mat4& xf, const glm::vec3& p) {
    const glm::vec3 q = glm::vec3(xf * glm::vec4(p, 1.0f));
    return glm::round(q * 1024.0f) / 1024.0f;
}

}  // namespace

void generate_smooth_normals(MeshCpu& mesh, float crease_deg,
                             const std::vector<glm::vec4>& source_colours) {
    std::vector<glm::vec4> colours =
        source_colours.size() == mesh.vertices.size() ? source_colours
                                                      : std::vector<glm::vec4>{};
    VertexChannels ch{mesh, colours, nullptr};
    smooth_normals_impl(ch, crease_deg);
}

void repair_t_junctions(MeshCpu& mesh, std::vector<glm::vec4>& source_colours) {
    // Colours that are not parallel to the vertices are left as they are.
    std::vector<glm::vec4> none;
    auto& colours = source_colours.size() == mesh.vertices.size() ? source_colours : none;
    VertexChannels ch{mesh, colours, nullptr};
    repair_t_junctions_impl(ch);
}

void generate_normals_across_shapes(std::vector<NormalGenShape>& shapes, float crease_deg) {
    std::size_t max_extra = 0;
    for (const auto& s : shapes)
        if (s.mesh) max_extra = std::max(max_extra, s.mesh->extra_uvs.size());

    // One combined mesh in the shared space. Each shape's real extra-UV sets
    // are padded to the common count; provenance (owner shape, own-frame
    // position) rides in `origins`, grown in lockstep with the vertices.
    MeshCpu all;
    all.extra_uvs.assign(max_extra, {});
    std::vector<glm::vec4> src;
    std::vector<VertexOrigin> origins;
    for (std::size_t s = 0; s < shapes.size(); ++s) {
        if (!shapes[s].mesh) continue;
        const MeshCpu& m = *shapes[s].mesh;
        const glm::mat4& xf = shapes[s].to_model;
        const auto& cols = shapes[s].source_colours;
        const auto base = static_cast<std::uint32_t>(all.vertices.size());
        for (std::size_t v = 0; v < m.vertices.size(); ++v) {
            MeshCpu::Vertex cv = m.vertices[v];
            cv.position = to_shared(xf, cv.position);
            all.vertices.push_back(cv);
            for (std::size_t c = 0; c < max_extra; ++c)
                all.extra_uvs[c].push_back(c < m.extra_uvs.size() && v < m.extra_uvs[c].size()
                                           ? m.extra_uvs[c][v] : glm::vec2(0.0f));
            src.push_back(v < cols.size() ? cols[v] : glm::vec4(m.vertices[v].color) / 255.0f);
            origins.push_back({static_cast<std::uint32_t>(s), m.vertices[v].position});
        }
        for (std::uint32_t idx : m.indices) all.indices.push_back(base + idx);
    }
    if (all.vertices.empty()) return;

    VertexChannels ch{all, src, &origins};
    repair_t_junctions_impl(ch);
    smooth_normals_impl(ch, crease_deg);

    // Split back into the original shapes, in their own frames.
    for (std::size_t s = 0; s < shapes.size(); ++s) {
        if (!shapes[s].mesh) continue;
        MeshCpu& m = *shapes[s].mesh;
        const glm::mat4& xf = shapes[s].to_model;
        const glm::mat3 to_local = glm::transpose(glm::mat3(xf));
        const std::size_t own_extra = m.extra_uvs.size();
        // Exact local position of this shape's ORIGINAL vertices, keyed by
        // their snapped shared-space position. A vertex the repair inserted
        // at one of those points takes it verbatim, so it meets the T vertex
        // with no gap (interpolating along the split edge would land a hair
        // off it and crack).
        std::map<PosKey, glm::vec3> own_local;
        for (const auto& v : m.vertices)
            own_local.try_emplace(pos_key(to_shared(xf, v.position)), v.position);

        std::vector<std::int64_t> remap(all.vertices.size(), -1);
        MeshCpu out;
        out.extra_uvs.assign(own_extra, {});
        for (std::size_t c = 0; c + 2 < all.indices.size(); c += 3) {
            if (origins[all.indices[c]].shape != s) continue;
            for (int k = 0; k < 3; ++k) {
                const std::uint32_t cv = all.indices[c + k];
                if (remap[cv] < 0) {
                    remap[cv] = static_cast<std::int64_t>(out.vertices.size());
                    MeshCpu::Vertex v = all.vertices[cv];
                    auto own = own_local.find(pos_key(all.vertices[cv].position));
                    v.position = own != own_local.end() ? own->second
                                                        : origins[cv].local_pos;
                    v.normal = glm::normalize(to_local * v.normal);
                    out.vertices.push_back(v);
                    for (std::size_t e = 0; e < own_extra; ++e)
                        out.extra_uvs[e].push_back(all.extra_uvs[e][cv]);
                }
                out.indices.push_back(static_cast<std::uint32_t>(remap[cv]));
            }
        }
        m.vertices = std::move(out.vertices);
        m.indices = std::move(out.indices);
        m.extra_uvs = std::move(out.extra_uvs);
    }
}

}  // namespace assets::detail
